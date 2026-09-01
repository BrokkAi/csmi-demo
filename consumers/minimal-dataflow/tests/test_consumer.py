"""Diagnostic semantic tests; fixtures are temporary, not interoperability evidence."""

from __future__ import annotations

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from minimal_dataflow.consumer import ConsumerFailure, SCHEMA, load_json, load_pack, run
from minimal_dataflow.scenario import load_scenario, require_pack_available

PURL = "pkg:maven/ai.brokk.csmi/external-normalize@1.0.0"
DIGEST = "a" * 64
SELECTORS = [{"purl": PURL, "digests": [{"algorithm": "sha-256", "coverage": "artifact-bytes", "value": DIGEST}]}]


def identity(name: str) -> dict:
    return {
        "artifactSelectors": SELECTORS,
        "scheme": "ai.brokk.csmi.jvm-symbol",
        "schemeVersion": "0.1",
        "stability": "portable",
        "descriptors": [
            {"role": "namespace", "name": "ai"},
            {"role": "namespace", "name": "brokk"},
            {"role": "namespace", "name": "csmi"},
            {"role": "namespace", "name": "fixture"},
            {"role": "type", "name": "ExternalStrings"},
            {"role": "callable", "name": name, "disambiguator": "(java.lang.String)->java.lang.String"},
        ],
    }


def semantic_document() -> dict:
    symbols = []
    declarations = []
    summaries = []
    completeness = []
    for index, name in enumerate(("normalize", "constant")):
        symbol_id = f"callable{index}"
        symbols.append({"id": symbol_id, **{key: value for key, value in identity(name).items() if key != "artifactSelectors"}})
        declarations.append({
            "symbol": symbol_id,
            "category": "callable",
            "callable": {
                "kind": "method",
                "parameters": [{"position": 0, "binding": "positional-only", "required": True}],
                "results": [{"position": 0}],
            },
        })
        transfers = []
        if name == "normalize":
            transfers.append({
                "source": {"root": {"phase": "input", "role": "parameter", "position": 0}},
                "destination": {"root": {"phase": "output", "role": "result", "position": 0}},
            })
        summaries.append({"callable": symbol_id, "transfers": transfers})
        completeness.append({"family": "procedure-summaries", "scope": {"callable": symbol_id}, "status": "complete"})
    return {
        "documentType": "semantic-document",
        "schema": SCHEMA,
        "semanticModelVersion": "0.1",
        "serializationVersion": "0.1-json",
        "provenanceRecords": [{
            "id": "producer",
            "producer": {"identifier": "https://example.invalid/diagnostic-producer", "version": "test-only"},
            "generationMethod": "manual-authoring",
        }],
        "defaultProvenance": "producer",
        "semanticModels": [{
            "artifactSelectors": SELECTORS,
            "symbols": symbols,
            "declarations": declarations,
            "procedureSummaries": summaries,
            "completenessStatements": completeness,
        }],
    }


def write_pack(root: Path, document: dict | None = None) -> tuple[Path, str]:
    pack = root / "pack"
    pack.mkdir()
    document = document or semantic_document()
    raw = json.dumps(document, sort_keys=True, separators=(",", ":")).encode()
    (pack / "model.json").write_bytes(raw)
    manifest = {
        "documentType": "pack-manifest",
        "schema": SCHEMA,
        "packFormatVersion": "0.1",
        "assembler": {"identifier": "https://example.invalid/diagnostic-assembler", "version": "test-only"},
        "license": "Apache-2.0",
        "resources": [{
            "path": "model.json",
            "role": "semantic-document",
            "mediaType": "application/vnd.csmi.semantic-model.v0.1+json",
            "size": len(raw),
            "digest": {"algorithm": "sha-256", "value": hashlib.sha256(raw).hexdigest()},
        }],
    }
    manifest_raw = json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
    (pack / "manifest.json").write_bytes(manifest_raw)
    return pack, hashlib.sha256(manifest_raw).hexdigest()


def inputs() -> tuple[dict, dict, dict, dict]:
    analysis = {
        "formatVersion": "minimal-dataflow-input/1",
        "nodes": ["source-normalize", "normalize-arg", "normalize-result", "sink-normalize", "source-constant", "constant-arg", "constant-result", "sink-constant"],
        "edges": [["source-normalize", "normalize-arg"], ["normalize-result", "sink-normalize"], ["source-constant", "constant-arg"], ["constant-result", "sink-constant"]],
        "externalCalls": [
            {"id": "normalize-call", "target": identity("normalize"), "arguments": ["normalize-arg"], "results": ["normalize-result"]},
            {"id": "constant-call", "target": identity("constant"), "arguments": ["constant-arg"], "results": ["constant-result"]},
        ],
        "queries": [
            {"id": "normalize.input-to-return", "sourceNode": "source-normalize", "sinkNode": "sink-normalize"},
            {"id": "constant.input-to-return", "sourceNode": "source-constant", "sinkNode": "sink-constant"},
        ],
    }
    artifact = {"purl": PURL, "digests": SELECTORS[0]["digests"]}
    labels = {"formatVersion": "csmi-demo-labels/1", "flows": [
        {"id": "normalize.input-to-return", "expectedFlow": True},
        {"id": "constant.input-to-return", "expectedFlow": False},
    ]}
    return analysis, artifact, labels, {"id": "diagnostic-only"}


class ConsumerTests(unittest.TestCase):
    def loaded(self, document: dict | None = None):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        pack, digest = write_pack(Path(temp.name), document)
        return load_pack(pack, digest)

    def test_pack_off_has_false_negative(self):
        analysis, artifact, labels, scenario = inputs()
        result = run(analysis=analysis, artifact=artifact, labels=labels, scenario_identity=scenario, pack=None)
        self.assertEqual(result["counts"], {"truePositive": 0, "falsePositive": 0, "falseNegative": 1, "trueNegative": 1})
        self.assertFalse(result["metrics"]["precision"]["defined"])

    def test_pack_on_positive_transfer_and_complete_negative(self):
        analysis, artifact, labels, scenario = inputs()
        result = run(analysis=analysis, artifact=artifact, labels=labels, scenario_identity=scenario, pack=self.loaded())
        self.assertEqual([flow["classification"] for flow in result["flows"]], ["TP", "TN"])
        self.assertEqual(result["counts"], {"truePositive": 1, "falsePositive": 0, "falseNegative": 0, "trueNegative": 1})

    def test_expected_labels_score_but_do_not_change_observed_flow(self):
        analysis, artifact, labels, scenario = inputs()
        labels["flows"][0]["expectedFlow"] = False
        result = run(analysis=analysis, artifact=artifact, labels=labels, scenario_identity=scenario, pack=self.loaded())
        self.assertTrue(result["flows"][0]["observedFlow"])
        self.assertEqual(result["flows"][0]["classification"], "FP")

    def assert_failure(self, code: str, document_mutator=None, input_mutator=None):
        document = semantic_document()
        if document_mutator:
            document_mutator(document)
        analysis, artifact, labels, scenario = inputs()
        if input_mutator:
            input_mutator(analysis, artifact, labels)
        with self.assertRaises(ConsumerFailure) as caught:
            run(analysis=analysis, artifact=artifact, labels=labels, scenario_identity=scenario, pack=self.loaded(document))
        self.assertEqual(caught.exception.code, code)

    def test_mismatched_artifact_identity(self):
        self.assert_failure("artifact-mismatch", input_mutator=lambda _a, artifact, _l: artifact.update(purl="pkg:maven/ai.brokk.csmi/external-normalize@2.0.0"))

    def test_unresolved_structural_symbol(self):
        self.assert_failure("unresolved-symbol", input_mutator=lambda analysis, _a, _l: analysis["externalCalls"][0].update(target=identity("same-name-wrong-identity")))

    def test_incomplete_semantics(self):
        self.assert_failure("incomplete-evidence", document_mutator=lambda doc: doc["semanticModels"][0]["completenessStatements"][0].update(status="partial", limitations=[{"kind": "diagnostic"}]))

    def test_unsupported_required_semantics(self):
        self.assert_failure("unsupported-semantics", document_mutator=lambda doc: doc["semanticModels"][0].update(vocabularyUses=[{"identifier": "example.required", "version": "1", "schema": "https://example.invalid/schema", "requirement": "required", "affects": [{"kind": "fact-family", "family": "procedure-summaries", "scope": {}}]}]))

    def test_malformed_noncanonical_pack(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        pack, _digest = write_pack(Path(temp.name))
        value = json.loads((pack / "manifest.json").read_text())
        (pack / "manifest.json").write_text(json.dumps(value, indent=2))
        with self.assertRaises(ConsumerFailure) as caught:
            load_pack(pack, None)
        self.assertEqual(caught.exception.code, "malformed-pack")

    def test_integrity_failure(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        pack, digest = write_pack(Path(temp.name))
        (pack / "model.json").write_bytes(b"{}")
        with self.assertRaises(ConsumerFailure) as caught:
            load_pack(pack, digest)
        self.assertEqual(caught.exception.code, "integrity-failure")

    def test_landed_shared_scenario_pack_matches_exact_identities(self):
        scenario_root = Path(__file__).resolve().parents[3] / "scenarios" / "external-normalize"
        artifact, labels, scenario, pack = load_scenario(scenario_root)
        self.assertEqual(artifact["purl"], "pkg:maven/ai.brokk.csmi-demo/external-normalize@1.0.0")
        self.assertEqual({flow["id"]: flow["expectedFlow"] for flow in labels["flows"]}, {
            "constant.input-to-return": False,
            "normalize.input-to-return": True,
        })
        self.assertEqual(scenario["id"], "external-normalize")
        manifest_path, digest = require_pack_available(pack)
        self.assertEqual(manifest_path, "pack/manifest.json")
        self.assertEqual(digest, "97873207ab6ffbc49bafbf4f2f0c08779081529ae1fedabaafb754f60f6fbb76")
        analysis_path = Path(__file__).resolve().parents[1] / "inputs" / "external-normalize.json"
        loaded_pack = load_pack(scenario_root / Path(manifest_path).parent, digest)
        result = run(
            analysis=load_json(analysis_path),
            artifact=artifact,
            labels=labels,
            scenario_identity=scenario,
            pack=loaded_pack,
        )
        self.assertEqual([flow["classification"] for flow in result["flows"]], ["TN", "TP"])
        self.assertEqual(result["counts"], {"truePositive": 1, "falsePositive": 0, "falseNegative": 0, "trueNegative": 1})


if __name__ == "__main__":
    unittest.main()
