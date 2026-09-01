#!/bin/sh
set -eu

consumer_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
scenario=$(CDPATH='' cd -- "$consumer_dir/../.." && pwd)/scenarios/external-normalize
results="$consumer_dir/results"

cd "$consumer_dir"
./mvnw --batch-mode --no-transfer-progress -q compile exec:java \
  -Dexec.mainClass=ai.brokk.csmi.flowdroid.FlowDroidScenarioCli \
  -Dexec.args="--scenario $scenario --output $results/pack-off.json --pack off"
./mvnw --batch-mode --no-transfer-progress -q compile exec:java \
  -Dexec.mainClass=ai.brokk.csmi.flowdroid.FlowDroidScenarioCli \
  -Dexec.args="--scenario $scenario --output $results/pack-on.json --pack on"
python3 "$consumer_dir/scripts/verify-results.py"
