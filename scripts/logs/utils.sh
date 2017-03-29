#!/bin/bash

BASEDIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" && pwd )"
LOG_DST="/home/ubuntu/aggregate"

TAR="tar"
GZIP="gzip -f"

function emit_error() {
    echo "ERROR: $1"
    exit 1
}

function emit_warning() {
    echo "WARNING: $1"
    return 0
}

function emit_info() {
    echo "INFO: $1"
    return 0
}

function run_wsman_cmd() {
    local host=$1
    local cmd=$2
    $BASEDIR/wsmancmd.py -s -H $host -a certificate -c /home/ubuntu/.ssl/winrm_client_cert.pem -k /home/ubuntu/.ssl/winrm_client_cert.key "$cmd"
}

function get_win_files() {
    local host=$1
    local remote_dir=$2
    local local_dir=$3
    if [ ! -d "$local_dir" ];then
        mkdir "$local_dir"
    fi
    smbclient "//$host/C\$" -c "prompt OFF; cd $remote_dir" -U "$win_user%$win_password"
    if [ $? -ne 0 ];then
        echo "Folder $remote_dir does not exists"
        return 0
    fi
    smbclient "//$host/C\$" -c "prompt OFF; recurse ON; lcd $local_dir; cd $remote_dir; mget *" -U "$win_user%$win_password"
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

function get_win_hotfixes_log() {
    local win_host=$1
    local log_file=$2
    emit_info "Getting hotfixes details for host: $win_host"
    get_win_hotfixes $win_host > $log_file
}

function get_win_system_info_log() {
    local win_host=$1
    local log_file=$2
    emit_info "Getting system info for host: $win_host"
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

function check_host_time() {
    local host1=$1
    local host2=$2
    host1_time=`get_win_time $host1`
    host2_time=`get_win_time $host2`
    local_time=`date +%s`

    local delta1=$((local_time - host1_time))
    local delta2=$((local_time - host2_time))
    if [ ${delta1#-} -gt 120 ];
    then
        emit_info "Host $host1 time offset compared to this host is too high: $delta"
        return 1
    fi
    if [ ${delta2#-} -gt 120 ];
    then
        emit_info "Host $host2 time offset compared to this host is too high: $delta"
        return 1
    fi
    return 0
}

function archive_devstack_logs() {
    local LOG_DST_DEVSTACK=${1:-$LOG_DST/devstack-logs}
    local DEVSTACK_LOGS="/opt/stack/logs/screen"

    if [ ! -d "$LOG_DST_DEVSTACK" ]
    then
        mkdir -p "$LOG_DST_DEVSTACK" || emit_error "L30: Failed to create $LOG_DST_DEVSTACK"
    fi

    for i in `ls -A $DEVSTACK_LOGS`
    do
        if [ -h "$DEVSTACK_LOGS/$i" ]
        then
                REAL=$(readlink "$DEVSTACK_LOGS/$i")
                $GZIP -c "$REAL" > "$LOG_DST_DEVSTACK/$i.gz" || emit_warning "L38: Failed to archive devstack logs: $i"
        fi
    done
    $GZIP -c /var/log/mysql/error.log > "$LOG_DST_DEVSTACK/mysql_error.log.gz"
    $GZIP -c /var/log/cloud-init.log > "$LOG_DST_DEVSTACK/cloud-init.log.gz"
    $GZIP -c /var/log/cloud-init-output.log > "$LOG_DST_DEVSTACK/cloud-init-output.log.gz"
    $GZIP -c /var/log/dmesg > "$LOG_DST_DEVSTACK/dmesg.log.gz"
    $GZIP -c /var/log/kern.log > "$LOG_DST_DEVSTACK/kern.log.gz"
    $GZIP -c /var/log/syslog > "$LOG_DST_DEVSTACK/syslog.log.gz"

    mkdir -p "$LOG_DST_DEVSTACK/rabbitmq"
    cp /var/log/rabbitmq/* "$LOG_DST_DEVSTACK/rabbitmq"
    sudo rabbitmqctl status > "$LOG_DST_DEVSTACK/rabbitmq/status.txt" 2>&1
    $GZIP $LOG_DST_DEVSTACK/rabbitmq/*
    mkdir -p "$LOG_DST_DEVSTACK/openvswitch"
    cp /var/log/openvswitch/* "$LOG_DST_DEVSTACK/openvswitch"
    $GZIP $LOG_DST_DEVSTACK/openvswitch/*
    for j in `ls -A /var/log/juju`; do
        $GZIP -c /var/log/juju/$j > "$LOG_DST_DEVSTACK/$j.gz"
    done
}

function archive_devstack_configs() {
    local CONFIG_DST_DEVSTACK=${1:-$LOG_DST/devstack-config}

    if [ ! -d "$CONFIG_DST_DEVSTACK" ]
    then
        mkdir -p "$CONFIG_DST_DEVSTACK" || emit_warning "L38: Failed to archive devstack configs"
    fi

    for i in cinder glance keystone neutron nova openvswitch
    do
        cp -r -L "/etc/$i" "$CONFIG_DST_DEVSTACK/$i" || continue
    done
    for file in `find "$CONFIG_DST_DEVSTACK/$i" -type f`
    do
        $GZIP $file
    done

    $GZIP -c /home/ubuntu/devstack/local.conf > "$CONFIG_DST_DEVSTACK/local.conf.gz"
    $GZIP -c /opt/stack/tempest/etc/tempest.conf > "$CONFIG_DST_DEVSTACK/tempest.conf.gz"
    df -h > "$CONFIG_DST_DEVSTACK/df.txt" 2>&1 && $GZIP "$CONFIG_DST_DEVSTACK/df.txt"
    iptables-save > "$CONFIG_DST_DEVSTACK/iptables.txt" 2>&1 && $GZIP "$CONFIG_DST_DEVSTACK/iptables.txt"
    dpkg-query -l > "$CONFIG_DST_DEVSTACK/dpkg-l.txt" 2>&1 && $GZIP "$CONFIG_DST_DEVSTACK/dpkg-l.txt"
    pip freeze > "$CONFIG_DST_DEVSTACK/pip-freeze.txt" 2>&1 && $GZIP "$CONFIG_DST_DEVSTACK/pip-freeze.txt"
    ps axwu > "$CONFIG_DST_DEVSTACK/pidstat.txt" 2>&1 && $GZIP "$CONFIG_DST_DEVSTACK/pidstat.txt"
    ifconfig -a -v > "$CONFIG_DST_DEVSTACK/ifconfig.txt" 2>&1 && $GZIP "$CONFIG_DST_DEVSTACK/ifconfig.txt"
    sudo ovs-vsctl -v show > "$CONFIG_DST_DEVSTACK/ovs_bridges.txt" 2>&1 && $GZIP "$CONFIG_DST_DEVSTACK/ovs_bridges.txt"
}

function archive_tempest_files() {
    local TEMPEST_LOGS="/home/ubuntu/tempest"

    for i in `ls -A $TEMPEST_LOGS`
    do
        $GZIP "$TEMPEST_LOGS/$i" -c > "$LOG_DST/$i.gz" || emit_error "L133: Failed to archive tempest logs"
    done
}

