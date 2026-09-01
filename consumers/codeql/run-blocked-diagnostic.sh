#!/usr/bin/env bash
set -euo pipefail

consumer_dir=$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)
repository_root=$(cd "$consumer_dir/../.." && pwd)
scenario_dir="$repository_root/scenarios/external-normalize"
analyzer_root="$scenario_dir/analyzer-input"
query_dir="$consumer_dir/query"
output=${1:-"$consumer_dir/blocked-diagnostic.json"}

source "$consumer_dir/versions.env"
actual_codeql=$(codeql version --format=terse)
if [[ "$actual_codeql" != "$CODEQL_CLI_VERSION" ]]; then
  echo "expected CodeQL CLI $CODEQL_CLI_VERSION, found $actual_codeql" >&2
  exit 2
fi

"$scenario_dir/scripts/verify.py"
python3 -m unittest discover -s "$consumer_dir" -p 'test_*.py' -v
codeql pack install "$query_dir"

work_dir=$(mktemp -d /private/tmp/csmi-codeql-diagnostic.XXXXXX)
resolved_packs="$work_dir/resolved-packs.json"
database_dir="$work_dir/database"
classes_dir="$work_dir/classes"
result_bqrs="$work_dir/off.bqrs"
result_json="$work_dir/off.json"
mkdir -p "$classes_dir"

codeql resolve packs --format=json > "$resolved_packs"
java_pack=$(python3 - "$resolved_packs" "$CODEQL_JAVA_ALL_VERSION" <<'PY'
import json
import sys

document = json.load(open(sys.argv[1], encoding="utf-8"))
version = sys.argv[2]
matches = []
for step in document.get("steps", []):
    found = step.get("found", {}).get("codeql/java-all", {}).get(version)
    if isinstance(found, dict) and isinstance(found.get("path"), str):
        matches.append(found["path"])
if len(matches) != 1:
    raise SystemExit(f"expected one resolved codeql/java-all@{version}, found {matches}")
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
  --output="$result_bqrs"
codeql bqrs decode "$result_bqrs" --format=json --output="$result_json"

python3 "$consumer_dir/verify_blocked.py" \
  --scenario="$scenario_dir/scenario.json" \
  --versions="$consumer_dir/versions.env" \
  --database="$database_dir" \
  --java-pack="$java_pack" \
  --result="$result_json" \
  --output="$output"

echo "diagnostic workspace retained at $work_dir"
