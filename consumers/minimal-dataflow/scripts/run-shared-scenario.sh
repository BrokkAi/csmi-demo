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

python3 -m minimal_dataflow.cli \
  --analysis "$analysis" \
  --scenario "$scenario" \
  --pack on \
  --output "$results/pack-on.json"

python3 "$consumer_dir/scripts/verify-results.py"
