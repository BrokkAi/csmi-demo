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


def expected_pack_metadata(scenario_dir: Path, manifest: dict[str, Any]) -> tuple[dict[str, str], dict[str, str], list[Any]]:
    pack = manifest["csmiPack"]
    pack_digest = pack["packDigest"]
    if pack.get("status") != "available" or pack_digest.get("algorithm") != "sha-256":
        raise ValueError("scenario does not declare an available sha-256 CSMI pack")
    manifest_path = (scenario_dir / pack["manifestPath"]).resolve()
    if scenario_dir.resolve() not in manifest_path.parents or digest(manifest_path) != pack_digest.get("value"):
        raise ValueError("scenario CSMI pack manifest identity mismatch")
    pack_manifest = load(manifest_path)
    semantic = [item for item in pack_manifest.get("resources", []) if item.get("role") == "semantic-document"]
    if len(semantic) != 1 or semantic[0].get("digest", {}).get("algorithm") != "sha-256":
        raise ValueError("scenario CSMI pack must contain one sha-256 semantic document")
    document_path = (manifest_path.parent / semantic[0]["path"]).resolve()
    if manifest_path.parent.resolve() not in document_path.parents:
        raise ValueError("scenario semantic document escapes its pack")
    document_digest = semantic[0]["digest"]
    if digest(document_path) != document_digest.get("value"):
        raise ValueError("scenario semantic document identity mismatch")
    document = load(document_path)
    records = document.get("provenanceRecords")
    if not isinstance(records, list):
        raise ValueError("scenario semantic document lacks provenance records")
    return pack_digest, document_digest, records


def metric(numerator: int, denominator: int) -> dict[str, Any]:
    result = {
        "defined": denominator != 0,
        "numerator": numerator,
        "denominator": denominator,
    }
    if denominator:
        result["value"] = numerator / denominator
    return result


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
                "name": item["name"],
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
        "resultFormatVersion": "csmi-demo-consumer-result/1",
        "status": "complete",
        "consumer": {
            "name": "io.joern.joern",
            "version": "4.0.592",
            "configurationPath": "consumers/joern/versions.json",
            "configurationSha256": digest(versions_path),
        },
        "scenario": {
            "id": manifest["scenario"]["id"],
            "version": manifest["scenario"]["version"],
            "manifest": {"path": "scenario.json", "sha256": digest(manifest_path)},
            "labels": {"path": manifest["scenario"]["labels"]["path"], "sha256": digest(labels_path)},
        },
        "artifact": {
            "purl": manifest["binaryArtifact"]["purl"],
            "digests": [{
                "algorithm": "sha-256",
                "coverage": manifest["binaryArtifact"]["digestCoverage"],
                "value": manifest["binaryArtifact"]["sha256"],
            }],
        },
        "analysis": {
            "formatVersion": "joern-cpg/4.0.592",
            "cpgSha256": digest(cpg),
            "methodEvidenceSha256": digest(methods),
            "externalMethods": external_methods,
            "packEnabled": pack_enabled,
        },
        "pack": {"state": "on" if pack_enabled else "off"},
        "provenance": {"records": []},
    }
    return record, labels["flows"], manifest


def completed(
    record: dict[str, Any],
    labels: list[dict[str, Any]],
    observations_path: Path,
    semantics_path: Path | None = None,
    scenario_dir: Path | None = None,
    manifest: dict[str, Any] | None = None,
) -> dict[str, Any]:
    observations = load(observations_path)
    if observations.get("joernVersion") != "4.0.592":
        raise ValueError("observation Joern version is not 4.0.592")
    if observations.get("packEnabled") != record["analysis"]["packEnabled"]:
        raise ValueError("observation pack state does not match requested result")
    observation_flows = observations.get("flows", [])
    if not isinstance(observation_flows, list) or any(not isinstance(item, dict) for item in observation_flows):
        raise ValueError("observations flows must be an array of objects")
    observation_ids = [item.get("id") for item in observation_flows]
    if len(observation_ids) != len(set(observation_ids)):
        raise ValueError("observations contain duplicate flow IDs")
    observed_by_id = {item["id"]: item for item in observation_flows}
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
        count_key, classification = (
            ("truePositive", "TP") if expected and observed else
            ("falseNegative", "FN") if expected else
            ("falsePositive", "FP") if observed else
            ("trueNegative", "TN")
        )
        counts[count_key] += 1
        flows.append({
            "id": label["id"],
            "expectedFlow": expected,
            "observedFlow": observed,
            "classification": classification,
            "pathCount": observation["pathCount"],
            "paths": observation["paths"],
        })
    tp = counts["truePositive"]
    fp = counts["falsePositive"]
    fn = counts["falseNegative"]
    if record["analysis"]["packEnabled"]:
        if semantics_path is None:
            raise ValueError("pack-on result requires adapter evidence")
        semantics = load(semantics_path)
        if semantics.get("outcome") != "applied":
            raise ValueError("pack-on adapter outcome is not applied")
        if scenario_dir is None or manifest is None:
            raise ValueError("pack-on result requires shared scenario pack metadata")
        pack_digest, document_digest, provenance_records = expected_pack_metadata(scenario_dir, manifest)
        if semantics.get("csmi", {}).get("packDigest") != pack_digest["value"]:
            raise ValueError("adapter pack digest does not match the shared scenario")
        if semantics.get("csmi", {}).get("semanticDocumentDigest") != document_digest["value"]:
            raise ValueError("adapter semantic document digest does not match the shared scenario")
        if semantics.get("csmi", {}).get("provenanceRecords") != provenance_records:
            raise ValueError("adapter provenance does not match the shared semantic document")
        record["pack"] = {
            "state": "on",
            "digest": pack_digest,
            "semanticDocumentDigest": document_digest,
        }
        record["analysis"]["semanticsSha256"] = digest(semantics_path)
        record["provenance"] = {"records": provenance_records}
    record["flows"] = flows
    record["counts"] = counts
    record["metrics"] = {"precision": metric(tp, tp + fp), "recall": metric(tp, tp + fn)}
    return record


def validate_pack_on(result: dict[str, Any], baseline_path: Path) -> None:
    if result["counts"]["falsePositive"] or result["counts"]["falseNegative"]:
        raise ValueError("pack-on result does not match every shared label")
    baseline = load(baseline_path)
    if baseline.get("status") != "complete" or baseline.get("pack", {}).get("state") != "off":
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
    args = parser.parse_args()
    try:
        record, labels, manifest = base_record(args.scenario, args.cpg, args.methods, args.pack_enabled)
        if args.observations is None:
            raise ValueError("--observations is required for a completed run")
        result = completed(record, labels, args.observations, args.semantics, args.scenario, manifest)
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
