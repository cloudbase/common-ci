#!/bin/bash
set -e

BASEDIR=$(dirname $0)

function run_wsman_cmd() {
    local host=$1
    local cmd=$2
    $BASEDIR/wsmancmd.py -u $win_user -p $win_password -U https://$1:5986/wsman $cmd
}

function get_win_files() {
    local host=$1
    local remote_dir=$2
    local local_dir=$3
    smbclient "//$host/C\$" -c "lcd $local_dir; cd $remote_dir; prompt; mget *" -U "$win_user%$win_password"
}

function run_wsman_ps() {
    local host=$1
    local cmd=$2
    run_wsman_cmd $host "powershell -NonInteractive -ExecutionPolicy RemoteSigned -Command $cmd"
}

function get_win_hotfixes() {
    local host=$1
    run_wsman_cmd $host "wmic qfe list"
}

function get_win_system_info() {
    local host=$1
    run_wsman_cmd $host "systeminfo"
}

function get_win_time() {
    local host=$1
    # Seconds since EPOCH
    host_time=`run_wsman_ps $host "[Math]::Truncate([double]::Parse((Get-Date (get-date).ToUniversalTime() -UFormat %s)))" 2>&1`
    # Skip the newline
    echo ${host_time::-1}
}

function push_dir() {
    pushd . > /dev/null
}

function pop_dir() {
    popd > /dev/null
}

function clone_pull_repo() {
    local repo_dir=$1
    local repo_url=$2
    local repo_branch=${3:-"master"}

    push_dir
    if [ -d "$repo_dir/.git" ]; then
        cd $repo_dir
        git checkout $repo_branch
        git pull
    else
        cd `dirname $repo_dir`
        git clone $repo_url
        cd $repo_dir
        if [ "$repo_branch" != "master" ]; then
            git checkout -b $repo_branch origin/$repo_branch
        fi
    fi
    pop_dir
}

function check_get_image() {
    local image_url=$1
    local images_dir=$2
    local file_name_tmp="$images_dir/${image_url##*/}"
    local file_name="$file_name_tmp"

    if [ "${file_name_tmp##*.}" == "gz" ]; then
        file_name="${file_name_tmp%.*}"
    fi

    if [ ! -f "$file_name" ]; then
        wget -q $image_url -O $file_name_tmp
        if [ "${file_name_tmp##*.}" == "gz" ]; then
            gunzip "$file_name_tmp"
        fi
    fi

    echo "${file_name##*/}"
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

function get_devstack_ip_addr() {
    python -c "import socket;
s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM);
s.connect(('8.8.8.8', 80));
(addr, port) = s.getsockname();
s.close();
print addr"
}

function check_copy_dir() {
    local src_dir=$1
    local dest_dir=$2

    if [ -d "$src_dir" ]; then
        cp -r "$src_dir" "$dest_dir"
    fi
}

function get_win_hotfixes_log() {
    local win_host=$1
    local log_file=$2
    echo "Getting hotfixes details for host: $win_host"
    get_win_hotfixes $win_host > $log_file
}

function get_win_system_info_log() {
    local win_host=$1
    local log_file=$2
    echo "Getting system info for host: $win_host"
    get_win_system_info $win_host > $log_file
}

function get_win_host_log_files() {
    local host_name=$1
    local local_dir=$2
    get_win_files $host_name "$host_logs_dir" $local_dir
}

function get_win_host_config_files() {
    local host_name=$1
    local local_dir=$2
    mkdir -p $local_dir

    get_win_files $host_name $host_config_dir $local_dir
}

function copy_devstack_config_files() {
    local dest_dir=$1
    
    mkdir -p $dest_dir

    check_copy_dir /etc/ceilometer $dest_dir
    check_copy_dir /etc/cinder $dest_dir
    check_copy_dir /etc/glance $dest_dir
    check_copy_dir /etc/heat $dest_dir
    check_copy_dir /etc/keystone $dest_dir
    check_copy_dir /etc/nova $dest_dir
    check_copy_dir /etc/neutron $dest_dir
    check_copy_dir /etc/swift $dest_dir

    mkdir $dest_dir/tempest
    check_copy_dir $tempest_dir/etc $dest_dir/tempest
}

function check_host_time() {
    local host=$1
    host_time=`get_win_time $host`
    local_time=`date +%s`

    local delta=$((local_time - host_time))
    if [ ${delta#-} -gt 120 ];
    then
        echo "Host $host time offset compared to this host is too high: $delta"
        return 1
    fi
}
