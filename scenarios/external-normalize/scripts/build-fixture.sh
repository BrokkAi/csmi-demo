#!/bin/sh
set -eu

scenario_dir=$(CDPATH='' cd -- "$(dirname -- "$0")/.." && pwd)
source_file="$scenario_dir/audit-source/src/main/java/ai/brokk/csmi/demo/ExternalNormalizer.java"
artifact="$scenario_dir/analyzer-input/lib/external-normalize-1.0.0.jar"
expected_jdk='21.0.8'
expected_sha256='d343c7d2fc3703ac426340bd6c7ae5ed4c414436f197b7a2cc98fc4a9357d8e8'

actual_javac=$(javac -version 2>&1 | awk '{print $2}')
actual_jar=$(jar --version 2>&1 | awk '{print $2}')
if [ "$actual_javac" != "$expected_jdk" ] || [ "$actual_jar" != "$expected_jdk" ]; then
  echo "expected javac and jar $expected_jdk; found javac $actual_javac and jar $actual_jar" >&2
  exit 1
fi

build_dir=$(mktemp -d "${TMPDIR:-/tmp}/csmi-external-normalize.XXXXXX")
trap 'rm -rf "$build_dir"' EXIT HUP INT TERM
classes="$build_dir/classes"
mkdir -p "$classes" "$(dirname -- "$artifact")"
javac --release 17 -encoding UTF-8 -d "$classes" "$source_file"
jar --create --file "$build_dir/external-normalize-1.0.0.jar" \
  --date=1980-01-01T00:00:02Z -C "$classes" .

actual_sha256=$(shasum -a 256 "$build_dir/external-normalize-1.0.0.jar" | awk '{print $1}')
if [ "$expected_sha256" = 'TO_BE_FILLED' ]; then
  echo "$actual_sha256"
  exit 2
fi
if [ "$actual_sha256" != "$expected_sha256" ]; then
  echo "fixture digest mismatch: expected $expected_sha256, built $actual_sha256" >&2
  exit 1
fi
if [ -f "$artifact" ]; then
  retained_sha256=$(shasum -a 256 "$artifact" | awk '{print $1}')
  if [ "$retained_sha256" != "$expected_sha256" ]; then
    echo "retained fixture digest mismatch: expected $expected_sha256, found $retained_sha256" >&2
    exit 1
  fi
  cmp "$build_dir/external-normalize-1.0.0.jar" "$artifact"
else
  cp "$build_dir/external-normalize-1.0.0.jar" "$artifact"
fi
echo "verified external-normalize-1.0.0.jar sha256:$actual_sha256"
