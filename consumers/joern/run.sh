#!/usr/bin/env bash
set -euo pipefail

readonly JOERN_VERSION="4.0.592"
readonly HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -ne 5 ]]; then
  echo "usage: $0 SCENARIO_DIR JOERN_HOME JDK_HOME EXPECTED_PACK_DIGEST OUTPUT_DIR" >&2
  exit 64
fi

readonly SCENARIO_DIR="$1"
readonly JOERN_HOME="$2"
readonly JDK_HOME="$3"
readonly EXPECTED_PACK_DIGEST="$4"
readonly OUTPUT_DIR="$5"
readonly CPG="$OUTPUT_DIR/application.cpg.bin.zip"
readonly METHODS="$OUTPUT_DIR/methods.json"
readonly SEMANTICS="$OUTPUT_DIR/semantics.json"

mkdir -p "$OUTPUT_DIR"

[[ -x "$JOERN_HOME/joern" ]] || { echo "missing Joern executable: $JOERN_HOME/joern" >&2; exit 2; }
[[ -x "$JOERN_HOME/javasrc2cpg" ]] || { echo "missing Java frontend: $JOERN_HOME/javasrc2cpg" >&2; exit 2; }
[[ -f "$JOERN_HOME/lib/io.joern.joern-cli-$JOERN_VERSION.jar" ]] || { echo "Joern distribution is not exactly $JOERN_VERSION" >&2; exit 2; }
[[ -x "$JDK_HOME/bin/java" ]] || { echo "missing pinned JDK: $JDK_HOME/bin/java" >&2; exit 2; }
"$JDK_HOME/bin/java" -version 2>&1 | grep -F '21.0.8' >/dev/null || { echo "JDK must be Temurin 21.0.8+9-LTS" >&2; exit 2; }
[[ -d "$SCENARIO_DIR/application" ]] || { echo "shared issue #1 application is absent" >&2; exit 3; }
[[ -f "$SCENARIO_DIR/artifact.json" ]] || { echo "shared issue #1 artifact evidence is absent" >&2; exit 3; }
[[ -f "$SCENARIO_DIR/csmi-pack/manifest.json" ]] || { echo "shared issue #1 CSMI pack is absent" >&2; exit 3; }

# The shared external library source is never an input. Its pinned binary is
# supplied only as a dependency to Java type recovery.
"$JOERN_HOME/javasrc2cpg" \
  "$SCENARIO_DIR/application" \
  --inference-jar-paths "$SCENARIO_DIR/artifacts/external-normalize.jar" \
  --jdk-path "$JDK_HOME" \
  --enable-type-recovery \
  --disable-type-fallback \
  --delombok-mode no-delombok \
  --output "$CPG"

"$JOERN_HOME/joern" --script "$HERE/methods.sc" --param cpgFile="$CPG" --param output="$METHODS"
python3 "$HERE/adapter.py" \
  --pack "$SCENARIO_DIR/csmi-pack" \
  --artifact "$SCENARIO_DIR/artifact.json" \
  --methods "$METHODS" \
  --expected-pack-digest "$EXPECTED_PACK_DIGEST" \
  --output "$SEMANTICS"

# Both executions import the identical CPG and run the identical query. Only
# the CSMI-derived custom FlowSemantic list changes.
"$JOERN_HOME/joern" --script "$HERE/flows.sc" --param cpgFile="$CPG" --param semanticsFile="$SEMANTICS" --param packEnabled=false --param output="$OUTPUT_DIR/pack-off.json"
"$JOERN_HOME/joern" --script "$HERE/flows.sc" --param cpgFile="$CPG" --param semanticsFile="$SEMANTICS" --param packEnabled=true --param output="$OUTPUT_DIR/pack-on.json"
