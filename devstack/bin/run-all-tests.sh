#!/bin/bash

function help() {
    echo "Required parameters:"
    echo "    --include-file: the tempest test groups to be executed"
    echo "    --exclude-file: tempest tests that have to be excluded"
    echo "    --tests-dir: tempest execution folder"
    echo "Optional parameters:"
    echo "    --isolated-file: tempest tests that require to be executed isolated" 
    echo "    --parallel-tests: number of tempest tests to run in parallel (DEFAULT: 4)"
    echo "    --max-attempts: number of retries if a test fails (DEFAULT: 2)"
    echo "    --log-file: name of the tempest run log file (including full path)"
    echo "    --results-html-file: name of the html results file (including full path)"
}

while [ $# -gt 0 ]
do
    case $1 in
        --include-file)
            INCLUDE_FILE=$2
            shift;;
        --exclude-file)
            EXCLUDE_FILE=$2
            shift;;
        --isolated-file)
            ISOLATED_FILE=$2
            shift;;
        --tests-dir)
            TESTS_DIR=$2
            shift;;
        --parallel-tests)
            PARALLEL_TESTS=$2
            shift;;
        --max-attempts)
            MAX_ATTEMPTS=$2
            shift;;
        --log-file)
            LOG_FILE=$2
            shift;;
        --results-html-file)
            RESULTS_HTML_FILE=$2
            shift;;
        *)
            echo "no such option"
            help
    esac
    shift
done

if [ -z "$INCLUDE_FILE" ]; then echo "tempest include file must be provided"; exit 1; fi
if [ -z "$EXCLUDE_FILE" ]; then echo "tempest exclude file must be provided"; exit 1; fi
if [ -z "$TESTS_DIR" ]; then echo "tempest execution folder must be provided"; exit 1; fi
if [ -z "$PARALLEL_TESTS" ]; then PARALLEL_TESTS=4; fi
if [ -z "$MAX_ATTEMPTS" ]; then MAX_ATTEMPTS=2; fi
if [ -z "$LOG_FILE" ]; then LOG_FILE="/home/ubuntu/tempest/subunit-output.log"; fi
if [ -z "$RESULTS_HTML_FILE" ]; then RESULTS_HTML_FILE="/home/ubuntu/tempest/results.html"; fi

BASEDIR=$(dirname $0)

pushd $BASEDIR

. $BASEDIR/utils.sh

TESTS_FILE=$(tempfile)

#. $TESTS_DIR/.tox/tempest/bin/activate

$BASEDIR/get-tests.sh $TESTS_DIR $INCLUDE_FILE $EXCLUDE_FILE $ISOLATED_FILE > $TESTS_FILE

echo "Running tests from: $TESTS_FILE"

if [ ! -d "$TESTS_DIR/.testrepository" ]; then
    push_dir
    cd $TESTS_DIR
    echo "Initializing testr"
    testr init
    pop_dir
fi

$BASEDIR/parallel-test-runner.sh $TESTS_FILE $TESTS_DIR $LOG_FILE \
    $PARALLEL_TESTS $MAX_ATTEMPTS || true

if [ -f "$ISOLATED_FILE" ]; then
    echo "Running isolated tests from: $ISOLATED_FILE"
    log_tmp=$(tempfile)
    $BASEDIR/parallel-test-runner.sh $ISOLATED_FILE $TESTS_DIR $log_tmp \
        $PARALLEL_TESTS $MAX_ATTEMPTS 1 || true

    cat $log_tmp >> $LOG_FILE
    rm $log_tmp
fi

rm $TESTS_FILE

#deactivate

echo "Generating HTML report..."
$BASEDIR/get-results-html.sh $LOG_FILE $RESULTS_HTML_FILE

subunit-stats $LOG_FILE > /dev/null
exit_code=$?

echo "Total execution time: $SECONDS seconds."

popd

exit $exit_code

