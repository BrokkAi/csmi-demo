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
codeql pack install "$query_dir"

work_dir=$(mktemp -d /private/tmp/csmi-codeql-consumer.XXXXXX)
database_dir="$work_dir/database"
classes_dir="$work_dir/classes"
model_dir="$work_dir/model"
mkdir -p "$classes_dir"

python3 "$consumer_dir/generate_model.py" \
  --pack "$scenario_dir/pack" \
  --artifact "$analyzer_root/lib/external-normalize-1.0.0.jar" \
  --output "$model_dir"

codeql resolve packs --format=json > "$work_dir/resolved-packs.json"
java_pack=$(python3 - "$work_dir/resolved-packs.json" "$CODEQL_JAVA_ALL_VERSION" <<'PY'
import json
import sys

document = json.load(open(sys.argv[1], encoding="utf-8"))
matches = []
for step in document.get("steps", []):
    found = step.get("found", {}).get("codeql/java-all", {}).get(sys.argv[2])
    if isinstance(found, dict) and isinstance(found.get("path"), str):
        matches.append(found["path"])
if len(matches) != 1:
    raise SystemExit(f"expected one resolved codeql/java-all@{sys.argv[2]}, found {matches}")
print(matches[0])
PY
)

(
  cd "$analyzer_root"
  codeql database create "$database_dir" \
    --language=java \
    --source-root="$analyzer_root" \
    --command="javac --release 17 -encoding UTF-8 -classpath lib/external-normalize-1.0.0.jar -d $classes_dir src/main/java/ai/brokk/csmi/demo/ScenarioApplication.java"
)

codeql query run "$query_dir/ExternalNormalize.ql" \
  --database="$database_dir" \
  --output="$work_dir/off.bqrs"
codeql query run "$query_dir/ExternalNormalize.ql" \
  --database="$database_dir" \
  --additional-packs="$work_dir" \
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
