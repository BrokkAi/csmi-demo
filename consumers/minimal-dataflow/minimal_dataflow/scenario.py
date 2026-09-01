"""Adapter for the shared external-normalize scenario contract."""

from __future__ import annotations

import hashlib
from pathlib import Path
from typing import Any

from .consumer import ConsumerFailure, load_json


def _sha256(path: Path) -> str:
    try:
        return hashlib.sha256(path.read_bytes()).hexdigest()
    except OSError as exc:
        raise ConsumerFailure("malformed-input", "shared scenario asset is unavailable", path=str(path), error=str(exc)) from exc


def load_scenario(root: Path) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any], dict[str, Any]]:
    manifest = load_json(root / "scenario.json")
    if not isinstance(manifest, dict) or manifest.get("schemaVersion") != 1:
        raise ConsumerFailure("malformed-input", "unsupported shared scenario manifest")
    scenario = manifest.get("scenario")
    binary = manifest.get("binaryArtifact")
    boundary = manifest.get("analyzerBoundary")
    pack = manifest.get("csmiPack")
    if not all(isinstance(value, dict) for value in (scenario, binary, boundary, pack)):
        raise ConsumerFailure("malformed-input", "shared scenario manifest lacks required identity sections")

    labels_record = scenario.get("labels")
    if not isinstance(labels_record, dict) or set(labels_record) != {"path", "sha256"}:
        raise ConsumerFailure("malformed-input", "shared scenario labels identity is malformed")
    labels_path = root / labels_record["path"]
    if _sha256(labels_path) != labels_record["sha256"]:
        raise ConsumerFailure("integrity-failure", "shared labels digest mismatch", path=str(labels_path))
    labels_source = load_json(labels_path)
    if not isinstance(labels_source, dict) or labels_source.get("schemaVersion") != 1 or labels_source.get("scenario") != scenario.get("id"):
        raise ConsumerFailure("malformed-input", "unsupported shared labels document")
    flows = labels_source.get("flows")
    if not isinstance(flows, list):
        raise ConsumerFailure("malformed-input", "shared labels flows must be an array")
    labels = {"formatVersion": "csmi-demo-labels/1", "flows": []}
    for flow in flows:
        if not isinstance(flow, dict) or not isinstance(flow.get("id"), str) or not isinstance(flow.get("expected"), bool):
            raise ConsumerFailure("malformed-input", "shared flow label is malformed")
        labels["flows"].append({"id": flow["id"], "expectedFlow": flow["expected"]})

    binary_path = root / binary.get("path", "")
    if _sha256(binary_path) != binary.get("sha256"):
        raise ConsumerFailure("integrity-failure", "shared binary digest mismatch", path=str(binary_path))
    included = boundary.get("includedPaths")
    if not isinstance(included, list) or binary.get("path") not in included:
        raise ConsumerFailure("malformed-input", "binary is outside the declared analyzer boundary")
    artifact = {
        "purl": binary.get("purl"),
        "digests": [{"algorithm": "sha-256", "coverage": binary.get("digestCoverage"), "value": binary.get("sha256")}],
    }
    scenario_identity = {
        "id": scenario.get("id"),
        "version": scenario.get("version"),
        "manifest": {"path": "scenario.json", "sha256": _sha256(root / "scenario.json")},
        "labels": labels_record,
    }
    return artifact, labels, scenario_identity, pack


def require_pack_available(pack_record: dict[str, Any]) -> tuple[str, str]:
    if pack_record.get("status") != "available":
        blocker = pack_record.get("blocker") if isinstance(pack_record.get("blocker"), dict) else {}
        raise ConsumerFailure(
            "pack-unavailable",
            "the shared scenario has no verified Bifrost-generated CSMI pack",
            blocker=blocker,
        )
    path = pack_record.get("manifestPath")
    digest = pack_record.get("packDigest")
    if not isinstance(path, str) or not isinstance(digest, dict) or digest.get("algorithm") != "sha-256" or not isinstance(digest.get("value"), str):
        raise ConsumerFailure("malformed-input", "shared pack identity is malformed")
    return path, digest["value"]
