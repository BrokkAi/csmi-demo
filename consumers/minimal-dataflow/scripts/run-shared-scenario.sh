#!/bin/sh
set -eu

consumer_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
repository=$(CDPATH='' cd -- "$consumer_dir/../.." && pwd)
scenario="$repository/scenarios/external-normalize"
analysis="$consumer_dir/inputs/external-normalize.json"
results="$consumer_dir/results"

mkdir -p "$results"
cd "$consumer_dir"

python3 -m minimal_dataflow.cli \
  --analysis "$analysis" \
  --scenario "$scenario" \
  --pack off \
  --output "$results/pack-off.json"

set +e
python3 -m minimal_dataflow.cli \
  --analysis "$analysis" \
  --scenario "$scenario" \
  --pack on \
  --output "$results/pack-on.json"
pack_on_status=$?
set -e

if [ "$pack_on_status" -ne 2 ]; then
  echo "expected the currently blocked pack-on run to exit 2; found $pack_on_status" >&2
  exit 1
fi

python3 "$consumer_dir/scripts/verify-results.py"
