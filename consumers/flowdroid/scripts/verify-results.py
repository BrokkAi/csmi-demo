#!/usr/bin/env python3
"""Validate retained FlowDroid pack-off/on interoperability evidence."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load(name):
    return json.loads((ROOT / "results" / name).read_text())


off = load("pack-off.json")
on = load("pack-on.json")
assert off["resultFormatVersion"] == on["resultFormatVersion"] == "csmi-demo-consumer-result/1"
assert off["status"] == on["status"] == "complete"
assert off["consumer"] == on["consumer"] == {"name": "brokkai.csmi.flowdroid", "version": "0.1.0"}
assert off["analysis"] == on["analysis"]
assert off["scenario"] == on["scenario"]
assert off["artifact"] == on["artifact"]
assert off["pack"] == {"state": "off"}
assert on["pack"] == {
    "state": "on",
    "digest": {"algorithm": "sha-256", "value": "97873207ab6ffbc49bafbf4f2f0c08779081529ae1fedabaafb754f60f6fbb76"},
    "semanticDocumentSha256": "ffff74e5ddb9dfa6f66c3b5c6651d2259fffc43db5549f3ffff1eb2de68fb136",
}
assert off["counts"] == {"truePositive": 0, "trueNegative": 1, "falsePositive": 0, "falseNegative": 1}
assert on["counts"] == {"truePositive": 1, "trueNegative": 1, "falsePositive": 0, "falseNegative": 0}
assert [flow["classification"] for flow in off["flows"]] == ["TN", "FN"]
assert [flow["classification"] for flow in on["flows"]] == ["TN", "TP"]
assert off["metrics"]["precision"] == {"defined": False, "numerator": 0, "denominator": 0}
assert on["metrics"]["precision"] == {"defined": True, "numerator": 1, "denominator": 1, "value": 1.0}
assert on["metrics"]["recall"] == {"defined": True, "numerator": 1, "denominator": 1, "value": 1.0}
assert off["provenance"] == {"records": []}
assert len(on["provenance"]["records"]) == 1
record = on["provenance"]["records"][0]
assert record["invocationId"] == "bifrost:f91ef53ee28893f23c3a5843d90abd3177bed9df"
assert record["producer"] == {
    "identifier": "https://bifrost.brokk.ai/semantic-pack-producer",
    "version": "0.10.7+f91ef53ee28893f23c3a5843d90abd3177bed9df",
}
assert off["termination"]["status"] == on["termination"]["status"] == "success"
assert off["termination"]["externalClassExcludedWithoutBodies"] is True
assert on["termination"]["externalClassExcludedWithoutBodies"] is True

print("verified retained FlowDroid pack-off and pack-on interoperability results")
