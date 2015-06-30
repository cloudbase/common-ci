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
        echo "Host $host1 time offset compared to this host is too high: $delta"
        return 1
    fi
    if [ ${delta2#-} -gt 120 ];
    then
        echo "Host $host2 time offset compared to this host is too high: $delta"
        return 1
    fi
    return 0
}
