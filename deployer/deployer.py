#!/usr/bin/env python

import argparse
import gevent
import logging
import os
import sys
import yaml
import oauth.oauth as oauth
import httplib2
import uuid
import json
import time

from gevent import monkey
from gevent import subprocess
from gevent import queue
from gevent import lock
from jujuclient import exc
from jujuclient.juju2 import environment

import helpers.utils as utils

# MAAS STATES
STATE = {
    0: "DEFAULT",
    1: "COMMISSIONING",
    2: "FAILED_COMMISSIONING",
    3: "MISSING",
    4: "READY",
    5: "RESERVED",
    6: "DEPLOYED",
    7: "RETIRED",
    8: "BROKEN",
    9: "DEPLOYING",
    10: "ALLOCATED",
    11: "FAILED_DEPLOYMENT",
    12: "RELEASING",
    13: "FAILED_RELEASING",
    14: "DISK_ERASING",
    15: "FAILED_DISK_ERASING"
}

PYTHON_PATH = os.path.dirname(os.path.abspath(os.path.normpath(sys.argv[0])))
sys.path.append(PYTHON_PATH)

monkey.patch_all()

LOG = logging.getLogger()
LOG.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - '
                              '%(levelname)s - %(message)s')
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)

LOG.addHandler(ch)

parser = argparse.ArgumentParser(prog="Deployer")
subparsers = parser.add_subparsers(dest="action")
parser.add_argument("--clouds-and-credentials",
                    dest="clouds_and_credentials",
                    type=str,
                    required=True,
                    help="Specified yaml must contain the following: "
                         "'endpoint' of MAAS, 'maas-oauth', "
                         "'environment' of MAAS, 'user' and 'password'"
                         "of juju user used to run jujuclient. "
                         "Example of yaml:\n "
                         "'endpoint': 'http://<ip>/MAAS/'\n"
                         "'maas-oauth': 'maas-oauth'\n"
                         "'environment': 'controller-name:model-name'\n"
                         "'user': 'user'\n"
                         "'password': 'password'\n")

teardown_parser = subparsers.add_parser('teardown')
teardown_parser.add_argument("--search-string",
                             dest="search_string",
                             type=str,
                             required=True,
                             help="Deploy uuid")
teardown_parser.add_argument("--template",
                              dest="template",
                              type=str,
                              required=False,
                              help="Juju deployer template")

deploy_parser = subparsers.add_parser('deploy')
deploy_parser.add_argument("--search-string",
                           dest="search_string",
                           type=str,
                           required=False,
                           help="Deploy uuid")
deploy_parser.add_argument("--template",
                           dest="template",
                           type=str,
                           required=True,
                           help="Juju deployer template")
deploy_parser.add_argument("--max-unit-retries",
                           dest="max_unit_retries",
                           type=int,
                           default=3,
                           required=False,
                           help="Maximum number of retries per unit. Default "
                                "values is set to 3 retries")
deploy_parser.add_argument("--max-machine-retries",
                           dest="max_machine_retries",
                           type=int,
                           default=3,
                           required=False,
                           help="Maximum number of retries per machine. "
                                "Default values is set to 3 retries")
deploy_parser.add_argument("--timeout",
                           dest="timeout",
                           type=int,
                           default=3600,
                           required=False,
                           help="Timeout required in order to finish the "
                                "deployment. Default value is set to "
                                "3600 seconds")


def exception_handler(green):
    LOG.error("Greenlet %r failed with an exception" % green)
    sys.exit(1)


class MaaSInstanceWatcher(object):

    def __init__(self, maas_url, maas_token, queue):
        self.queue = queue
        self.watchers = []
        self.maas_url = maas_url
        self._parse_token(maas_token)

    def _watch(self, node):
        response = self._perform_API_request(
            self.maas_url, 'api/2.0/nodes/%s/' % node,
            'GET', self.key, self.secret, self.consumer_key)
        machine_name = response.get('hostname')
        LOG.debug("Starting watcher for node: %s (%s)" % (machine_name, node))

        node_state = None
        while True:
            response = self._perform_API_request(
                self.maas_url, 'api/2.0/nodes/%s/' % node,
                'GET', self.key, self.secret, self.consumer_key)
            status = response.get('status')
            if node_state != status:
                LOG.debug("Node %s (%s) changed status to: %s" % (
                          machine_name, response.get('system_id'),
                          STATE[status]))
                node_state = status
            payload = {
                "status": STATE[status],
                "instance": response.get('resource_uri'),
                "maas-id": node,
            }
            if STATE[status] == "FAILED_DEPLOYMENT":
                self.queue.put(payload)
                LOG.debug("Stopping watcher for node %s (%s)"
                          % (machine_name, node))
                return
            gevent.sleep(5)

    def start_maas_watcher(self, node):
        e = gevent.spawn(self._watch, node)
        e.link_exception(exception_handler)
        self.watchers.append(e)

    def _perform_API_request(self, site, uri, method,
                             key, secret, consumer_key):
        resource_tok_string = "oauth_token_secret=%s&oauth_token=%s" % (
            secret, key)
        resource_token = oauth.OAuthToken.from_string(resource_tok_string)
        consumer_token = oauth.OAuthConsumer(consumer_key, "")

        oauth_request = oauth.OAuthRequest.from_consumer_and_token(
            consumer_token, token=resource_token, http_url=site,
            parameters={'oauth_nonce': uuid.uuid4().hex})
        oauth_request.sign_request(
            oauth.OAuthSignatureMethod_PLAINTEXT(), consumer_token,
            resource_token)
        headers = oauth_request.to_header()
        url = "%s%s" % (site, uri)
        http = httplib2.Http()
        response, content = http.request(url, method, body=None,
                                         headers=headers)
        self._check_response(response)
        body = json.loads(content)
        return body

    def _check_response(self, response):
        status = response.get("status")
        if int(status) > 299:
            raise Exception("Request returned status %s" % status)

    def _parse_token(self, token):
        t = token.split(":")
        if len(t) != 3:
            raise ValueError("Invalid MaaS token")
        self.consumer_key = t[0]
        self.key = t[1]
        self.secret = t[2]


class Deployer(object):

    def __init__(self, options):
        self.options = options
        self.search_string = self.options.search_string
        self.bundle = self.options.template
        with open(self.bundle, "r") as stream:
            self.services = [m for m in yaml.load(stream)['services']]
        LOG.debug(self.services)
        if self.options.action == "deploy":
            self.max_unit_retries = self.options.max_unit_retries
            self.timeout = self.options.timeout
            self.max_machine_retries = self.options.max_machine_retries
        self.units = {}
        self.machines = {}
        self.home = os.environ.get("HOME", "/tmp")
        self.workdir = os.path.join(self.home, ".deployer")

        with open(self.options.clouds_and_credentials, 'r') as f:
            content = yaml.load(f)
        maas_server = content['endpoint']
        maas_oauth = content['maas-oauth']
        maas_environment = content['environment']
        user = 'user-' + content['user']
        password = content['password']

        self.juju = environment.Environment.connect(maas_environment)
        LOG.debug("Connection started with: %s" % self.juju.endpoint)
        self.conn = environment.Environment(endpoint=self.juju.endpoint)
        self.conn.login(user=user, password=password)
        self.juju_watcher = self.conn.get_watch()

        self.channel = queue.Queue()
        self.eventlets = []
        self.maas_watcher = MaaSInstanceWatcher(maas_server,
                                                maas_oauth,
                                                self.channel)
        self.juju_watchers = []
        self.juju_channel = queue.Queue()
        self.unit_lock = lock.Semaphore(value=1)
        self.machine_lock = lock.Semaphore(value=1)
        self.deleted_machines = []
        self.tags = {}
        self._map_applications_to_tags()

    def _map_applications_to_tags(self):
        with open(self.bundle, 'r') as file:
            content = yaml.load(file)

        applications = content.get("services")
        for application in applications:
            self.tags[application] = applications[application]["constraints"]

    def _ensure_dependencies(self):
        pkgs = []
        if utils.which("juju") is None:
            utils.add_apt_ppa("ppa:juju/stable")
            utils.apt_update()
            pkgs.append("juju")
        if len(pkgs) > 0:
            utils.install_apt_packages(pkgs)

    def _ensure_workdir(self):
        if os.path.isdir(self.workdir) is False:
            os.makedirs(self.workdir, 0o700)

    def _run_deployer(self, bundle):
        if os.path.isfile(bundle) is False:
            raise Exception("No such bundle file: %s" % bundle)
        args = [
            "juju", "deploy", bundle
        ]
        subprocess.check_call(args)

    def _start_maas_watcher(self, machine):
        """
        poll MaaS API to monitor machine status. If it switches to
        Failed Deployment, then raise an exception
        """
        e = gevent.spawn(self.maas_watcher.start_maas_watcher, machine)
        e.link_exception(exception_handler)
        self.eventlets.append(e)

    def _consume_maas_events(self):
        LOG.debug("Starting MAAS Consumer")
        while True:
            try:
                event = self.channel.get_nowait()
                node = event.get("maas-id")
                self.machine_lock.acquire()
                try:
                    machine_data = self.machines.get(node)
                    juju_data = self.machines.get(machine_data["juju-id"])
                finally:
                    self.machine_lock.release()

                LOG.debug("Applications %s run on node %s"
                          % (juju_data["applications"], node))
                data = {
                    "juju-id": machine_data["juju-id"],
                    "series": machine_data["series"],
                    "tags": machine_data["tags"],
                    "applications": juju_data["applications"],
                    "units": juju_data["units"],
                    "maas-id": node,
                    "instance": event.get("instance"),
                }

                self._invoke_retry_on_machine(data)
            except queue.Empty:
                gevent.sleep(1)
                continue

    def _invoke_retry_on_machine(self, data):
        self.machine_lock.acquire()
        try:
            retries_list = []
            for application in data["applications"]:
                retries_list.append(self.machines.get(application))
                self.machines[application] = self.machines.get(application) + 1
            retries = max(retries_list)
        finally:
            self.machine_lock.release()

        if retries <= self.max_machine_retries:
            LOG.debug("Retrying machine for applications %s. %s retry"
                      % (data["applications"], retries))

            constraints = {"tags": data["tags"].split(",")}
            result = self.juju.add_machine(series=data["series"],
                                           constraints=constraints)
            new_machine_id = result.get("machine")
            if new_machine_id is None:
                raise Exception("Failed to add new machine with series %s and "
                                "constraints %s" % (data["series"],
                                                    constraints))
            LOG.debug("Machine %s was created with constraints %s"
                      % (new_machine_id, constraints))
            self._add_applications_to_machine(data["applications"],
                                              new_machine_id)
            self._remove_units(data["units"])
            self._destroy_machine(data["juju-id"])
            self._clear_cache_for_node(data["maas-id"])
        else:
            raise Exception("Node %s entered failed deployment state with "
                            "response %s" % (data["maas-id"],
                                             data["instance"]))

    def _clear_cache_for_node(self, node):
        # This is needed because after MAAS failed the first time, it will
        # allocate another machine with the different id, but if this machine
        # fails as well, then the previous id is used.
        self.machine_lock.acquire()
        try:
            self.deleted_machines.append(node)
            del self.machines[node]
        finally:
            self.machine_lock.release()

    def _remove_units(self, units):
        # removing units from the cached units
        for unit in units:
            self.unit_lock.acquire()
            try:
                del self.units[unit]
            finally:
                self.unit_lock.release()

    def _add_applications_to_machine(self, applications, machine_id):
        # adding applications to specified machine
        for application in applications:
            LOG.debug("Adding application %s to machine %s"
                      % (application, machine_id))
            try:
                self.juju.add_unit(service_name=application,
                                   machine_spec="%s" % machine_id)
            except Exception:
                LOG.debug("Failed to add unit for application %s"
                          % application)

    def _destroy_machine(self, machine_id):
        LOG.debug("Removing machine %s" % machine_id)
        try:
            self.juju.destroy_machines(["%s" % machine_id], force=True)
        except Exception:
            LOG.debug("Failed to destroy machine %s" % machine_id)

    def start_analizer(self):
        LOG.debug("Starting Analizer")
        e = gevent.spawn(self._analize)
        e.link_exception(exception_handler)
        self.juju_watchers.append(e)

    def _analize(self):
        while True:
            status = self.juju_watcher.next()
            # LOG.debug("%r" % status)
            for i in status:
                if i[0] == "unit":
                    self._analize_unit_status(i)
                if i[0] == "machine":
                    self._analize_machine_status(i)
                if i[0] == "application":
                    self._analize_application_status(i)

    def _analize_unit_status(self, unit_status):
        if unit_status[1] != "change":
            return

        if self.search_string not in unit_status[2]["application"]:
            return

        unit_data = unit_status[2]
        self.unit_lock.acquire()
        try:
            cached_data = self.units.get(unit_data["name"])
        finally:
            self.unit_lock.release()

        if cached_data is None:
            cached_data = {
                "data": unit_data,
                "retries": 0,
            }

        payload = {
            "unit": unit_data["name"],
            "action": "none",
            "retries": cached_data["retries"],
        }
        workload_state = unit_data["workload-status"]["current"]
        cached_state = cached_data["data"]["workload-status"]["current"]
        LOG.debug("%s previous state was %s and current state is %s"
                  % (unit_data["name"], cached_state, workload_state))
        if cached_state != workload_state and workload_state == "error":
            cached_data["retries"] += 1
            payload["action"] = "retry"
            payload["retries"] = cached_data["retries"]
            payload["error"] = unit_data["workload-status"]["message"]

        cached_data["data"]["workload-status"]["current"] = workload_state
        self.unit_lock.acquire()
        try:
            self.units[unit_data["name"]] = cached_data
        finally:
            self.unit_lock.release()

        try:
            self._write_unit_ips(self.units.keys())
        except exc.EnvError:
            LOG.debug("Could not write unit ips")

        self.juju_channel.put(payload)
        self._add_deployed_machine_id(unit_data)

    def _add_deployed_machine_id(self, unit_data):
        # This is needed because in status["machines"] we cannot tell which
        # MAAS machine corresponds to which juju machine
        try:
            # if machine_id is number\lxd\number then we skip it
            int(unit_data["machine-id"])
        except:
            return

        self.machine_lock.acquire()
        try:
            cached_data = self.machines.get(unit_data["machine-id"])
            retries = self.machines.get(unit_data["application"])
        finally:
            self.machine_lock.release()

        if cached_data is None:
            cached_data = {
                "applications": [unit_data["application"]],
                "units": [unit_data["name"]]
            }

        if unit_data["application"] not in cached_data["applications"]:
            cached_data["applications"].append(unit_data["application"])

        if unit_data["name"] not in cached_data["units"]:
            cached_data["units"].append(unit_data["name"])

        self.machine_lock.acquire()
        try:
            self.machines[unit_data["machine-id"]] = cached_data
            if retries is None:
                self.machines[unit_data["application"]] = 1
        finally:
            self.machine_lock.release()

    def _analize_machine_status(self, machine_status):
        if machine_status[1] != "change":
            return

        machine_data = machine_status[2]
        if machine_data["instance-id"] == "" or machine_data[
                "instance-id"] == "pending":
            return

        self.machine_lock.acquire()
        try:
            deleted_machines = self.deleted_machines
            cached_units = self.machines.get(machine_data["id"])
            cached_data = self.machines.get(machine_data["instance-id"])
        finally:
            self.machine_lock.release()

        self._resolve_deleted_machines()
        if cached_units is None:
            # if no units are saved that means that the current machine does
            # not need to be watched because it is not part of the current
            # deployment
            return

        for application in cached_units["applications"]:
            if self.tags.get(application) is not None:
                tags = self.tags.get(application).split('=')[1]
                break

        if cached_data is None:
            cached_data = {
                "analized": False,
                "juju-id": machine_data["id"],
                "series": machine_data["series"],
                "tags": tags,
            }

        if not cached_data["analized"] and machine_data[
                "instance-id"] not in deleted_machines:
            self._start_maas_watcher(machine_data["instance-id"])
            cached_data["analized"] = True

            self.machine_lock.acquire()
            try:
                self.machines[machine_data["instance-id"]] = cached_data
            finally:
                self.machine_lock.release()

    def _resolve_deleted_machines(self):
        status = self._juju_status()
        machines = self._get_machine_ids(status)
        self.machine_lock.acquire()
        try:
            deleted_machines = self.deleted_machines
        finally:
            self.machine_lock.release()

        current_machines = []
        for machine in machines:
            current_machines.append(status["machines"][machine]["instance-id"])

        for machine in deleted_machines:
            if machine not in current_machines:
                deleted_machines.remove(machine)

        self.machine_lock.acquire()
        try:
            self.deleted_machines = deleted_machines
        finally:
            self.machine_lock.release()

    def _analize_application_status(self, application_status):
        pass

    def _consume_juju_data(self):
        LOG.debug("Starting Juju Consumer")
        while True:
            try:
                event = self.juju_channel.get_nowait()
                unit = event.get("unit")
                if unit and event.get("action") == "retry":
                    unit_retries = event.get("retries")
                    if unit_retries <= self.max_unit_retries:
                        LOG.debug("Retrying unit %s. %s retry"
                                  % (unit, unit_retries))
                        try:
                            self.juju.resolved(unit)
                        except Exception:
                            pass
                    else:
                        raise Exception("Unit %s is in error state: "
                                        "%s" % (unit, event.get("error")))
            except queue.Empty:
                gevent.sleep(5)
                continue

    @utils.exec_retry(retry=5)
    def _juju_status(self, *args, **kw):
        return self.juju.status(*args, **kw)

    def _write_unit_ips(self, units):
        unit_ips = {}
        for i in units:
            name = i.split("/")[0][:-len("-%s" %
                                         self.search_string)].replace('-', "_")
            ip = self.juju.get_private_address(i)["private-address"]
            if name in unit_ips:
                unit_ips[name] += ",%s" % ip
            else:
                unit_ips[name] = ip
        nodes = os.path.join(os.getcwd(), "nodes")
        with open(nodes, "w") as fd:
            for i in unit_ips.keys():
                fd.write("%s=%s\n" % (i.upper(), unit_ips[i]))

    def _get_machine_ids(self, status):
        m = status.get("machines")
        if m is None:
            return []
        return m.keys()

    def _get_application_names(self, status):
        m = status.get("applications")
        if m is None:
            return []
        return m.keys()

    def _wait_for_teardown(self, machines=[]):
        while True:
            has_machines = False
            status = self._juju_status()
            state_machines = status.get("machines", {})
            for i in machines:
                if state_machines.get(i):
                    has_machines = True
            if has_machines is False:
                break
            gevent.sleep(3)

    def _validate_deployment(self):
        self.unit_lock.acquire()
        try:
            units = self.units.values()
        finally:
            self.unit_lock.release()

        if not units:
            return False

        for unit in units:
            if unit["data"]["workload-status"]["current"] != "active":
                return False
        return True

    def _deployment_watcher(self, started_time, timeout):
        LOG.debug("Starting Deployment Watcher")
        end_time = started_time + timeout
        while time.time() < end_time:
            if self._validate_deployment():
                LOG.debug("Deployment finished successfully")
                return
            time.sleep(60)

        raise Exception("Deployment failed to finish in %s seconds" % timeout)

    def deploy(self):
        self._ensure_workdir()

        self._ensure_dependencies()
        self._run_deployer(self.bundle)

        start_time = time.time()

        e = gevent.spawn(self._consume_maas_events)
        e.link_exception(exception_handler)
        self.eventlets.append(e)

        e = gevent.spawn(self._consume_juju_data)
        e.link_exception(exception_handler)
        self.eventlets.append(e)

        e = gevent.spawn(self.start_analizer)
        e.link_exception(exception_handler)
        self.eventlets.append(e)

        self._deployment_watcher(start_time, self.timeout)
        gevent.killall(self.eventlets)
        gevent.killall(self.maas_watcher.watchers)
        gevent.killall(self.juju_watchers)

    def teardown(self):
        status = self._juju_status(filters=("*%s*" % self.search_string))
        machines = self._get_machine_ids(status)
        application_names = self._get_application_names(status)
        for application in application_names:
            self.juju.destroy_service(application)
        self.juju.destroy_machines(machines, force=True)
        self._wait_for_teardown(machines)


if __name__ == '__main__':
    opt = parser.parse_args()
    deployer = Deployer(opt)
    if opt.action == "deploy":
        deployer.deploy()
    if opt.action == "teardown":
        deployer.teardown()
