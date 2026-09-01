#!/usr/bin/env bash
set -euo pipefail

consumer_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
repository_root=$(cd "$consumer_dir/../.." && pwd)
scenario_dir="$repository_root/scenarios/external-normalize"
analyzer_root="$scenario_dir/analyzer-input"
query_dir="$consumer_dir/query"
output_dir=${1:-"$consumer_dir/results"}

source "$consumer_dir/versions.env"
actual_codeql=$(codeql version --format=terse)
if [[ "$actual_codeql" != "$CODEQL_CLI_VERSION" ]]; then
  echo "expected CodeQL CLI $CODEQL_CLI_VERSION, found $actual_codeql" >&2
  exit 2
fi
actual_javac=$(javac -version 2>&1)
if [[ "$actual_javac" != "javac 21.0.8" ]]; then
  echo "expected javac 21.0.8, found $actual_javac" >&2
  exit 2
fi

"$scenario_dir/scripts/verify.py"
python3 -m unittest discover -s "$consumer_dir" -p 'test_*.py' -v

temp_root=${RUNNER_TEMP:-${TMPDIR:-/tmp}}
work_dir=$(mktemp -d "$temp_root/csmi-codeql-consumer.XXXXXX")
database_dir="$work_dir/database"
classes_dir="$work_dir/classes"
model_dir="$work_dir/model"
pinned_pack_root="$work_dir/pinned-packs"
mkdir -p "$classes_dir"

codeql pack download --force --dir="$pinned_pack_root" -- \
  "codeql/java-all@$CODEQL_JAVA_ALL_VERSION"
java_pack="$pinned_pack_root/codeql/java-all/$CODEQL_JAVA_ALL_VERSION/qlpack.yml"

python3 "$consumer_dir/generate_model.py" \
  --pack "$scenario_dir/pack" \
  --artifact "$analyzer_root/lib/external-normalize-1.0.0.jar" \
  --output "$model_dir"

(
  cd "$analyzer_root"
  codeql database create "$database_dir" \
    --language=java \
    --source-root="$analyzer_root" \
    --command="javac --release 17 -encoding UTF-8 -classpath lib/external-normalize-1.0.0.jar -d $classes_dir src/main/java/ai/brokk/csmi/demo/ScenarioApplication.java"
)

codeql query run "$query_dir/ExternalNormalize.ql" \
  --database="$database_dir" \
  --additional-packs="$pinned_pack_root" \
  --output="$work_dir/off.bqrs"
codeql query run "$query_dir/ExternalNormalize.ql" \
  --database="$database_dir" \
  --additional-packs="$pinned_pack_root:$work_dir" \
  --model-packs=brokkai/csmi-external-normalize-model@0.0.0 \
  --output="$work_dir/on.bqrs"
codeql bqrs decode "$work_dir/off.bqrs" --format=json --output="$work_dir/off.json"
codeql bqrs decode "$work_dir/on.bqrs" --format=json --output="$work_dir/on.json"

python3 "$consumer_dir/verify_results.py" \
  --scenario="$scenario_dir/scenario.json" \
  --labels="$scenario_dir/labels.json" \
  --versions="$consumer_dir/versions.env" \
  --database="$database_dir" \
  --java-pack="$java_pack" \
  --query="$query_dir/ExternalNormalize.ql" \
  --trace="$model_dir/trace.json" \
  --off-result="$work_dir/off.json" \
  --on-result="$work_dir/on.json" \
  --output-dir="$output_dir"

echo "CodeQL workspace retained at $work_dir"
