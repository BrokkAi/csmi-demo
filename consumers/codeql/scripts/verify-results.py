#!/usr/bin/env python3
"""Validate retained CodeQL interoperability evidence without running CodeQL."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
results = {name: json.loads((ROOT / "results" / name).read_text()) for name in ("pack-off.json", "pack-on.json")}
off, on = results["pack-off.json"], results["pack-on.json"]

assert off["resultFormatVersion"] == "csmi-demo-consumer-result/1"
assert off["status"] == on["status"] == "complete"
assert off["consumer"] == on["consumer"] == {"name": "brokkai.csmi.codeql", "version": "2.26.4"}
assert off["analysis"] == on["analysis"]
assert off["scenario"] == on["scenario"]
assert off["artifact"] == on["artifact"]
assert off["pack"] == {"state": "off"}
assert on["pack"] == {"state": "on", "digest": {"algorithm": "sha-256", "value": "97873207ab6ffbc49bafbf4f2f0c08779081529ae1fedabaafb754f60f6fbb76"}}
assert off["provenance"] == {"records": []}
assert len(on["provenance"]["records"]) == 1
assert on["provenance"]["records"][0]["invocationId"] == "bifrost:f91ef53ee28893f23c3a5843d90abd3177bed9df"
assert [flow["classification"] for flow in off["flows"]] == ["TN", "FN"]
assert [flow["classification"] for flow in on["flows"]] == ["TN", "TP"]
assert off["counts"] == {"truePositive": 0, "falsePositive": 0, "falseNegative": 1, "trueNegative": 1}
assert on["counts"] == {"truePositive": 1, "falsePositive": 0, "falseNegative": 0, "trueNegative": 1}
assert off["metrics"]["precision"] == {"defined": False, "numerator": 0, "denominator": 0}
assert off["metrics"]["recall"]["value"] == 0.0
assert on["metrics"]["precision"]["value"] == on["metrics"]["recall"]["value"] == 1.0
assert off["environment"]["database"] == on["environment"]["database"]
assert off["environment"]["semanticToggle"] == "off"
assert on["environment"]["semanticToggle"] == "generated-csmi-model-pack"

print("verified retained CodeQL pack-off and pack-on interoperability results")
