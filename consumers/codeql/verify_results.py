#!/usr/bin/env python3
"""Build fail-closed CodeQL results for the shared external-normalize scenario."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import zipfile
from pathlib import Path


RESULT_FORMAT = "csmi-demo-consumer-result/1"
ANALYSIS_FORMAT = "codeql-java-query/1"
CONSUMER_NAME = "brokkai.csmi.codeql"


class InvalidResult(ValueError):
    pass


def load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidResult(f"cannot read valid JSON from {path}: {error}") from error
    if not isinstance(value, dict):
        raise InvalidResult(f"{path} must contain a JSON object")
    return value


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_versions(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or not value or key in values:
            raise InvalidResult(f"invalid versions entry: {line!r}")
        values[key] = value
    required = {
        "CODEQL_CLI_VERSION",
        "CODEQL_JAVA_ALL_VERSION",
        "CODEQL_JAVA_ALL_SHA",
        "CODEQL_LINUX_BUNDLE_SHA256",
    }
    if values.keys() != required:
        raise InvalidResult(f"versions.env keys must be exactly {sorted(required)}")
    return values


def source_inventory(database: Path, analyzer_root: Path) -> list[str]:
    archive = database / "src.zip"
    try:
        with zipfile.ZipFile(archive) as source_zip:
            names = [name for name in source_zip.namelist() if not name.endswith("/")]
    except (OSError, zipfile.BadZipFile) as error:
        raise InvalidResult(f"cannot inspect CodeQL source archive {archive}: {error}") from error
    suffix = (
        "scenarios/external-normalize/analyzer-input/src/main/java/"
        "ai/brokk/csmi/demo/ScenarioApplication.java"
    )
    if len(names) != 1 or not names[0].endswith(suffix):
        raise InvalidResult(f"CodeQL source archive crosses the analyzer boundary: {names}")
    metadata = (database / "codeql-database.yml").read_text(encoding="utf-8")
    if f"sourceLocationPrefix: {analyzer_root.resolve()}" not in metadata.splitlines():
        raise InvalidResult("CodeQL database sourceLocationPrefix is not the exact analyzer input root")
    return [suffix]


def verify_java_pack(path: Path, versions: dict[str, str]) -> None:
    lines = path.read_text(encoding="utf-8").splitlines()
    required = {
        "name: codeql/java-all",
        f"version: {versions['CODEQL_JAVA_ALL_VERSION']}",
        f"  sha: {versions['CODEQL_JAVA_ALL_SHA']}",
    }
    missing = sorted(required - set(lines))
    if missing:
        raise InvalidResult(f"resolved java-all identity mismatch: missing {missing}")


def observed_labels(result: dict, allowed: set[str]) -> set[str]:
    table = result.get("#select")
    if not isinstance(table, dict) or not isinstance(table.get("tuples"), list):
        raise InvalidResult("decoded BQRS must contain a #select tuple array")
    labels = []
    for row in table["tuples"]:
        if not isinstance(row, list) or len(row) != 1 or not isinstance(row[0], str):
            raise InvalidResult(f"invalid CodeQL result row: {row!r}")
        labels.append(row[0])
    if len(labels) != len(set(labels)):
        raise InvalidResult("CodeQL query emitted duplicate labels")
    unknown = set(labels) - allowed
    if unknown:
        raise InvalidResult(f"CodeQL query emitted unknown shared labels: {sorted(unknown)}")
    return set(labels)


def metric(numerator: int, denominator: int) -> dict:
    value = {"defined": denominator != 0, "numerator": numerator, "denominator": denominator}
    if denominator:
        value["value"] = numerator / denominator
    return value


def classify(labels: list[dict], observed: set[str]) -> tuple[list[dict], dict, dict]:
    counts = {"truePositive": 0, "falsePositive": 0, "falseNegative": 0, "trueNegative": 0}
    names = {(True, True): ("TP", "truePositive"), (False, True): ("FP", "falsePositive"),
             (True, False): ("FN", "falseNegative"), (False, False): ("TN", "trueNegative")}
    flows = []
    for label in labels:
        expected = label.get("expected")
        identity = label.get("id")
        if not isinstance(identity, str) or not isinstance(expected, bool):
            raise InvalidResult(f"invalid shared flow label: {label!r}")
        actual = identity in observed
        short, count = names[(expected, actual)]
        counts[count] += 1
        flows.append({"id": identity, "expectedFlow": expected, "observedFlow": actual, "classification": short})
    metrics = {
        "precision": metric(counts["truePositive"], counts["truePositive"] + counts["falsePositive"]),
        "recall": metric(counts["truePositive"], counts["truePositive"] + counts["falseNegative"]),
    }
    return flows, counts, metrics


def build_result(scenario_path: Path, labels_path: Path, query: Path, versions: dict[str, str],
                 inventory: list[str], provenance: dict, observed: set[str], enabled: bool) -> dict:
    scenario = load_object(scenario_path)
    labels_document = load_object(labels_path)
    identity = scenario["scenario"]
    binary = scenario["binaryArtifact"]
    pack = scenario["csmiPack"]
    if identity.get("status") != "materialized" or pack.get("status") != "available":
        raise InvalidResult("shared scenario and CSMI pack must be materialized")
    if sha256(labels_path) != identity["labels"]["sha256"]:
        raise InvalidResult("shared labels digest mismatch")
    manifest_path = scenario_path.parent / pack["manifestPath"]
    if sha256(manifest_path) != pack["packDigest"]["value"]:
        raise InvalidResult("shared pack manifest digest mismatch")
    artifact = scenario_path.parent / binary["path"]
    if sha256(artifact) != binary["sha256"]:
        raise InvalidResult("shared binary digest mismatch")
    flows, counts, metrics = classify(labels_document["flows"], observed)
    result = {
        "resultFormatVersion": RESULT_FORMAT,
        "status": "complete",
        "consumer": {"name": CONSUMER_NAME, "version": versions["CODEQL_CLI_VERSION"]},
        "analysis": {"canonicalSha256": sha256(query), "formatVersion": ANALYSIS_FORMAT},
        "artifact": {"purl": binary["purl"], "digests": [{"algorithm": "sha-256", "coverage": binary["digestCoverage"], "value": binary["sha256"]}]},
        "scenario": {
            "id": identity["id"], "version": identity["version"],
            "labels": {"path": identity["labels"]["path"], "sha256": identity["labels"]["sha256"]},
            "manifest": {"path": "scenario.json", "sha256": sha256(scenario_path)},
        },
        "pack": ({"state": "on", "digest": pack["packDigest"]} if enabled else {"state": "off"}),
        "provenance": {"records": [provenance] if enabled else []},
        "flows": flows,
        "counts": counts,
        "metrics": metrics,
        "environment": {
            "codeql": {
                "cliVersion": versions["CODEQL_CLI_VERSION"],
                "linuxBundleSha256": versions["CODEQL_LINUX_BUNDLE_SHA256"],
                "javaAllVersion": versions["CODEQL_JAVA_ALL_VERSION"],
                "javaAllSha": versions["CODEQL_JAVA_ALL_SHA"],
                "queryPack": "brokkai/csmi-demo-codeql-query@0.0.0",
            },
            "database": {"builtOnce": True, "inputRoot": scenario["analyzerBoundary"]["inputRoot"], "sourceInventory": inventory},
            "semanticToggle": "generated-csmi-model-pack" if enabled else "off",
        },
    }
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--labels", type=Path, required=True)
    parser.add_argument("--versions", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--java-pack", type=Path, required=True)
    parser.add_argument("--query", type=Path, required=True)
    parser.add_argument("--trace", type=Path, required=True)
    parser.add_argument("--off-result", type=Path, required=True)
    parser.add_argument("--on-result", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        versions = load_versions(args.versions)
        verify_java_pack(args.java_pack, versions)
        scenario = load_object(args.scenario)
        analyzer_root = args.scenario.parent / scenario["analyzerBoundary"]["inputRoot"]
        inventory = source_inventory(args.database, analyzer_root)
        labels = load_object(args.labels)["flows"]
        allowed = {item["id"] for item in labels}
        trace = load_object(args.trace)
        provenance = trace.get("provenance")
        if not isinstance(provenance, dict):
            raise InvalidResult("generated model trace lacks exact producer provenance")
        off = observed_labels(load_object(args.off_result), allowed)
        on = observed_labels(load_object(args.on_result), allowed)
        off_result = build_result(args.scenario, args.labels, args.query, versions, inventory, provenance, off, False)
        on_result = build_result(args.scenario, args.labels, args.query, versions, inventory, provenance, on, True)
        if off_result["counts"]["falseNegative"] < 1:
            raise InvalidResult("pack-off must retain a motivating false negative")
        if [flow["classification"] for flow in on_result["flows"]] != ["TN", "TP"]:
            raise InvalidResult("pack-on result does not exactly match shared positive and near-miss labels")
        args.output_dir.mkdir(parents=True, exist_ok=True)
        off_text = json.dumps(off_result, indent=2, sort_keys=True) + "\n"
        on_text = json.dumps(on_result, indent=2, sort_keys=True) + "\n"
        (args.output_dir / "pack-off.json").write_text(off_text, encoding="utf-8")
        (args.output_dir / "pack-on.json").write_text(on_text, encoding="utf-8")
    except (InvalidResult, KeyError, OSError, TypeError, zipfile.BadZipFile) as error:
        print(f"CodeQL result generation failed closed: {error}", file=sys.stderr)
        return 2
    print(f"wrote validated CodeQL pack-off and pack-on results to {args.output_dir}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
