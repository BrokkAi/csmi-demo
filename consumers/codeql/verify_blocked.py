#!/usr/bin/env python3
"""Validate and report the CodeQL diagnostic while the CSMI pack is unavailable."""

from __future__ import annotations

import argparse
import json
import sys
import zipfile
from pathlib import Path


class InvalidDiagnostic(ValueError):
    pass


def load_object(path: Path) -> dict:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        raise InvalidDiagnostic(f"cannot read valid JSON from {path}: {error}") from error
    if not isinstance(value, dict):
        raise InvalidDiagnostic(f"{path} must contain a JSON object")
    return value


def load_versions(path: Path) -> dict[str, str]:
    values = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        if not line or line.startswith("#"):
            continue
        key, separator, value = line.partition("=")
        if not separator or not key or not value or key in values:
            raise InvalidDiagnostic(f"invalid versions entry: {line!r}")
        values[key] = value
    required = {
        "CODEQL_CLI_VERSION",
        "CODEQL_JAVA_ALL_VERSION",
        "CODEQL_JAVA_ALL_SHA",
        "CODEQL_LINUX_BUNDLE_SHA256",
    }
    if values.keys() != required:
        raise InvalidDiagnostic(f"versions.env keys must be exactly {sorted(required)}")
    return values


def source_inventory(database: Path, analyzer_root: Path) -> list[str]:
    archive = database / "src.zip"
    try:
        with zipfile.ZipFile(archive) as source_zip:
            names = [name for name in source_zip.namelist() if not name.endswith("/")]
    except (OSError, zipfile.BadZipFile) as error:
        raise InvalidDiagnostic(f"cannot inspect CodeQL source archive {archive}: {error}") from error

    expected_suffix = (
        "scenarios/external-normalize/analyzer-input/src/main/java/"
        "ai/brokk/csmi/demo/ScenarioApplication.java"
    )
    if len(names) != 1 or not names[0].endswith(expected_suffix):
        raise InvalidDiagnostic(f"CodeQL source archive crosses the analyzer boundary: {names}")
    if "audit-source" in names[0] or "producer" in names[0]:
        raise InvalidDiagnostic(f"excluded source found in CodeQL database: {names[0]}")

    database_metadata = (database / "codeql-database.yml").read_text(encoding="utf-8")
    expected_prefix = f"sourceLocationPrefix: {analyzer_root.resolve()}"
    if expected_prefix not in database_metadata.splitlines():
        raise InvalidDiagnostic("CodeQL database sourceLocationPrefix is not the exact analyzer input root")
    return [expected_suffix]


def verify_java_pack(path: Path, versions: dict[str, str]) -> None:
    try:
        metadata = path.read_text(encoding="utf-8").splitlines()
    except OSError as error:
        raise InvalidDiagnostic(f"cannot read resolved java-all metadata {path}: {error}") from error
    required_lines = {
        "name: codeql/java-all",
        f"version: {versions['CODEQL_JAVA_ALL_VERSION']}",
        f"  sha: {versions['CODEQL_JAVA_ALL_SHA']}",
    }
    missing = sorted(required_lines - set(metadata))
    if missing:
        raise InvalidDiagnostic(f"resolved java-all identity mismatch in {path}: missing {missing}")


def observed_labels(result: dict) -> list[str]:
    result_set = result.get("#select")
    if not isinstance(result_set, dict) or not isinstance(result_set.get("tuples"), list):
        raise InvalidDiagnostic("decoded BQRS must contain a #select tuple array")
    labels = []
    for row in result_set["tuples"]:
        if not isinstance(row, list) or len(row) != 1 or not isinstance(row[0], str):
            raise InvalidDiagnostic(f"invalid CodeQL result row: {row!r}")
        labels.append(row[0])
    if len(labels) != len(set(labels)):
        raise InvalidDiagnostic("CodeQL query emitted duplicate labels")
    return sorted(labels)


def build_report(
    scenario: dict,
    versions: dict[str, str],
    inventory: list[str],
    labels: list[str],
) -> dict:
    pack = scenario.get("csmiPack", {})
    blocker = pack.get("blocker", {})
    if scenario.get("scenario", {}).get("status") != "blocked" or pack.get("status") != "unavailable":
        raise InvalidDiagnostic("scenario is no longer in the expected typed blocked state")
    if (
        blocker.get("code") != "summary.empty"
        or blocker.get("path") != "$.shards[1].payload.summaries[0]"
        or blocker.get("upstreamIssue") != "https://github.com/BrokkAi/bifrost-dev/issues/2841"
    ):
        raise InvalidDiagnostic("scenario blocker identity changed")

    scenario_identity = scenario["scenario"]
    binary = scenario["binaryArtifact"]
    return {
        "schemaVersion": 1,
        "status": "blocked",
        "consumer": {
            "name": "CodeQL",
            "cliVersion": versions["CODEQL_CLI_VERSION"],
            "linuxBundleSha256": versions["CODEQL_LINUX_BUNDLE_SHA256"],
            "queryPack": "brokkai/csmi-demo-codeql-query@0.0.0",
            "javaAll": {
                "version": versions["CODEQL_JAVA_ALL_VERSION"],
                "sha": versions["CODEQL_JAVA_ALL_SHA"],
            },
        },
        "scenario": {
            "id": scenario_identity["id"],
            "version": scenario_identity["version"],
            "labelsSha256": scenario_identity["labels"]["sha256"],
            "artifact": {
                "purl": binary["purl"],
                "path": binary["path"],
                "digestCoverage": binary["digestCoverage"],
                "sha256": binary["sha256"],
            },
        },
        "database": {
            "builtOnce": True,
            "inputRoot": scenario["analyzerBoundary"]["inputRoot"],
            "sourceInventory": inventory,
            "excludedRoots": scenario["analyzerBoundary"]["excludedRoots"],
        },
        "csmiPack": {
            "status": "unavailable",
            "manifestPath": None,
            "packDigest": None,
            "blocker": blocker,
        },
        "packOffDiagnostic": {
            "status": "diagnostic-only",
            "packEnabled": False,
            "observedLabels": labels,
            "retainedInteroperabilityEvidence": False,
        },
        "packOn": {
            "status": "blocked",
            "packEnabled": True,
            "result": None,
        },
        "comparison": {
            "status": "not-run",
            "counts": None,
            "precision": None,
            "recall": None,
        },
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--versions", type=Path, required=True)
    parser.add_argument("--database", type=Path, required=True)
    parser.add_argument("--java-pack", type=Path, required=True)
    parser.add_argument("--result", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        scenario = load_object(args.scenario)
        versions = load_versions(args.versions)
        verify_java_pack(args.java_pack, versions)
        analyzer_root = args.scenario.parent / scenario["analyzerBoundary"]["inputRoot"]
        inventory = source_inventory(args.database, analyzer_root)
        labels = observed_labels(load_object(args.result))
        report = build_report(scenario, versions, inventory, labels)
        args.output.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    except (InvalidDiagnostic, KeyError, OSError) as error:
        print(f"CodeQL blocked diagnostic failed closed: {error}", file=sys.stderr)
        return 2
    print(f"wrote typed blocked CodeQL diagnostic to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
