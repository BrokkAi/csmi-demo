#!/usr/bin/env python3
"""Validate Joern observations against the shared consumer evidence contract."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain an object")
    return value


def metric(numerator: int, denominator: int) -> dict[str, Any]:
    return {
        "numerator": numerator,
        "denominator": denominator,
        "value": numerator / denominator if denominator else None,
        "status": "defined" if denominator else "undefined",
    }


def base_record(scenario_dir: Path, cpg: Path, methods: Path, pack_enabled: bool) -> tuple[dict[str, Any], list[dict[str, Any]], dict[str, Any]]:
    manifest_path = scenario_dir / "scenario.json"
    manifest = load(manifest_path)
    labels_path = scenario_dir / manifest["scenario"]["labels"]["path"]
    if digest(labels_path) != manifest["scenario"]["labels"]["sha256"]:
        raise ValueError("shared labels digest does not match scenario.json")
    labels = load(labels_path)
    method_records = json.loads(methods.read_text(encoding="utf-8"))
    if not isinstance(method_records, list):
        raise ValueError("Joern method evidence must be an array")
    external_methods = sorted(
        (
            {
                "fullName": item["fullName"],
                "signature": item["signature"],
                "hasReceiver": item["hasReceiver"],
                "parameterCount": item["parameterCount"],
            }
            for item in method_records
            if isinstance(item, dict) and item.get("isExternal") is True
        ),
        key=lambda item: item["fullName"],
    )
    versions_path = Path(__file__).with_name("versions.json")
    record = {
        "schemaVersion": 1,
        "consumer": {
            "name": "joern",
            "version": "4.0.592",
            "configurationPath": "consumers/joern/versions.json",
            "configurationSha256": digest(versions_path),
        },
        "scenario": {
            "id": manifest["scenario"]["id"],
            "version": manifest["scenario"]["version"],
            "manifestSha256": digest(manifest_path),
            "labelsSha256": digest(labels_path),
            "artifact": {
                "purl": manifest["binaryArtifact"]["purl"],
                "sha256": manifest["binaryArtifact"]["sha256"],
                "digestCoverage": manifest["binaryArtifact"]["digestCoverage"],
            },
        },
        "analysis": {
            "cpgSha256": digest(cpg),
            "methodEvidenceSha256": digest(methods),
            "externalMethods": external_methods,
            "packEnabled": pack_enabled,
        },
    }
    return record, labels["flows"], manifest


def completed(record: dict[str, Any], labels: list[dict[str, Any]], observations_path: Path, semantics_path: Path | None = None) -> dict[str, Any]:
    observations = load(observations_path)
    if observations.get("joernVersion") != "4.0.592":
        raise ValueError("observation Joern version is not 4.0.592")
    if observations.get("packEnabled") != record["analysis"]["packEnabled"]:
        raise ValueError("observation pack state does not match requested result")
    observed_by_id = {item["id"]: item for item in observations.get("flows", [])}
    if set(observed_by_id) != {item["id"] for item in labels}:
        raise ValueError("observations do not match the complete shared label set")

    counts = {name: 0 for name in ("truePositive", "falsePositive", "falseNegative", "trueNegative")}
    flows: list[dict[str, Any]] = []
    for label in labels:
        observation = observed_by_id[label["id"]]
        expected = label["expected"]
        observed = observation["observed"]
        if not isinstance(observed, bool):
            raise ValueError(f"flow {label['id']} has a non-boolean observation")
        classification = (
            "truePositive" if expected and observed else
            "falseNegative" if expected else
            "falsePositive" if observed else
            "trueNegative"
        )
        counts[classification] += 1
        flows.append({
            "id": label["id"],
            "callable": label["callable"],
            "expected": expected,
            "observed": observed,
            "classification": classification,
            "pathCount": observation["pathCount"],
            "paths": observation["paths"],
        })
    tp = counts["truePositive"]
    fp = counts["falsePositive"]
    fn = counts["falseNegative"]
    record["run"] = {"status": "complete"}
    if record["analysis"]["packEnabled"]:
        if semantics_path is None:
            raise ValueError("pack-on result requires adapter evidence")
        semantics = load(semantics_path)
        if semantics.get("outcome") != "applied":
            raise ValueError("pack-on adapter outcome is not applied")
        record["csmiPack"] = {
            "status": "applied",
            "packDigest": semantics["csmi"]["packDigest"],
            "semanticDocumentDigest": semantics["csmi"]["semanticDocumentDigest"],
        }
    record["flows"] = flows
    record["counts"] = counts
    record["metrics"] = {"precision": metric(tp, tp + fp), "recall": metric(tp, tp + fn)}
    return record


def unavailable(record: dict[str, Any], labels: list[dict[str, Any]], manifest: dict[str, Any]) -> dict[str, Any]:
    pack = manifest["csmiPack"]
    if pack.get("status") != "unavailable" or pack.get("packDigest") is not None:
        raise ValueError("scenario does not declare the CSMI pack unavailable")
    record["run"] = {"status": "unavailable", "diagnostic": pack["blocker"]}
    record["csmiPack"] = {"status": "unavailable", "packDigest": None}
    record["flows"] = [
        {
            "id": label["id"],
            "callable": label["callable"],
            "expected": label["expected"],
            "observed": None,
            "classification": "unresolved",
        }
        for label in labels
    ]
    record["counts"] = None
    record["metrics"] = None
    return record


def validate_pack_on(result: dict[str, Any], baseline_path: Path) -> None:
    if result["counts"]["falsePositive"] or result["counts"]["falseNegative"]:
        raise ValueError("pack-on result does not match every shared label")
    baseline = load(baseline_path)
    if baseline.get("run", {}).get("status") != "complete" or baseline.get("analysis", {}).get("packEnabled") is not False:
        raise ValueError("pack-off baseline is not a complete disabled-pack run")
    for field in ("cpgSha256", "methodEvidenceSha256"):
        if baseline["analysis"].get(field) != result["analysis"].get(field):
            raise ValueError(f"pack-off/on {field} differs")
    if baseline.get("scenario") != result.get("scenario"):
        raise ValueError("pack-off/on scenario identity differs")
    errors = baseline.get("counts", {}).get("falsePositive", 0) + baseline.get("counts", {}).get("falseNegative", 0)
    if errors < 1:
        raise ValueError("pack-off baseline has no false positive or false negative delta")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--scenario", type=Path, required=True)
    parser.add_argument("--cpg", type=Path, required=True)
    parser.add_argument("--methods", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--observations", type=Path)
    parser.add_argument("--semantics", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--pack-enabled", action="store_true")
    parser.add_argument("--unavailable", action="store_true")
    args = parser.parse_args()
    try:
        record, labels, manifest = base_record(args.scenario, args.cpg, args.methods, args.pack_enabled)
        if args.unavailable:
            result = unavailable(record, labels, manifest)
        else:
            if args.observations is None:
                raise ValueError("--observations is required for a completed run")
            result = completed(record, labels, args.observations, args.semantics)
            if args.pack_enabled:
                if args.baseline is None:
                    raise ValueError("pack-on result requires --baseline")
                validate_pack_on(result, args.baseline)
        args.output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    except (KeyError, OSError, ValueError, json.JSONDecodeError) as error:
        print(f"result validation failed: {error}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
