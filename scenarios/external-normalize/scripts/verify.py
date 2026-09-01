#!/usr/bin/env python3
import hashlib
import json
import sys
import zipfile
from pathlib import Path


DEFAULT_SCENARIO = Path(__file__).resolve().parent.parent
PRODUCER_COMMIT = "f91ef53ee28893f23c3a5843d90abd3177bed9df"


def fail(message):
    raise AssertionError(message)


def sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def check_identity(scenario, record, label):
    path = scenario / record["path"]
    if not path.is_file():
        fail(f"{label} is missing: {record['path']}")
    actual = sha256(path)
    if actual != record["sha256"]:
        fail(f"{label} digest mismatch: expected {record['sha256']}, found {actual}")


def safe_resource(root, relative):
    path = (root / relative).resolve()
    if root.resolve() not in path.parents:
        fail(f"pack resource escapes its root: {relative}")
    return path


def callable_name(symbol):
    callables = [d for d in symbol["descriptors"] if d.get("role") == "callable"]
    if len(callables) != 1 or callables[0].get("name") not in {"constant", "normalize"}:
        fail(f"unexpected callable descriptor: {callables}")
    if callables[0].get("disambiguator") != "(java.lang.String)->java.lang.String":
        fail(f"unexpected callable disambiguator: {callables[0]}")
    prefix = [(d.get("role"), d.get("name")) for d in symbol["descriptors"][:-1]]
    if prefix != [
        ("namespace", "ai"),
        ("namespace", "brokk"),
        ("namespace", "csmi"),
        ("namespace", "demo"),
        ("type", "ExternalNormalizer"),
    ]:
        fail(f"unexpected callable structural identity: {prefix}")
    return callables[0]["name"]


def verify_pack(scenario, scenario_manifest):
    pack_record = scenario_manifest["csmiPack"]
    if pack_record["status"] != "available":
        fail("CSMI pack must be available")
    manifest_path = scenario / pack_record["manifestPath"]
    if not manifest_path.is_file():
        fail(f"CSMI manifest is missing: {pack_record['manifestPath']}")
    digest = pack_record["packDigest"]
    if digest["algorithm"] != "sha-256" or sha256(manifest_path) != digest["value"]:
        fail("CSMI manifest digest mismatch")

    pack_manifest = json.loads(manifest_path.read_bytes())
    if pack_manifest["documentType"] != "pack-manifest":
        fail("retained CSMI manifest has the wrong document type")
    if pack_manifest["assembler"] != {
        "identifier": "https://bifrost.brokk.ai/csmi-export",
        "version": f"0.1.0+{PRODUCER_COMMIT}",
    }:
        fail("CSMI assembler identity mismatch")

    resources = pack_manifest["resources"]
    recorded_resources = pack_record["resourceDigests"]
    if len(resources) != 1 or len(recorded_resources) != 1:
        fail("pack must contain exactly one semantic-document resource")
    resource = resources[0]
    if recorded_resources[0] != {
        "path": f"pack/{resource['path']}",
        "mediaType": resource["mediaType"],
        "size": resource["size"],
        "algorithm": resource["digest"]["algorithm"],
        "value": resource["digest"]["value"],
    }:
        fail("scenario and manifest resource identities disagree")
    if resource["role"] != "semantic-document" or resource["mediaType"] != "application/vnd.csmi.semantic-model.v0.1+json":
        fail("pack resource has the wrong role or media type")
    resource_path = safe_resource(manifest_path.parent, resource["path"])
    if not resource_path.is_file() or resource_path.stat().st_size != resource["size"]:
        fail("pack resource is missing or has the wrong size")
    if resource["digest"]["algorithm"] != "sha-256" or sha256(resource_path) != resource["digest"]["value"]:
        fail("pack resource digest mismatch")

    document = json.loads(resource_path.read_bytes())
    if document["documentType"] != "semantic-document":
        fail("pack resource has the wrong document type")
    if document["semanticModelVersion"] != "0.1" or document["serializationVersion"] != "0.1-json":
        fail("pack resource has the wrong CSMI version")
    provenance = document["provenanceRecords"]
    if len(provenance) != 1 or provenance[0]["invocationId"] != f"bifrost:{PRODUCER_COMMIT}":
        fail("pack producer revision mismatch")
    if provenance[0]["producer"] != {
        "identifier": "https://bifrost.brokk.ai/semantic-pack-producer",
        "version": f"0.10.7+{PRODUCER_COMMIT}",
    }:
        fail("semantic model producer identity mismatch")

    models = document["semanticModels"]
    if len(models) != 1:
        fail("pack must contain exactly one semantic model")
    model = models[0]
    binary = scenario_manifest["binaryArtifact"]
    exact_digest = {
        "algorithm": "sha-256",
        "coverage": binary["digestCoverage"],
        "value": binary["sha256"],
    }
    selector = [{"digests": [exact_digest], "purl": binary["purl"]}]
    if model["artifactSelectors"] != selector:
        fail("pack does not apply to the exact retained JAR identity")
    if provenance[0]["inputs"] != [{
        "digest": exact_digest,
        "purl": binary["purl"],
        "role": "target-artifact",
    }]:
        fail("producer provenance does not identify the exact retained JAR")

    callables = {}
    for symbol in model["symbols"]:
        if any(d.get("role") == "callable" for d in symbol["descriptors"]):
            callables[callable_name(symbol)] = symbol["id"]
    if set(callables) != {"constant", "normalize"}:
        fail(f"unexpected callable symbols: {sorted(callables)}")

    summaries = {summary["callable"]: summary for summary in model["procedureSummaries"]}
    if summaries.get(callables["constant"]) != {
        "callable": callables["constant"],
        "transfers": [],
    }:
        fail("constant must have an explicit empty transfer set")
    transfer = {
        "destination": {"root": {"phase": "output", "position": 0, "role": "result"}},
        "source": {"root": {"phase": "input", "position": 0, "role": "parameter"}},
    }
    if summaries.get(callables["normalize"]) != {
        "callable": callables["normalize"],
        "transfers": [transfer],
    }:
        fail("normalize must contain exactly parameter[0] -> normal result[0]")
    if set(summaries) != set(callables.values()):
        fail("procedure-summary inventory does not match callable inventory")

    complete = {
        statement["scope"]["callable"]
        for statement in model["completenessStatements"]
        if statement.get("family") == "procedure-summaries"
        and statement.get("status") == "complete"
        and set(statement.get("scope", {})) == {"callable"}
    }
    if complete != set(callables.values()):
        fail("both callables require callable-scoped complete procedure-summary coverage")


def main():
    if len(sys.argv) > 2:
        fail("usage: verify.py [SCENARIO_ROOT]")
    scenario = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else DEFAULT_SCENARIO
    manifest = json.loads((scenario / "scenario.json").read_text())
    if manifest["scenario"]["status"] != "materialized":
        fail("scenario must be materialized")

    check_identity(scenario, manifest["scenario"]["labels"], "labels")
    check_identity(scenario, manifest["sourceArtifact"], "audit source")
    check_identity(scenario, manifest["binaryArtifact"], "binary artifact")
    check_identity(scenario, manifest["applicationArtifact"], "application source")
    check_identity(scenario, manifest["producerInput"], "Bifrost producer input")
    if sha256(scenario / manifest["build"]["script"]) != manifest["build"]["scriptSha256"]:
        fail("build script digest mismatch")

    boundary = manifest["analyzerBoundary"]
    input_root = (scenario / boundary["inputRoot"]).resolve()
    included = sorted(str(path.relative_to(scenario)) for path in input_root.rglob("*") if path.is_file())
    if included != sorted(boundary["includedPaths"]):
        fail(f"analyzer input inventory mismatch: {included}")
    for excluded in boundary["excludedRoots"]:
        excluded_root = (scenario / excluded).resolve()
        if excluded_root == input_root or input_root in excluded_root.parents:
            fail(f"excluded root enters analyzer input: {excluded}")

    with zipfile.ZipFile(scenario / manifest["binaryArtifact"]["path"]) as jar:
        names = jar.namelist()
        expected_class = "ai/brokk/csmi/demo/ExternalNormalizer.class"
        if expected_class not in names:
            fail(f"opaque JAR is missing {expected_class}")
        leaked = [name for name in names if name.endswith(".java") or "audit-source" in name]
        if leaked:
            fail(f"opaque JAR leaks source paths: {leaked}")

    labels = json.loads((scenario / "labels.json").read_text())
    expectations = {flow["id"]: flow["expected"] for flow in labels["flows"]}
    if expectations != {"constant.input-to-return": False, "normalize.input-to-return": True}:
        fail(f"unexpected label contract: {expectations}")

    producer = json.loads((scenario / manifest["producerInput"]["path"]).read_text())
    if producer["provenance"]["revision"] != f"bifrost:{PRODUCER_COMMIT}":
        fail("authored producer input revision mismatch")
    shards = [s for s in producer["shards"] if s["payload"]["kind"] == "procedure_summaries"]
    if len(shards) != 1:
        fail("producer input must contain one procedure-summary shard")
    authored = {s["target"]["symbol"]: s for s in shards[0]["payload"]["summaries"]}
    if authored["constant"].get("completeness") != "complete" or authored["constant"].get("transfers") != []:
        fail("authored constant summary must be a complete empty transfer set")
    expected = {
        "input": {"kind": "parameter", "ordinal": 0},
        "exit_kind": "normal",
        "output": {"kind": "normal_return"},
    }
    if authored["normalize"].get("completeness") != "complete" or authored["normalize"].get("transfers") != [expected]:
        fail("authored normalize summary must contain parameter[0] -> normal return")

    producer_record = manifest["csmiProducer"]
    if producer_record["commit"] != PRODUCER_COMMIT or producer_record["api"] != "export_authored_csmi_pack":
        fail("scenario CSMI producer identity mismatch")
    verify_pack(scenario, manifest)
    print("verified deterministic external-normalize fixture and exact Bifrost-generated CSMI pack")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, IndexError, json.JSONDecodeError, OSError, zipfile.BadZipFile) as error:
        print(f"verification failed: {error}", file=sys.stderr)
        sys.exit(1)
