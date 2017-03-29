#!/bin/bash

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
 
set -x
set +e

source ${WORKSPACE}/common-ci/scripts/jobs/${project}-config.sh

DEPLOYER_PATH="/home/ubuntu/deployer"
JUJU_SSH_KEY="/home/ubuntu/.local/share/juju/ssh/juju_id_rsa"
LOGS_SERVER="10.20.1.14"
LOGS_SSH_KEY="/home/ubuntu/.ssh/norman.pem"
BUNDLE_LOCATION=$(mktemp)

eval "cat <<EOF
$(<${WORKSPACE}/common-ci/templates/bundle.template)
EOF
" >> $BUNDLE_LOCATION

cat $BUNDLE_LOCATION

$DEPLOYER_PATH/deployer.py  --clouds-and-credentials $DEPLOYER_PATH/$CI_CREDS deploy --template $BUNDLE_LOCATION --max-unit-retries 10 --timeout 7200 --search-string $UUID
build_exit_code=$?

source $WORKSPACE/nodes
    
exec_with_retry 5 2 ssh -tt -o 'PasswordAuthentication=no' -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' -i $JUJU_SSH_KEY ubuntu@$DEVSTACK \
    "git clone https://github.com/cloudbase/common-ci.git /home/ubuntu/common-ci"
clone_exit_code=$?

exec_with_retry 5 2 ssh -tt -o 'PasswordAuthentication=no' -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' -i $JUJU_SSH_KEY ubuntu@$DEVSTACK \
    "git -C /home/ubuntu/common-ci checkout charms"
checkout_exit_code=$?

	
if [[ $build_exit_code -eq 0 ]]; then
	#run tempest
	
    exec_with_retry 5 2 ssh -tt -o 'PasswordAuthentication=no' -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' -i $JUJU_SSH_KEY ubuntu@$DEVSTACK \
        "mkdir -p /home/ubuntu/tempest"
	ssh -tt -o 'PasswordAuthentication=no' -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' -i $JUJU_SSH_KEY ubuntu@$DEVSTACK \
       "/home/ubuntu/common-ci/scripts/bin/run-all-tests.sh --include-file /home/ubuntu/common-ci/tests/$project/included_tests.txt \
       --exclude-file /home/ubuntu/common-ci/tests/$project/excluded_tests.txt --isolated-file /home/ubuntu/common-ci/tests/$project/isolated_tests.txt \
       --tests-dir /opt/stack/tempest --parallel-tests 10 --max-attempts 2"
	tests_exit_code=$?
fi 

######################### Collect logs #########################
LOG_DIR="logs/${UUID}"
if [ $LOG_DIR ]; then
    rm -rf $LOG_DIR
fi
mkdir -p "$LOG_DIR"

ssh -tt -o 'PasswordAuthentication=no' -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' -i $JUJU_SSH_KEY ubuntu@$DEVSTACK \
    "sudo /home/ubuntu/common-ci/scripts/logs/collect-logs.sh"

scp -o 'PasswordAuthentication=no' -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' -i $JUJU_SSH_KEY \
ubuntu@$DEVSTACK:/home/ubuntu/aggregate.tar.gz $LOG_DIR/aggregate.tar.gz

tar -zxf $LOG_DIR/aggregate.tar.gz -C $LOG_DIR/
rm $LOG_DIR/aggregate.tar.gz

source $WORKSPACE/common-ci/scripts/logs/utils.sh

for hv in $(echo $HYPERV | tr "," "\n"); do
    HV_LOGS=$LOG_DIR/hyperv-logs/$hv
    HV_CONFS=$LOG_DIR/hyperv-config/$hv
    mkdir -p $HV_LOGS
    mkdir -p $HV_CONFS

    get_win_files $hv "\openstack\log" $HV_LOGS
    get_win_files $hv "\openstack\etc" $HV_CONFS
    get_win_files $hv "\juju\log" $HV_LOGS
    
    run_wsman_cmd $hv 'systeminfo' > $HV_LOGS/systeminfo.log
    run_wsman_cmd $hv 'wmic qfe list' > $HV_LOGS/windows-hotfixes.log
    run_wsman_cmd $hv 'c:\python27\scripts\pip freeze' > $HV_LOGS/pip-freeze.log
    run_wsman_cmd $hv 'ipconfig /all' > $HV_LOGS/ipconfig.log
    run_wsman_cmd $hv 'sc qc nova-compute' > $HV_LOGS/nova-compute-service.log
    run_wsman_cmd $hv 'sc qc neutron-openvswitch-agent' > $HV_LOGS/neutron-openvswitch-agent-service.log
    
    run_wsman_ps $hv 'get-netadapter ^| Select-object *' > $HV_LOGS/get-netadapter.log
    run_wsman_ps $hv 'get-vmswitch ^| Select-object *' > $HV_LOGS/get-vmswitch.log
    run_wsman_ps $hv 'get-WmiObject win32_logicaldisk ^| Select-object *' > $HV_LOGS/disk-free.log
    run_wsman_ps $hv 'get-netfirewallprofile ^| Select-Object *' > $HV_LOGS/firewall.log
    
    run_wsman_ps $hv 'get-process ^| Select-Object *' > $HV_LOGS/get-process.log
    run_wsman_ps $hv 'get-service ^| Select-Object *' > $HV_LOGS/get-service.log 
done

wget http://10.20.1.3:8080/job/$JOB_NAME/$BUILD_ID/consoleText -O $LOG_DIR/console.log

find $LOG_DIR -name "*.log" -exec gzip {} \;

tar -zcf $LOG_DIR/aggregate.tar.gz $LOG_DIR

if [ $project == "ovs" ]; then
    if [ ! $UUID ]; then
        exit 1
    fi
    REMOTE_LOG_PATH="/srv/logs/ovs/tempest-run/$UUID"
elif [ $network_type == "ovs" ]; then
    if [ ! $project ] || [ ! $ZUUL_CHANGE ] || [ ! $ZUUL_PATCHSET ]; then
        exit 1
    fi
    REMOTE_LOG_PATH="/srv/logs/${project}-ovs/$ZUUL_CHANGE/$ZUUL_PATCHSET"
else
    if [ ! $project ] || [ ! $ZUUL_CHANGE ] || [ ! $ZUUL_PATCHSET ]; then
        exit 1
    fi
    REMOTE_LOG_PATH="/srv/logs/$project/$ZUUL_CHANGE/$ZUUL_PATCHSET"
fi

# Copy logs to remote log server
echo "Creating logs destination folder"
ssh -tt -o 'PasswordAuthentication=no' -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' -i $LOGS_SSH_KEY logs@$LOGS_SERVER \
    "rm -r $REMOTE_LOG_PATH"
ssh -tt -o 'PasswordAuthentication=no' -o 'StrictHostKeyChecking=no' -o 'UserKnownHostsFile=/dev/null' -i $LOGS_SSH_KEY logs@$LOGS_SERVER \
    "mkdir -p $REMOTE_LOG_PATH"
        #"if [ ! -d $REMOTE_LOG_PATH ]; then mkdir -p $REMOTE_LOG_PATH; else rm -r $REMOTE_LOG_PATH/*; fi"

echo "Uploading logs"
scp -o "UserKnownHostsFile /dev/null" -o "StrictHostKeyChecking no" -i $LOGS_SSH_KEY $LOG_DIR/aggregate.tar.gz logs@$LOGS_SERVER:$REMOTE_LOG_PATH/aggregate.tar.gz

echo "Extracting logs"
ssh -o "UserKnownHostsFile /dev/null" -o "StrictHostKeyChecking no" -i $LOGS_SSH_KEY logs@$LOGS_SERVER "tar -xvf $REMOTE_LOG_PATH/aggregate.tar.gz -C $REMOTE_LOG_PATH/ --strip 1"

# Remove local logs
rm -rf $LOG_DIR
##############################################

if [ "$DEBUG" != "YES" ]; then
    #destroy charms, services and used nodes.
    $DEPLOYER_PATH/deployer.py  --clouds-and-credentials $DEPLOYER_PATH/$CI_CREDS teardown --search-string $UUID
fi

if [[ $build_exit_code -ne 0 ]]; then
	echo "CI Error while deploying environment"
	exit 1
fi
 
if [[ $clone_exit_code -ne 0 ]]; then
	echo "CI Error while cloning the scripts repository"
	exit 1
fi

if [[ $checkout_exit_code -ne 0 ]]; then
	echo "CI Error while checking out the scripts repository"
	exit 1
fi

if [[ $tests_exit_code -ne 0 ]]; then
	echo "Tempest tests execution finished with a failure status"
	exit 1
fi 

exit 0
