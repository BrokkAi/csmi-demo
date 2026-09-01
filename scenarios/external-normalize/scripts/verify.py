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
    if sha256(path) != record["sha256"]:
        fail(f"{label} digest mismatch")


def callable_name(symbol):
    descriptors = symbol["descriptors"]
    callable_parts = [part for part in descriptors if part.get("role") == "callable"]
    if len(callable_parts) != 1:
        fail("callable symbol must have one callable descriptor")
    callable_part = callable_parts[0]
    if callable_part.get("disambiguator") != "(java.lang.String)->java.lang.String":
        fail("callable descriptor has the wrong JVM disambiguator")
    structural_prefix = [(part.get("role"), part.get("name")) for part in descriptors[:-1]]
    if structural_prefix != [
        ("namespace", "ai"),
        ("namespace", "brokk"),
        ("namespace", "csmi"),
        ("namespace", "demo"),
        ("type", "ExternalNormalizer"),
    ]:
        fail("callable descriptor has the wrong structural identity")
    return callable_part["name"]


def verify_pack(scenario, scenario_record):
    pack_record = scenario_record["csmiPack"]
    if pack_record["status"] != "available":
        fail("CSMI pack must be available")
    manifest_path = scenario / pack_record["manifestPath"]
    digest = pack_record["packDigest"]
    if digest["algorithm"] != "sha-256" or sha256(manifest_path) != digest["value"]:
        fail("CSMI manifest digest mismatch")

    manifest = json.loads(manifest_path.read_bytes())
    if manifest["documentType"] != "pack-manifest":
        fail("CSMI manifest document type mismatch")
    if manifest["assembler"] != {
        "identifier": "https://bifrost.brokk.ai/csmi-export",
        "version": f"0.1.0+{PRODUCER_COMMIT}",
    }:
        fail("CSMI assembler identity mismatch")
    if len(manifest["resources"]) != 1 or len(pack_record["resourceDigests"]) != 1:
        fail("pack must contain one semantic document")
    resource = manifest["resources"][0]
    recorded = pack_record["resourceDigests"][0]
    if recorded != {
        "path": f"pack/{resource['path']}",
        "mediaType": resource["mediaType"],
        "size": resource["size"],
        "algorithm": resource["digest"]["algorithm"],
        "value": resource["digest"]["value"],
    }:
        fail("scenario and manifest resource identities disagree")
    if resource["role"] != "semantic-document" or resource["mediaType"] != "application/vnd.csmi.semantic-model.v0.1+json":
        fail("CSMI resource role or media type mismatch")
    resource_path = (manifest_path.parent / resource["path"]).resolve()
    if manifest_path.parent.resolve() not in resource_path.parents:
        fail("CSMI resource escapes the pack root")
    if resource_path.stat().st_size != resource["size"]:
        fail("CSMI resource size mismatch")
    if resource["digest"]["algorithm"] != "sha-256" or sha256(resource_path) != resource["digest"]["value"]:
        fail("CSMI resource digest mismatch")

    document = json.loads(resource_path.read_bytes())
    if document["documentType"] != "semantic-document" or document["semanticModelVersion"] != "0.1" or document["serializationVersion"] != "0.1-json":
        fail("CSMI semantic document version mismatch")
    provenance = document["provenanceRecords"]
    if len(provenance) != 1 or provenance[0]["invocationId"] != f"bifrost:{PRODUCER_COMMIT}":
        fail("CSMI producer revision mismatch")
    if provenance[0]["producer"] != {
        "identifier": "https://bifrost.brokk.ai/semantic-pack-producer",
        "version": f"0.10.7+{PRODUCER_COMMIT}",
    }:
        fail("CSMI producer identity mismatch")

    models = document["semanticModels"]
    if len(models) != 1:
        fail("pack must contain one semantic model")
    model = models[0]
    artifact = scenario_record["binaryArtifact"]
    exact_digest = {
        "algorithm": "sha-256",
        "coverage": artifact["digestCoverage"],
        "value": artifact["sha256"],
    }
    if model["artifactSelectors"] != [{"digests": [exact_digest], "purl": artifact["purl"]}]:
        fail("CSMI artifact selector does not match the retained JAR")
    if provenance[0]["inputs"] != [{"digest": exact_digest, "purl": artifact["purl"], "role": "target-artifact"}]:
        fail("CSMI provenance does not match the retained JAR")

    callables = {}
    for symbol in model["symbols"]:
        if any(part.get("role") == "callable" for part in symbol["descriptors"]):
            callables[callable_name(symbol)] = symbol["id"]
    if set(callables) != {"constant", "normalize"}:
        fail("unexpected CSMI callable inventory")
    summaries = {summary["callable"]: summary for summary in model["procedureSummaries"]}
    if summaries.get(callables["constant"]) != {"callable": callables["constant"], "transfers": []}:
        fail("constant must have an explicit empty transfer set")
    transfer = {
        "destination": {"root": {"phase": "output", "position": 0, "role": "result"}},
        "source": {"root": {"phase": "input", "position": 0, "role": "parameter"}},
    }
    if summaries.get(callables["normalize"]) != {"callable": callables["normalize"], "transfers": [transfer]}:
        fail("normalize must contain exactly parameter[0] -> normal result[0]")
    if set(summaries) != set(callables.values()):
        fail("CSMI summary inventory does not match its callables")
    complete = {
        statement["scope"]["callable"]
        for statement in model["completenessStatements"]
        if statement.get("family") == "procedure-summaries"
        and statement.get("status") == "complete"
        and set(statement.get("scope", {})) == {"callable"}
    }
    if complete != set(callables.values()):
        fail("both summaries require callable-scoped complete coverage")


def main():
    if len(sys.argv) > 2:
        fail("usage: verify.py [SCENARIO_ROOT]")
    scenario = Path(sys.argv[1]).resolve() if len(sys.argv) == 2 else DEFAULT_SCENARIO
    record = json.loads((scenario / "scenario.json").read_text())
    if record["scenario"]["status"] != "materialized":
        fail("scenario must be materialized")
    check_identity(scenario, record["scenario"]["labels"], "labels")
    check_identity(scenario, record["sourceArtifact"], "audit source")
    check_identity(scenario, record["binaryArtifact"], "binary artifact")
    check_identity(scenario, record["applicationArtifact"], "application source")
    check_identity(scenario, record["producerInput"], "Bifrost producer input")
    if sha256(scenario / record["build"]["script"]) != record["build"]["scriptSha256"]:
        fail("build script digest mismatch")

    boundary = record["analyzerBoundary"]
    input_root = (scenario / boundary["inputRoot"]).resolve()
    included = sorted(str(path.relative_to(scenario)) for path in input_root.rglob("*") if path.is_file())
    if included != sorted(boundary["includedPaths"]):
        fail("analyzer input inventory mismatch")
    for excluded in boundary["excludedRoots"]:
        excluded_root = (scenario / excluded).resolve()
        if excluded_root == input_root or input_root in excluded_root.parents:
            fail(f"excluded root enters analyzer input: {excluded}")

    with zipfile.ZipFile(scenario / record["binaryArtifact"]["path"]) as jar:
        names = jar.namelist()
        if "ai/brokk/csmi/demo/ExternalNormalizer.class" not in names:
            fail("opaque JAR is missing ExternalNormalizer.class")
        if any(name.endswith(".java") or "audit-source" in name for name in names):
            fail("opaque JAR leaks audit source")

    labels = json.loads((scenario / "labels.json").read_text())
    expectations = {flow["id"]: flow["expected"] for flow in labels["flows"]}
    if expectations != {"constant.input-to-return": False, "normalize.input-to-return": True}:
        fail("unexpected label contract")

    producer = json.loads((scenario / record["producerInput"]["path"]).read_text())
    if producer["provenance"]["revision"] != f"bifrost:{PRODUCER_COMMIT}":
        fail("authored producer revision mismatch")
    shards = [shard for shard in producer["shards"] if shard["payload"]["kind"] == "procedure_summaries"]
    if len(shards) != 1:
        fail("producer input must contain one procedure-summary shard")
    authored = {summary["target"]["symbol"]: summary for summary in shards[0]["payload"]["summaries"]}
    if authored["constant"].get("completeness") != "complete" or authored["constant"].get("transfers") != []:
        fail("authored constant summary must be complete and empty")
    expected = {
        "input": {"kind": "parameter", "ordinal": 0},
        "exit_kind": "normal",
        "output": {"kind": "normal_return"},
    }
    if authored["normalize"].get("completeness") != "complete" or authored["normalize"].get("transfers") != [expected]:
        fail("authored normalize summary mismatch")
    if record["csmiProducer"]["commit"] != PRODUCER_COMMIT or record["csmiProducer"]["api"] != "export_authored_csmi_pack":
        fail("scenario producer identity mismatch")
    verify_pack(scenario, record)
    print("verified deterministic external-normalize fixture and exact Bifrost-generated CSMI pack")


if __name__ == "__main__":
    try:
        main()
    except (AssertionError, KeyError, IndexError, json.JSONDecodeError, OSError, zipfile.BadZipFile) as error:
        print(f"verification failed: {error}", file=sys.stderr)
        sys.exit(1)
