#!/usr/bin/env python

import argparse
import logging
import sys
import re
import time

from jujuclient.juju2 import environment

parser = argparse.ArgumentParser(prog="node-pool")
parser.add_argument("--tags",
                    dest="tags",
                    type=str,
                    required=True,
                    help="Searching tags. They have to be passed as a string "
                         "with spaces. Example: --tags 'abc def' ")
parser.add_argument("--series",
                    dest="series",
                    type=str,
                    required=True,
                    help="Specified series to search for")
parser.add_argument("--vm-no-increment",
                    dest="vm_no_increment",
                    type=int,
                    required=True,
                    help="Specified number of machines to be spawned")
parser.add_argument("--vm-no-min-threshold",
                    dest="vm_no_min_threshold",
                    type=int,
                    required=True,
                    help="Minimum threshold of machines")

LOG = logging.getLogger()
LOG.setLevel(logging.DEBUG)
formatter = logging.Formatter('%(asctime)s - %(name)s - '
                              '%(levelname)s - %(message)s')
ch = logging.StreamHandler(sys.stdout)
ch.setLevel(logging.DEBUG)
ch.setFormatter(formatter)

LOG.addHandler(ch)


class NodePool(object):

    def __init__(self, options):
        self.vm_no_increment = options.vm_no_increment
        self.vm_no_min_threshold = options.vm_no_min_threshold
        self.juju = environment.Environment.connect('maas:default')

    def _get_used_machines(self, status):
        used_machines = []
        applications = status.get("applications")
        for application in applications:
            units = applications[application].get("units")
            if units is None:
                continue
            for unit in units:
                machine = applications[application]["units"][unit]["machine"]
                if machine not in used_machines:
                    used_machines.append(machine)
        return used_machines

    def _check_pending_machines(self, status):
        pending = False
        machines = status.get("machines")
        for machine in machines:
            if machines[machine]["instance-id"] == "pending":
                pending = True
                break
        return pending

    def _count_vms_with_tags(self, status, tags, series):
        count = 0
        machines = status.get("machines")
        used_machines = self._get_used_machines(status)
        for machine in machines:
            if machine in used_machines:
                continue

            m = re.match(".*tags=(\S+).*", machines[machine]["hardware"])
            machine_tags = m.group(1)

            internal_count = 0
            for tag in tags:
                if tag in machine_tags:
                    internal_count = internal_count + 1

            if (series == machines[machine]["series"] and
                    internal_count == len(tags)):
                count = count + 1
        return count

    def spawn_vms_with_tags_and_series(self, tags, series):
        """
        Spawn a certain number of virtual machines with the given
        tags and series.
        """
        self.status = self.juju.status()
        LOG.debug("Waiting for pending machines")
        started_time = time.time()
        end_time = started_time + 600
        while True:
            if self._check_pending_machines(self.status):
                time.sleep(60)
                self.status = self.juju.status()
            else:
                break

            if time.time() > end_time:
                raise Exception("Machines are still in pending. "
                                "Cannot continue")

        tags = tags.split(" ")
        LOG.debug("Counting machines with tags %s" % tags)
        vm_no_machines = self._count_vms_with_tags(self.status, tags, series)
        LOG.debug("Found %s vms with tags %s and series %s"
                  % (vm_no_machines, tags, series))
        if vm_no_machines < self.vm_no_min_threshold:
            vm_to_add = self.vm_no_min_threshold - vm_no_machines
            LOG.debug("Adding %s machines with tags '%s' and series '%s'"
                      % (vm_to_add, tags, series))

            for i in range(0, vm_to_add):
                self.juju.add_machine(series=series,
                                      constraints={"tags": tags})

if __name__ == '__main__':
    opt = parser.parse_args()
    node_pool = NodePool(opt)
    node_pool.spawn_vms_with_tags_and_series(opt.tags, opt.series)
