import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import adapter


def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def base_document():
    def symbol(symbol_id, name, full_name):
        return {
            "id": symbol_id,
            "scheme": "org.example.java-source",
            "schemeVersion": "0.1",
            "stability": "portable",
            "descriptors": [{"role": "callable", "name": name}],
            "externalIdentities": [{"scheme": adapter.JOERN_IDENTITY_SCHEME, "version": adapter.JOERN_IDENTITY_VERSION, "value": full_name}],
        }

    return {
        "documentType": "semantic-document",
        "schema": adapter.CSMI_SCHEMA,
        "semanticModelVersion": "0.1",
        "serializationVersion": "0.1-json",
        "provenanceRecords": [{"id": "test", "producer": {"identifier": "https://example.test", "version": "1"}, "generationMethod": "manual-authoring"}],
        "defaultProvenance": "test",
        "semanticModels": [{
            "artifactSelectors": [{"purl": "pkg:maven/test/external@1.0", "digests": [{"algorithm": "sha-256", "coverage": "binary", "value": "a" * 64}]}],
            "symbols": [symbol("instance", "instance", "test.External.instance:java.lang.String(java.lang.String)"), symbol("constant", "constant", "test.External.constant:java.lang.String(java.lang.String)")],
            "declarations": [
                {"symbol": "instance", "category": "callable", "callable": {"kind": "method", "receiver": {"kind": "instance"}, "parameters": [{"position": 0, "binding": "positional-only", "required": True}], "results": [{"position": 0}]}},
                {"symbol": "constant", "category": "callable", "callable": {"kind": "method", "parameters": [{"position": 0, "binding": "positional-only", "required": True}], "results": [{"position": 0}]}},
            ],
            "procedureSummaries": [
                {"callable": "instance", "transfers": [
                    {"source": {"root": {"phase": "input", "role": "receiver"}}, "destination": {"root": {"phase": "output", "role": "receiver"}}},
                    {"source": {"root": {"phase": "input", "role": "receiver"}}, "destination": {"root": {"phase": "output", "role": "result", "position": 0}}},
                    {"source": {"root": {"phase": "input", "role": "parameter", "position": 0}}, "destination": {"root": {"phase": "output", "role": "parameter", "position": 0}}},
                    {"source": {"root": {"phase": "input", "role": "parameter", "position": 0}}, "destination": {"root": {"phase": "output", "role": "result", "position": 0}}},
                ]},
                {"callable": "constant", "transfers": []},
            ],
            "completenessStatements": [
                {"family": "procedure-summaries", "scope": {"callable": "instance"}, "status": "complete"},
                {"family": "procedure-summaries", "scope": {"callable": "constant"}, "status": "complete"},
            ],
        }],
    }


def methods():
    return [
        {"fullName": "test.External.instance:java.lang.String(java.lang.String)", "signature": "java.lang.String(java.lang.String)", "isExternal": True, "hasReceiver": True, "parameterCount": 1},
        {"fullName": "test.External.constant:java.lang.String(java.lang.String)", "signature": "java.lang.String(java.lang.String)", "isExternal": True, "hasReceiver": False, "parameterCount": 1},
    ]


class AdapterTests(unittest.TestCase):
    def setUp(self):
        self.scheme_patch = mock.patch.object(adapter, "SUPPORTED_SYMBOL_SCHEMES", {("org.example.java-source", "0.1")})
        self.scheme_patch.start()

    def tearDown(self):
        self.scheme_patch.stop()

    def loaded(self, document=None):
        return adapter.LoadedPack("b" * 64, "c" * 64, document or base_document())

    def artifact(self):
        return {"purl": "pkg:maven/test/external@1.0", "digests": [{"algorithm": "sha-256", "coverage": "binary", "value": "a" * 64}]}

    def test_receiver_argument_return_and_self_flow_indices(self):
        result = adapter.project(self.loaded(), self.artifact(), methods())
        semantics = {item["methodFullName"]: item for item in result["semantics"]}
        self.assertEqual(semantics["test.External.instance:java.lang.String(java.lang.String)"]["mappings"], [[0, -1], [0, 0], [1, -1], [1, 1]])
        self.assertEqual(semantics["test.External.constant:java.lang.String(java.lang.String)"]["mappings"], [])
        self.assertFalse(any(item["regex"] for item in result["semantics"]))

    def assert_error(self, code, document=None, artifact=None, method_evidence=None):
        with self.assertRaises(adapter.AdapterError) as caught:
            adapter.project(self.loaded(document), artifact or self.artifact(), method_evidence or methods())
        self.assertEqual(caught.exception.code, code)

    def test_mismatched_artifact_fails_closed(self):
        artifact = self.artifact()
        artifact["digests"][0]["value"] = "d" * 64
        self.assert_error("artifact-not-matched", artifact=artifact)

    def test_unresolved_method_fails_closed(self):
        self.assert_error("unresolved-method-identity", method_evidence=methods()[1:])

    def test_ambiguous_method_fails_closed(self):
        evidence = methods()
        evidence.append(copy.deepcopy(evidence[0]))
        self.assert_error("ambiguous-method-identity", method_evidence=evidence)

    def test_incomplete_summary_is_not_projected(self):
        document = base_document()
        document["semanticModels"][0]["completenessStatements"][0]["status"] = "partial"
        document["semanticModels"][0]["completenessStatements"][0]["limitations"] = [{"kind": "coverage-limited"}]
        self.assert_error("partial-procedure-summary", document=document)

    def test_unsupported_projection_is_not_broadened(self):
        document = base_document()
        document["semanticModels"][0]["procedureSummaries"][0]["transfers"][0]["source"]["projections"] = [{"kind": "field", "name": "x"}]
        self.assert_error("unsupported-projection", document=document)

    def test_missing_pinned_external_identity_is_not_reconstructed(self):
        document = base_document()
        document["semanticModels"][0]["symbols"][0].pop("externalIdentities")
        self.assert_error("missing-exact-joern-identity", document=document)

    def test_unregistered_symbol_scheme_is_unsupported(self):
        document = base_document()
        document["semanticModels"][0]["symbols"][0]["scheme"] = "unregistered.java"
        self.assert_error("unsupported-symbol-scheme", document=document)

    def test_symbol_artifact_override_must_match(self):
        document = base_document()
        document["semanticModels"][0]["symbols"][0]["artifactSelectors"] = [{"purl": "pkg:maven/test/other@1.0"}]
        self.assert_error("artifact-not-matched", document=document)

    def test_pack_integrity_and_expected_digest(self):
        document = base_document()
        document_bytes = canonical(document)
        descriptor = {"path": "model.json", "role": "semantic-document", "mediaType": adapter.SEMANTIC_MEDIA_TYPE, "size": len(document_bytes), "digest": {"algorithm": "sha-256", "value": hashlib.sha256(document_bytes).hexdigest()}}
        manifest = {"documentType": "pack-manifest", "schema": adapter.CSMI_SCHEMA, "packFormatVersion": "0.1", "assembler": {"identifier": "https://example.test/assembler", "version": "1"}, "license": "Apache-2.0", "resources": [descriptor]}
        manifest_bytes = canonical(manifest)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "manifest.json").write_bytes(manifest_bytes)
            (root / "model.json").write_bytes(document_bytes)
            expected = hashlib.sha256(manifest_bytes).hexdigest()
            loaded = adapter.load_pack(root, expected)
            self.assertEqual(loaded.digest, expected)
            (root / "model.json").write_bytes(document_bytes + b"\n")
            with self.assertRaises(adapter.AdapterError) as caught:
                adapter.load_pack(root, expected)
            self.assertEqual(caught.exception.outcome, "integrity-failure")


if __name__ == "__main__":
    unittest.main()
