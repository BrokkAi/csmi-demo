#!/usr/bin/env bash
set -euo pipefail

readonly JOERN_VERSION="4.0.592"
readonly JOERN_CLI_SHA256="22dc242defb713f1f7257ee5efc3be7b7abd3216d9d8f500906bbe04716b47c4"
readonly JAVA_FRONTEND_SHA256="60bc0f0eb9c0fcb3c02e4eed890766c2720b146ed00942bbcfa87fb5779bc234"
readonly HERE="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"

if [[ $# -ne 4 ]]; then
  echo "usage: $0 SCENARIO_DIR JOERN_HOME JDK_HOME OUTPUT_DIR" >&2
  exit 64
fi

readonly SCENARIO_DIR="$(cd -- "$1" && pwd)"
readonly JOERN_HOME="$2"
readonly JDK_HOME="$3"
mkdir -p "$4"
readonly OUTPUT_DIR="$(cd -- "$4" && pwd)"
readonly CPG="$OUTPUT_DIR/application.cpg.bin.zip"
readonly METHODS="$OUTPUT_DIR/methods.json"
readonly SEMANTICS="$OUTPUT_DIR/semantics.json"
readonly LABELS="$SCENARIO_DIR/labels.json"
readonly SCENARIO_MANIFEST="$SCENARIO_DIR/scenario.json"

mkdir -p "$OUTPUT_DIR"

[[ -x "$JOERN_HOME/joern" ]] || { echo "missing Joern executable: $JOERN_HOME/joern" >&2; exit 2; }
[[ -x "$JOERN_HOME/javasrc2cpg" ]] || { echo "missing Java frontend: $JOERN_HOME/javasrc2cpg" >&2; exit 2; }
[[ -f "$JOERN_HOME/lib/io.joern.joern-cli-$JOERN_VERSION.jar" ]] || { echo "Joern distribution is not exactly $JOERN_VERSION" >&2; exit 2; }
[[ "$(shasum -a 256 "$JOERN_HOME/lib/io.joern.joern-cli-$JOERN_VERSION.jar" | awk '{print $1}')" == "$JOERN_CLI_SHA256" ]] || { echo "Joern CLI JAR digest mismatch" >&2; exit 2; }
[[ "$(shasum -a 256 "$JOERN_HOME/frontends/javasrc2cpg/lib/io.joern.javasrc2cpg-$JOERN_VERSION.jar" | awk '{print $1}')" == "$JAVA_FRONTEND_SHA256" ]] || { echo "Joern Java frontend JAR digest mismatch" >&2; exit 2; }
[[ -x "$JDK_HOME/bin/java" ]] || { echo "missing pinned JDK: $JDK_HOME/bin/java" >&2; exit 2; }
readonly JAVA_PROPERTIES="$("$JDK_HOME/bin/java" -XshowSettings:properties -version 2>&1)"
grep -F 'java.runtime.version = 21.0.8+9-LTS' <<<"$JAVA_PROPERTIES" >/dev/null || { echo "JDK runtime must be 21.0.8+9-LTS" >&2; exit 2; }
grep -F 'java.vendor = Eclipse Adoptium' <<<"$JAVA_PROPERTIES" >/dev/null || { echo "JDK vendor must be Eclipse Adoptium (Temurin)" >&2; exit 2; }
export JAVA_HOME="$JDK_HOME"
export PATH="$JDK_HOME/bin:$PATH"
[[ -d "$SCENARIO_DIR/analyzer-input/src/main/java" ]] || { echo "shared issue #1 application is absent" >&2; exit 3; }
[[ -f "$SCENARIO_MANIFEST" ]] || { echo "shared issue #1 scenario manifest is absent" >&2; exit 3; }
[[ -f "$LABELS" ]] || { echo "shared issue #1 labels are absent" >&2; exit 3; }

"$SCENARIO_DIR/scripts/verify.py"

# The shared external library source is never an input. Its pinned binary is
# supplied only as a dependency to Java type recovery.
"$JOERN_HOME/javasrc2cpg" \
  "$SCENARIO_DIR/analyzer-input/src/main/java" \
  --inference-jar-paths "$SCENARIO_DIR/analyzer-input/lib/external-normalize-1.0.0.jar" \
  --jdk-path "$JDK_HOME" \
  --enable-type-recovery \
  --disable-type-fallback \
  --delombok-mode no-delombok \
  --output "$CPG"

mkdir -p "$OUTPUT_DIR/method-workspace" "$OUTPUT_DIR/pack-off-workspace"
(
  cd -- "$OUTPUT_DIR/method-workspace"
  "$JOERN_HOME/joern" --script "$HERE/methods.sc" --param cpgFile="$CPG" --param output="$METHODS"
)

# Both executions import the identical CPG and run the identical query. Only
# the CSMI-derived custom FlowSemantic list changes.
(
  cd -- "$OUTPUT_DIR/pack-off-workspace"
  "$JOERN_HOME/joern" --script "$HERE/flows.sc" --param cpgFile="$CPG" --param labelsFile="$LABELS" --param semanticsFile="$SEMANTICS" --param packEnabled=false --param output="$OUTPUT_DIR/pack-off-observations.json"
)
python3 "$HERE/results.py" --scenario "$SCENARIO_DIR" --cpg "$CPG" --methods "$METHODS" --observations "$OUTPUT_DIR/pack-off-observations.json" --output "$OUTPUT_DIR/pack-off.json"

python3 "$HERE/adapter.py" --scenario "$SCENARIO_MANIFEST" --methods "$METHODS" --output "$SEMANTICS"
mkdir -p "$OUTPUT_DIR/pack-on-workspace"
(
  cd -- "$OUTPUT_DIR/pack-on-workspace"
  "$JOERN_HOME/joern" --script "$HERE/flows.sc" --param cpgFile="$CPG" --param labelsFile="$LABELS" --param semanticsFile="$SEMANTICS" --param packEnabled=true --param output="$OUTPUT_DIR/pack-on-observations.json"
)
python3 "$HERE/results.py" --scenario "$SCENARIO_DIR" --cpg "$CPG" --methods "$METHODS" --observations "$OUTPUT_DIR/pack-on-observations.json" --semantics "$SEMANTICS" --baseline "$OUTPUT_DIR/pack-off.json" --pack-enabled --output "$OUTPUT_DIR/pack-on.json"
