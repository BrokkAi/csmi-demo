#!/usr/bin/env python3
"""Validate retained shared-scenario interoperability results."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load(name):
    return json.loads((ROOT / "results" / name).read_text())


pack_off = load("pack-off.json")
assert pack_off["status"] == "complete"
assert pack_off["consumer"] == {"name": "brokkai.csmi.minimal-dataflow", "version": "0.1.0"}
assert pack_off["pack"] == {"state": "off"}
assert pack_off["scenario"]["id"] == "external-normalize"
assert pack_off["analysis"] == {
    "canonicalSha256": "82e3fb7bfc3b40a779a1762a907961431df7d7fd8c1af0215aa6cae9bcb129fb",
    "formatVersion": "minimal-dataflow-input/1",
}
assert pack_off["counts"] == {
    "falseNegative": 1,
    "falsePositive": 0,
    "trueNegative": 1,
    "truePositive": 0,
}
assert [flow["classification"] for flow in pack_off["flows"]] == ["TN", "FN"]
assert pack_off["metrics"]["precision"] == {
    "defined": False,
    "denominator": 0,
    "numerator": 0,
}

pack_on = load("pack-on.json")
assert pack_on["status"] == "complete"
assert pack_on["consumer"] == pack_off["consumer"]
assert pack_on["analysis"] == pack_off["analysis"]
assert pack_on["pack"] == {
    "state": "on",
    "digest": {
        "algorithm": "sha-256",
        "value": "97873207ab6ffbc49bafbf4f2f0c08779081529ae1fedabaafb754f60f6fbb76",
    },
}
assert pack_on["scenario"] == pack_off["scenario"]
assert pack_on["artifact"] == pack_off["artifact"]
assert pack_on["counts"] == {
    "falseNegative": 0,
    "falsePositive": 0,
    "trueNegative": 1,
    "truePositive": 1,
}
assert [flow["classification"] for flow in pack_on["flows"]] == ["TN", "TP"]
assert pack_on["metrics"]["precision"] == {
    "defined": True,
    "denominator": 1,
    "numerator": 1,
    "value": 1.0,
}
assert pack_on["metrics"]["recall"] == {
    "defined": True,
    "denominator": 1,
    "numerator": 1,
    "value": 1.0,
}
assert len(pack_on["provenance"]["records"]) == 1
producer_record = pack_on["provenance"]["records"][0]
assert producer_record["invocationId"] == "bifrost:f91ef53ee28893f23c3a5843d90abd3177bed9df"
assert producer_record["producer"] == {
    "identifier": "https://bifrost.brokk.ai/semantic-pack-producer",
    "version": "0.10.7+f91ef53ee28893f23c3a5843d90abd3177bed9df",
}
assert producer_record["inputs"] == [{
    "digest": pack_on["artifact"]["digests"][0],
    "purl": pack_on["artifact"]["purl"],
    "role": "target-artifact",
}]

print("verified retained pack-off and pack-on interoperability results")
