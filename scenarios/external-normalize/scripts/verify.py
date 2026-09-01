#!/usr/bin/env python3
import hashlib
import json
import sys
import zipfile
from pathlib import Path


SCENARIO = Path(__file__).resolve().parent.parent


def fail(message):
    raise AssertionError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_identity(record, label):
    path = SCENARIO / record["path"]
    if not path.is_file():
        fail(f"{label} is missing: {record['path']}")
    actual = sha256(path)
    if actual != record["sha256"]:
        fail(f"{label} digest mismatch: expected {record['sha256']}, found {actual}")


def main():
    manifest = json.loads((SCENARIO / "scenario.json").read_text())
    if manifest["scenario"]["status"] != "blocked":
        fail("scenario must remain blocked until a generated pack is retained")

    check_identity(manifest["scenario"]["labels"], "labels")
    check_identity(manifest["sourceArtifact"], "audit source")
    check_identity(manifest["binaryArtifact"], "binary artifact")
    check_identity(manifest["applicationArtifact"], "application source")
    check_identity(manifest["producerInput"], "Bifrost producer input")

    build_script = SCENARIO / manifest["build"]["script"]
    if sha256(build_script) != manifest["build"]["scriptSha256"]:
        fail("build script digest mismatch")

    boundary = manifest["analyzerBoundary"]
    input_root = (SCENARIO / boundary["inputRoot"]).resolve()
    included = sorted(
        str(path.relative_to(SCENARIO))
        for path in input_root.rglob("*")
        if path.is_file()
    )
    if included != sorted(boundary["includedPaths"]):
        fail(f"analyzer input inventory mismatch: {included}")
    for excluded in boundary["excludedRoots"]:
        excluded_root = (SCENARIO / excluded).resolve()
        if excluded_root == input_root or input_root in excluded_root.parents:
            fail(f"excluded root enters analyzer input: {excluded}")

    with zipfile.ZipFile(SCENARIO / manifest["binaryArtifact"]["path"]) as jar:
        names = jar.namelist()
        expected_class = "ai/brokk/csmi/demo/ExternalNormalizer.class"
        if expected_class not in names:
            fail(f"opaque JAR is missing {expected_class}")
        leaked = [name for name in names if name.endswith(".java") or "audit-source" in name]
        if leaked:
            fail(f"opaque JAR leaks source paths: {leaked}")

    labels = json.loads((SCENARIO / "labels.json").read_text())
    expectations = {flow["id"]: flow["expected"] for flow in labels["flows"]}
    if expectations != {
        "constant.input-to-return": False,
        "normalize.input-to-return": True,
    }:
        fail(f"unexpected label contract: {expectations}")

    producer = json.loads((SCENARIO / manifest["producerInput"]["path"]).read_text())
    summary_shards = [
        shard for shard in producer["shards"]
        if shard["payload"]["kind"] == "procedure_summaries"
    ]
    if len(summary_shards) != 1:
        fail("producer input must contain one procedure-summary shard")
    summaries = {
        summary["target"]["symbol"]: summary
        for summary in summary_shards[0]["payload"]["summaries"]
    }
    constant = summaries.get("constant")
    normalize = summaries.get("normalize")
    if not constant or constant.get("completeness") != "complete" or constant.get("transfers") != []:
        fail("constant must be a complete empty transfer set")
    expected_transfer = {
        "input": {"kind": "parameter", "ordinal": 0},
        "exit_kind": "normal",
        "output": {"kind": "normal_return"},
    }
    if not normalize or normalize.get("completeness") != "complete":
        fail("normalize summary must be complete")
    if normalize.get("transfers") != [expected_transfer]:
        fail("normalize must contain exactly parameter[0] -> normal return")

    pack = manifest["csmiPack"]
    if pack != {
        "status": "unavailable",
        "manifestPath": None,
        "packDigest": None,
        "resourceDigests": [],
        "blocker": {
            "code": "summary.empty",
            "path": "$.shards[1].payload.summaries[0]",
            "record": "BLOCKER.md",
        },
    }:
        fail("blocked pack identity changed unexpectedly")
    if (SCENARIO / "pack").exists():
        fail("no pack directory may be retained while export is blocked")

    print("verified deterministic external-normalize fixture and preserved CSMI export blocker")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, json.JSONDecodeError, zipfile.BadZipFile) as error:
        print(f"verification failed: {error}", file=sys.stderr)
        sys.exit(1)
