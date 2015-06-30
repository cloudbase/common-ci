#!/bin/bash
set -e

BASEDIR=$(dirname $0)

function push_dir() {
    pushd . > /dev/null
}

function pop_dir() {
    popd > /dev/null
}

function exec_with_retry () {
    local max_retries=$1
    local interval=${2}
    local cmd=${@:3}

    local counter=0
    while [ $counter -lt $max_retries ]; do
        local exit_code=0
        eval $cmd || exit_code=$?
        if [ $exit_code -eq 0 ]; then
            return 0
        fi
        let counter=counter+1

        if [ -n "$interval" ]; then
            sleep $interval
        fi
    done
    return $exit_code
}


function copy_devstack_config_files() {
    local dest_dir=$1
    
    mkdir -p $dest_dir

    cp -r /etc/ceilometer $dest_dir
    cp -r /etc/cinder $dest_dir
    cp -r /etc/glance $dest_dir
    cp -r /etc/heat $dest_dir
    cp -r /etc/keystone $dest_dir
    cp -r /etc/nova $dest_dir
    cp -r /etc/neutron $dest_dir
    cp -r /etc/swift $dest_dir

    mkdir $dest_dir/tempest
    check_copy_dir $tempest_dir/etc $dest_dir/tempest
}

function copy_devstack_log_files() {
    local dest_dir=$1
    
    mkdir -p $dest_dir

    cp -r /opt/stack/logs $dest_dir
    cp -r /etc/cinder $dest_dir
    cp -r /etc/glance $dest_dir
    cp -r /etc/heat $dest_dir
    cp -r /etc/keystone $dest_dir
    cp -r /etc/nova $dest_dir
    cp -r /etc/neutron $dest_dir
    cp -r /etc/swift $dest_dir

    mkdir $dest_dir/tempest
    check_copy_dir $tempest_dir/etc $dest_dir/tempest
}

function copy_devstack_config_files() {
    local dest_dir=$1
    
    mkdir -p $dest_dir

    cp -r /etc/ceilometer $dest_dir
    cp -r /etc/cinder $dest_dir
    cp -r /etc/glance $dest_dir
    cp -r /etc/heat $dest_dir
    cp -r /etc/keystone $dest_dir
    cp -r /etc/nova $dest_dir
    cp -r /etc/neutron $dest_dir
    cp -r /etc/swift $dest_dir

    mkdir $dest_dir/tempest
    check_copy_dir $tempest_dir/etc $dest_dir/tempest
}

function mount_windows_share() {
    local host=$1
    local user=$2
    local pass=$3
    local domain=$4

    mkdir -p /mnt/$host
    sudo mount -t cifs //$host/C$ /mnt/ -o username=$user,password=$pass,domain=$domain
}

function umount_windows_share(){
    local host=$1

    sudo umount /mnt/$host
}

