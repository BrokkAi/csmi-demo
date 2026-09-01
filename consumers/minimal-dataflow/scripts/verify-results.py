#!/usr/bin/env python3
"""Validate retained shared-scenario results without promoting blocked evidence."""

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent


def load(name):
    return json.loads((ROOT / "results" / name).read_text())


pack_off = load("pack-off.json")
assert pack_off["status"] == "complete"
assert pack_off["pack"] == {"state": "off"}
assert pack_off["scenario"]["id"] == "external-normalize"
assert pack_off["analysis"] == {
    "canonicalSha256": "8b4328015d707525bbb7de8f0e9685b6a8d6a9ad09fa112870a16305510dd381",
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
assert pack_on["status"] == "failed"
assert pack_on["pack"] == {"state": "on"}
assert pack_on["scenario"]["id"] == "external-normalize"
assert pack_on["artifact"] == pack_off["artifact"]
assert pack_on["failure"]["code"] == "pack-unavailable"
assert pack_on["failure"]["details"]["blocker"]["code"] == "summary.empty"
assert pack_on["failure"]["details"]["blocker"]["upstreamIssue"] == "https://github.com/BrokkAi/bifrost-dev/issues/2841"

print("verified retained pack-off result and typed pack-on blocker")
