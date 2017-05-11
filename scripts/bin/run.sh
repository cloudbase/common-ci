#!/bin/bash
set -e

BASEDIR=$(dirname $0)

. $BASEDIR/utils.sh






tempest_dir="/opt/stack/tempest"
test_config_dir"$tempest_dir/config
test_logs_dir="$tempest_dir/logs"
subunit_log_file="subunit.log"
html_results_file="results.html"
max_parallel_tests=4
max_attempts=3

project=$(basename $ZUUL_PROJECT)
filters_location="/home/ubuntu/$project-ci/devstack/tests"
include_file="$filters_location/included_tests.txt"
exclude_file="$filters_location/excluded_tests.txt"
isolated_file="$filters_location/isolated_tests.txt"

$log_dir="/home/ubuntu/tempest"
if [ ! -d $log_dir ]; then mkdir -p $log_dir; fi

$BASEDIR/run-all-tests.sh --tests-dir $tempest_dir \
                          --parallel-tests $max_parallel_tests \
                          --max-attempts $max_attempts \
                          --log-file "$log_dir/$subunit_log_file" \
                          --results-html-file "$log_dir/$html_results_file" \
                          --include-file
                          -- exclude-file
                          --isolated-file
    > $test_logs_dir/out.txt 2> $test_logs_dir/err.txt \
    || has_failed_tests=1

subunit-stats --no-passthrough "$log_dir/$subunit_log_file" || true

<< 'TBD'
    copy_devstack_config_files "$test_config_dir/devstack"

    for host_name in ${host_names[@]};
    do
        exec_with_retry 15 2 get_win_host_config_files $host_name "$test_config_dir/$host_name"
        exec_with_retry 5 0 get_win_system_info_log $host_name "$test_logs_dir/$host_name/systeminfo.log"
        exec_with_retry 5 0 get_win_hotfixes_log $host_name "$test_logs_dir/$host_name/hotfixes.log"
        exec_with_retry 15 2 get_win_host_log_files $host_name "$test_logs_dir/$host_name"
    done

    echo "Removing symlinks from logs"
    find "$test_logs_dir/" -type l -delete
    echo "Compressing log files"
    find "$test_logs_dir/" -name "*.log" -exec gzip {} \;
TBD

exit $has_failed_tests
