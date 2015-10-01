#!/usr/bin/env python

import os
import sys

PYTHON_PATH = os.path.dirname(os.path.abspath(os.path.normpath(sys.argv[0])))
sys.path.append(PYTHON_PATH)

from gevent import monkey
monkey.patch_all()

import gevent
import sys
import argparse
import yaml
import tempfile
import os
import logging

LOG = logging.getLogger()
LOG.setLevel(logging.DEBUG)
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
formatter = logging.Formatter(
    '%(asctime)s - %(name)s - %(levelname)s - %(message)s')
ch.setFormatter(formatter)
LOG.addHandler(ch)


import helpers.utils as utils
import helpers.maasclient as maasclient
import jujuclient

from gevent import subprocess
from gevent.queue import Queue, Empty

from jujuclient import Environment


parser = argparse.ArgumentParser(prog="Deployer")
subparsers = parser.add_subparsers(dest="action")

deploy_parser = subparsers.add_parser('deploy')
teardown_parser = subparsers.add_parser('teardown')

teardown_parser.add_argument("--search-string", dest="search_string",
    type=str, required=True, help="Deploy uuid")
teardown_parser.add_argument("--template", dest="template",
    type=str, required=False, help="Juju deployer template")

deploy_parser.add_argument("--search-string", dest="search_string",
    type=str, required=False, help="Deploy uuid")
deploy_parser.add_argument("--template", dest="template",
    type=str, required=True, help="Juju deployer template") 


def exception_handler(green):
    LOG.error("Greenlet %r failed with an exception" % green)
    sys.exit(1)


class MaaSInstanceWatcher(maasclient.Nodes):

    def __init__(self, maas_url, maas_token, queue):
        super(MaaSInstanceWatcher, self).__init__(maas_url, maas_token)
        self.queue = queue
        self.watchers = []

    def _watch(self, node):
        node_state = None
        if isinstance(node, maasclient.Node) is False:
            raise ValueError("Function got invalid type: %r" % type(node))
        while True:
            status = node.substatus()
            if node_state != status:
                LOG.debug("Node %s changed status to: %s" % (node.data["hostname"], status))
                node_state = status
            payload = {"status": status, "instance": node.data["resource_uri"]}
            self.queue.put(payload)
            if status == maasclient.FAILED_DEPLOYMENT:
                return
            gevent.sleep(5)

    def start_watcher(self, node):
        LOG.debug("Starting watcher for node: %s" % node)
        n = self.get(node)
        e = gevent.spawn(self._watch, n)
        e.link_exception(exception_handler)
        self.watchers.append(e)


class Deployer(object):

    def __init__(self, options):
        self.options = options
        self.juju = Environment.connect('maas')
        self.search_string = options.search_string
        self.bundle = self.options.template
        #self.bundle_generator = utils.BundleGenerator(self.options)
        self.home = os.environ.get("HOME", "/tmp")
        self.workdir = os.path.join(self.home, ".deployer")
        self.channel = Queue()
        self.eventlets = []
        env_config = self.juju.get_env_config()
        self.maas_watcher = MaaSInstanceWatcher(
            env_config["Config"]["maas-server"],
            env_config["Config"]["maas-oauth"],
            self.channel)

    def _ensure_dependencies(self):
        pkgs = []
        if utils.which("juju-deployer") is None:
            utils.add_apt_ppa("ppa:juju/stable")
            utils.apt_update()
            pkgs.append("juju-deployer")
        if len(pkgs) > 0:
            utils.install_apt_packages(pkgs)

    def _ensure_workdir(self):
        if os.path.isdir(self.workdir) is False:
            os.makedirs(self.workdir, 0o700)

    def _run_deployer(self, bundle):
        if os.path.isfile(bundle) is False:
            raise Exception("No such bundle file: %s" % bundle)
        args = [
            "juju-deployer", "-r", "3", "--local-mods", "-S", "-c", bundle
        ]
        subprocess.check_call(args)

    #def _render_yaml(self, project):
    #    proj = project.split("/")[-1]
    #    func = getattr(self.bundle_generator, "%s_bundle" % proj)
    #    if not func:
    #        raise ValueError(
    #            "Project %s is not supported by bundler" % project)
    #    bundle = func()
    #    bundle_file = os.path.join(self.workdir, self.search_string)
    #    with open(bundle_file, "w") as fd:
    #        yaml.dump(bundle, stream=fd, default_flow_style=False,
    #            allow_unicode=True, encoding=None)
    #    return bundle_file

    def _start_maas_watcher(self, machine):
        """
        poll MaaS API to monitor machine status. If it switches to
        Failed Deployment, then raise an exception
        """
        e = gevent.spawn(self.maas_watcher.start_watcher, machine)
        e.link_exception(exception_handler)
        self.eventlets.append(e)

    def _consume_events(self):
        LOG.debug("Starting Consumer")
        while True:
            try:
                event = self.channel.get_nowait()
                if event.get("status") == maasclient.FAILED_DEPLOYMENT:
                    raise Exception("Node %s entered failed deployment state" %
                        event.get("instance"))
            except Empty:
                gevent.sleep(1)
                continue

    @utils.exec_retry(retry=5)
    def _juju_status(self, *args, **kw):
        return self.juju.status(*args, **kw)

    def _get_machines(self, status):
        machines = []
        m = status.get("Machines")
        if m is None:
            return machines
        for i in m.keys():
            instanceId = m[i].get("InstanceId")
            if instanceId == "pending":
                continue
            machines.append(m[i].get("InstanceId"))
        return machines

    def _get_machine_ids(self, status):
        m = status.get("Machines")
        if m is None:
            return []
        return m.keys()

    def _get_service_names(self, status):
        m = status.get("Services")
        if m is None:
            return []
        return m.keys()

    def _analize_units(self, units, debug=False):
        all_active = True
        for i in units.keys():
            unit = units[i]
            if debug:
                LOG.debug(
                    "Unit %s has status: %r" % (i, unit["Workload"]["Status"]))
            if unit["UnitAgent"]["Status"] == "error":
                raise Exception("Unit %s is in error state: %s" %
                    (i, unit["UnitAgent"]["Err"]))
            if unit["Workload"]["Status"] == "error":
                raise Exception("Unit %s workload is in error state: %s" %
                    (i, unit["Workload"]["Info"]))
            if unit["Err"] is not None:
                raise Exception("Unit %s is in error state: %s" %
                    (i, unit["Err"]))
            if unit["Workload"]["Status"] != "active":
                all_active = False
        return all_active

    def _analize_machines(self, machines):
        for i in machines.keys():
            machine = machines.get(i)
            if machine["Err"]:
                raise Exception("MaaS returned error when allocating %s: %s" %
                    (i, machine["Err"]))
            agent = machine.get("Agent")
            if agent:
                status = agent.get("Status")
                info = agent.get("Info")
                err = agent.get("Err")
                if status == "error" or err:
                    raise Exception(
                        "Machine agent is in error state: %r" % info)

    def _write_unit_ips(self, units):
        unit_ips = {}
        for i in units:
            name = i.split("/")[0][:-len("-%s" % self.search_string)].replace('-', "_")
            ip = self.juju.get_private_address(i)["PrivateAddress"]
            if name in unit_ips:
                unit_ips[name] += ",%s" % ip
            else:
                unit_ips[name] = ip
        nodes = os.path.join(os.getcwd(), "nodes")
        with open(nodes, "w") as fd:
            for i in unit_ips.keys():
                fd.write("%s=%s\n" % (i.upper(), unit_ips[i]))

    def _analize(self, status, debug=False):
        """
        Return True if charms have reached active workload state, False if not
        raise error any charm reaches error state.
        """
        services = status.get("Services")
        if services is None:
            return False
        all_units = {}
        for i in services.keys():
            svc = services.get(i)
            units = svc.get("Units")
            all_units.update(units)
        # TODO: only do this if there are changes, not on every iteration.
        try:
            self._write_unit_ips(all_units)
        except jujuclient.EnvError:
            LOG.debug("Cound not write unit ips")
        all_active = self._analize_units(all_units, debug)
        if all_active:
            return True
        # Juju retains the error returned by the MaaS API in case MaaS
        # errored out while the acquire API call was made. In this scenario,
        # MaaS will not return a usable node.
        machines = status.get("Machines")
        if machines is None:
            return False
        self._analize_machines(machines)

    def _poll_services(self):
        """
        This poller works under the assumption that the charms being deployed
        have implemented status-set calls that tell us when workload status
        changed to active. Poll services, units and instances until all units
        have workload status set to active, or untill any of them error out.
        """
        LOG.debug("Starting poller")
        watched_machines = []
        iteration = 0
        while True:
            status = self._juju_status(filters=("*%s*" % self.search_string))
            #LOG.debug("%r" % status)
            debug = False
            if iteration % 1 == 0:
                debug = True
            all_active = self._analize(status, debug=debug)
            if all_active:
                break
            machines = self._get_machines(status)
            diff = set(machines).difference(set(watched_machines))
            new_machines = list(diff)
            for i in new_machines:
                self._start_maas_watcher(i)
                watched_machines.append(i)
            iteration += 1
            gevent.sleep(3)

    def _wait_for_teardown(self, machines=[]):
        while True:
            has_machines = False
            status = self._juju_status()
            state_machines = status.get("Machines", {})
            for i in machines:
                if state_machines.get(i):
                    has_machines = True
            if has_machines is False:
                break
            gevent.sleep(3)

    def deploy(self):
        self._ensure_workdir()
        self._ensure_dependencies()
        #bundle = self._render_yaml(self.options.zuul_project)
        self._run_deployer(self.bundle)

        e = gevent.spawn(self._consume_events)
        e.link_exception(exception_handler)
        self.eventlets.append(e)

        self._poll_services()
        gevent.killall(self.eventlets)
        gevent.killall(self.maas_watcher.watchers)

    def teardown(self):
        status = self._juju_status(filters=("*%s*" % self.search_string))
        machines = self._get_machine_ids(status)
        service_names = self._get_service_names(status)
        for i in service_names:
            self.juju.destroy_service(i)
        self.juju.destroy_machines(machines, force=True)
        self._wait_for_teardown(machines)


if __name__ == '__main__':
    opt = parser.parse_args()
    deployer = Deployer(opt)
    if opt.action == "deploy":
        deployer.deploy()
    if opt.action == "teardown":
        deployer.teardown()

