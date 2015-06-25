#!/usr/bin/env python

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

from gevent import subprocess
from gevent.queue import Queue, Empty

from jujuclient import Environment


parser = argparse.ArgumentParser(prog="Deployer")
subparsers = parser.add_subparsers(dest="action")

deploy_parser = subparsers.add_parser('deploy')
teardown_parser = subparsers.add_parser('teardown')

teardown_parser.add_argument("--zuul-uuid", dest="zuul_uuid",                     
    type=str, required=True, help="Zuul uuid")

deploy_parser.add_argument("--nr-ad-units", dest="nr_ad_units",
    type=int, default=0, help="Number of AD units to be deployed")
deploy_parser.add_argument("--ad-service", dest="ad_service",                 
    type=str, help="Active directory service name")
deploy_parser.add_argument("--nr-devstack-units", dest="nr_devstack_units",
    type=int, default=1, help="Number of DevStack units to be deployed")
deploy_parser.add_argument("--nr-hyperv-units", dest="nr_hyper_v_units",
    type=int, default=1, help="Number of Hyper-V units to be deployed")
deploy_parser.add_argument("--zuul-branch", dest="zuul_branch",
    type=str, default="master", help="Zuul branch")
deploy_parser.add_argument("--zuul-change", dest="zuul_change",
    type=str, required=True, help="Zuul change")
deploy_parser.add_argument("--zuul-project", dest="zuul_project",
    type=str, required=True, help="Zuul project")
deploy_parser.add_argument("--zuul-ref", dest="zuul_ref",
    type=str, required=True, help="Zuul ref")
deploy_parser.add_argument("--zuul-uuid", dest="zuul_uuid",
    type=str, required=True, help="Zuul uuid")
deploy_parser.add_argument("--zuul-url", dest="zuul_url",
    type=str, required=True, help="Zuul url")
deploy_parser.add_argument("--data-ports", dest="data_ports",
    type=str, required=True, help="Data ports")
deploy_parser.add_argument("--external-ports", dest="external_ports",
    type=str, required=True, help="External ports")
deploy_parser.add_argument("--ad-domain-name", dest="ad_domain_name",
    type=str, default="cloudbase.local", help="AD domain name")
deploy_parser.add_argument("--ad-admin-password", dest="ad_admin_password",
    type=str, help="AD administrator password")
deploy_parser.add_argument("--hyper-v-extra-python-packages",
    dest="hyper_v_extra_python_packages",
    type=str, help="Hyper-V extra python packages")
deploy_parser.add_argument("--vlan-range", dest="vlan_range",
    type=str, required=True, help="VLAN range")
deploy_parser.add_argument("--devstack-extra-packages",
    dest="devstack_extra_packages",
    type=str, help="DevStack extra packages")
deploy_parser.add_argument("--devstack-extra-python-packages",
    dest="devstack_extra_python_packages",
    type=str, help="DevStack extra python packages")
deploy_parser.add_argument("--devstack-enabled-services",
    dest="devstack_enabled_services", type=str,
    help="DevStack enabled services")
deploy_parser.add_argument("--devstack-disabled-services",
    dest="devstack_disabled_services", type=str,
    help="DevStack disabled services")
deploy_parser.add_argument("--devstack-enabled-plugins",
    dest="devstack_enabled_plugins", type=str, help="DevStack enabled plugins")


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
        self.watchers.append(gevent.spawn(self._watch, n))


class Deployer(object):

    def __init__(self, options):
        self.options = options
        self.juju = Environment.connect('maas')
        self.uuid = options.zuul_uuid
        self.bundle_generator = utils.BundleGenerator(self.options)
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
            "juju-deployer", "-S", "-c", bundle
        ]
        subprocess.check_call(args)

    def _render_yaml(self, project):
        proj = project.split("/")[-1]
        func = getattr(self.bundle_generator, "%s_bundle" % proj)
        if not func:
            raise ValueError(
                "Project %s is not supported by bundler" % project)
        bundle = func()
        bundle_file = os.path.join(self.workdir, self.uuid)
        with open(bundle_file, "w") as fd:
            yaml.dump(bundle, stream=fd, default_flow_style=False,
                allow_unicode=True, encoding=None)
        return bundle_file

    def _start_maas_watcher(self, machine):
        """
        poll MaaS API to monitor machine status. If it switches to
        Failed Deployment, then raise an exception
        """
        e = gevent.spawn(self.maas_watcher.start_watcher, machine)
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
        all_active = self._analize_units(all_units, debug)
        if all_active:
            return True
        # Juju retains the error returned by the MaaS API in case MaaS
        # errored out while the acquire API call was made. In this scenario,
        # MaaS will not return a usable node.
        machines = status.get("Machines")
        if machines is None:
            return False
        for i in machines.keys():
            machine = machines.get(i)
            if machine["Err"]:
                raise Exception("MaaS returned error when allocating %s: %s" %
                    (i, machine["Err"]))

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
            status = self.juju.status(filters=("*%s*" % self.uuid))
            debug = False
            if iteration % 30 == 0:
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

    def _wait_for_teardown(self):
        while True:
            status = self.juju.status(filters=("*%s*" % self.uuid))
            if len(status.get("Services")) == 0:
                break
            gevent.sleep(3)
        
    def deploy(self):
        self._ensure_workdir()
        self._ensure_dependencies()
        bundle = self._render_yaml(self.options.zuul_project)
        self._run_deployer(bundle)
        self.eventlets.append(gevent.spawn(self._consume_events))
        self._poll_services()
        gevent.killall(self.eventlets)
        gevent.killall(self.maas_watcher.watchers)

    def teardown(self):
        status = self.juju.status(filters=("*%s*" % self.uuid))
        machines = self._get_machine_ids(status)
        service_names = self._get_service_names(status)
        for i in service_names:
            self.juju.destroy_service(i)
        self.juju.destroy_machines(machines, force=True)
        self._wait_for_teardown()


if __name__ == '__main__':
    opt = parser.parse_args()
    deployer = Deployer(opt)
    if opt.action == "deploy":
        if opt.nr_ad_units > 0 and opt.ad_admin_password is None:
            parser.error(
                "Parameter --ad-admin-password is mandatory if deploying AD")
        deployer.deploy()
    if opt.action == "teardown":
        deployer.teardown()

