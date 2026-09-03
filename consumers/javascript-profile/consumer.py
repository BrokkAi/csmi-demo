#!/usr/bin/env python3
"""Small fail-closed consumer for the CSMI JavaScript/Node identity profile."""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path


PROFILE = ("csmi.javascript-typescript", "0.1.0")
PROFILE_SCHEMA = "https://csmi.brokk.ai/schema/profiles/javascript-typescript/0.1/schema.json"


class UnsupportedModel(ValueError):
    pass


def canonical_digest(value: object) -> str:
    encoded = json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    return hashlib.sha256(encoded).hexdigest()


def load(path: Path) -> object:
    return json.loads(path.read_text(encoding="utf-8"))


def interpret(pack: dict, cases: dict, enabled: bool) -> dict:
    model = pack["semanticModels"][0]
    uses = {
        (use.get("identifier"), use.get("version")): use
        for use in model.get("vocabularyUses", [])
    }
    use = uses.get(PROFILE)
    if use is None or use.get("requirement") != "required" or use.get("schema") != PROFILE_SCHEMA:
        raise UnsupportedModel("unsupported-required-profile")

    selector = model["artifactSelectors"][0]
    candidate = cases["candidateArtifact"]
    digests = selector.get("digests", [])
    if selector.get("purl") != candidate.get("purl") or not any(
        item.get("algorithm") == "sha-256"
        and item.get("coverage") == "official-distribution-archive"
        and item.get("value") == candidate.get("sha256")
        for item in digests
    ):
        raise UnsupportedModel("artifact-indeterminate-or-not-matched")

    symbol = model["symbols"][0]
    descriptors = symbol.get("descriptors", [])
    extension = symbol.get("extensions", [])[0]
    payload = extension.get("payload", {})
    if (
        symbol.get("scheme") != "csmi.javascript-runtime"
        or symbol.get("schemeVersion") != "0.1.0"
        or len(descriptors) != 2
        or descriptors[0] != {"role": "namespace", "name": "node:child_process"}
        or descriptors[1] != {"role": "callable", "name": "execSync"}
        or (extension.get("vocabulary"), extension.get("version")) != PROFILE
        or payload.get("kind") != "module-binding"
        or payload.get("canonicalModule") != descriptors[0]["name"]
        or payload.get("exportName") != descriptors[1]["name"]
    ):
        raise UnsupportedModel("identity-or-binding-mismatch")

    accepted = {
        (item["form"], item["value"])
        for item in payload.get("acceptedSpecifiers", [])
    }
    symbol_identity = {
        "artifactSelector": selector,
        "scheme": symbol["scheme"],
        "schemeVersion": symbol["schemeVersion"],
        "stability": symbol["stability"],
        "descriptors": descriptors,
    }
    outcomes = []
    for case in cases["cases"]:
        observed = bool(
            enabled
            and case.get("artifactPurl") == selector["purl"]
            and case.get("exportName") == payload["exportName"]
            and (case.get("form"), case.get("specifier")) in accepted
        )
        outcomes.append({
            "id": case["id"],
            "expected": case["expectedMatch"],
            "observed": observed,
            "resolvedSymbol": symbol_identity if observed else None,
        })
    tp = sum(item["expected"] and item["observed"] for item in outcomes)
    fp = sum(not item["expected"] and item["observed"] for item in outcomes)
    fn = sum(item["expected"] and not item["observed"] for item in outcomes)
    tn = sum(not item["expected"] and not item["observed"] for item in outcomes)
    return {
        "resultFormatVersion": "csmi-demo-consumer-result/1",
        "status": "complete",
        "consumer": {"identifier": "brokkai.csmi.javascript-profile", "version": "0.1.0"},
        "scenario": cases["scenario"],
        "pack": {"state": "on" if enabled else "off", "sha256": canonical_digest(pack)},
        "candidateArtifact": candidate,
        "cases": outcomes,
        "counts": {"truePositive": tp, "falsePositive": fp, "falseNegative": fn, "trueNegative": tn},
        "precision": {"defined": tp + fp > 0, "numerator": tp, "denominator": tp + fp},
        "recall": {"defined": tp + fn > 0, "numerator": tp, "denominator": tp + fn},
    }


def verify_archive(cases: dict, archive: Path) -> None:
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != cases["candidateArtifact"]["sha256"]:
        raise UnsupportedModel("official-archive-digest-mismatch")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--pack", type=Path, required=True)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--mode", choices=("off", "on"), required=True)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--archive", type=Path)
    args = parser.parse_args()
    pack, cases = load(args.pack), load(args.cases)
    if args.archive:
        verify_archive(cases, args.archive)
    result = interpret(pack, cases, args.mode == "on")
    rendered = json.dumps(result, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(rendered, encoding="utf-8")
    else:
        print(rendered, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
