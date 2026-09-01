import copy
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

import adapter

HERE = Path(__file__).resolve().parent
SCENARIO_MANIFEST = HERE.parent.parent / "scenarios" / "external-normalize" / "scenario.json"

def canonical(value):
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True).encode()


def base_document():
    def symbol(symbol_id, name):
        return {
            "id": symbol_id,
            "scheme": "org.example.java-source",
            "schemeVersion": "0.1",
            "stability": "portable",
            "descriptors": [
                {"role": "namespace", "name": "test"},
                {"role": "type", "name": "External"},
                {"role": "callable", "name": name, "disambiguator": "(java.lang.String)->java.lang.String"},
            ],
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
            "symbols": [
                symbol("instance", "instance"),
                symbol("constant", "constant"),
                {"id": "external-type", "scheme": "org.example.java-source", "schemeVersion": "0.1", "stability": "portable", "descriptors": [{"role": "namespace", "name": "test"}, {"role": "type", "name": "External"}]},
                {"id": "string-type", "scheme": "org.example.java-source", "schemeVersion": "0.1", "stability": "portable", "descriptors": [{"role": "namespace", "name": "java"}, {"role": "namespace", "name": "lang"}, {"role": "type", "name": "String"}]},
            ],
            "declarations": [
                {"symbol": "instance", "owner": "external-type", "category": "callable", "callable": {"kind": "method", "receiver": {"kind": "instance"}, "parameters": [{"position": 0, "binding": "positional-only", "required": True, "type": {"kind": "reference", "symbol": "string-type"}}], "results": [{"position": 0, "type": {"kind": "reference", "symbol": "string-type"}}]}},
                {"symbol": "constant", "owner": "external-type", "category": "callable", "callable": {"kind": "method", "parameters": [{"position": 0, "binding": "positional-only", "required": True, "type": {"kind": "reference", "symbol": "string-type"}}], "results": [{"position": 0, "type": {"kind": "reference", "symbol": "string-type"}}]}},
            ],
            "procedureSummaries": [
                {"callable": "instance", "transfers": [
                    {"source": {"root": {"phase": "input", "role": "receiver"}}, "destination": {"root": {"phase": "output", "role": "receiver"}}},
                    {"source": {"root": {"phase": "input", "role": "receiver"}}, "destination": {"root": {"phase": "output", "role": "result", "position": 0}}},
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
        {"name": "instance", "fullName": "test.External.instance:java.lang.String(java.lang.String)", "signature": "java.lang.String(java.lang.String)", "isExternal": True, "hasReceiver": True, "parameterCount": 1},
        # Joern models a Java static-call type qualifier in argument slot 0;
        # that is not a semantic CSMI receiver.
        {"name": "constant", "fullName": "test.External.constant:java.lang.String(java.lang.String)", "signature": "java.lang.String(java.lang.String)", "isExternal": True, "hasReceiver": True, "parameterCount": 1},
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
        self.assertEqual(semantics["test.External.constant:java.lang.String(java.lang.String)"]["mappings"], [[0, 0], [1, 1]])
        self.assertEqual(semantics["test.External.constant:java.lang.String(java.lang.String)"]["csmiTransferMappings"], [])
        self.assertFalse(any(item["regex"] for item in result["semantics"]))
        self.assertEqual(semantics["test.External.constant:java.lang.String(java.lang.String)"]["coverage"]["status"], "complete")
        self.assertEqual(result["csmi"]["defaultProvenance"], "test")

    def test_static_java_type_qualifier_is_not_a_csmi_receiver(self):
        result = adapter.project(self.loaded(), self.artifact(), methods())
        constant = next(item for item in result["semantics"] if item["methodFullName"].startswith("test.External.constant:"))
        self.assertEqual(constant["mappings"], [[0, 0], [1, 1]])

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
        document["semanticModels"][0]["procedureSummaries"][0]["transfers"][0]["source"]["projection"] = {
            "scheme": "https://example.test/fields", "schemeVersion": "1", "steps": [{"kind": "field", "args": {"name": "x"}}]
        }
        self.assert_error("unsupported-projection", document=document)

    def test_unprojected_output_parameter_requires_writeback_vocabulary(self):
        document = base_document()
        document["semanticModels"][0]["procedureSummaries"][0]["transfers"].append({
            "source": {"root": {"phase": "input", "role": "parameter", "position": 0}},
            "destination": {"root": {"phase": "output", "role": "parameter", "position": 0}},
        })
        self.assert_error("unsupported-parameter-writeback", document=document)

    def test_full_name_must_equal_structurally_projected_identity(self):
        evidence = methods()
        evidence[0]["fullName"] = "test.Other.redirect:java.lang.String(java.lang.String)"
        self.assert_error("unresolved-method-identity", method_evidence=evidence)

    def test_unregistered_symbol_scheme_is_unsupported(self):
        document = base_document()
        document["semanticModels"][0]["symbols"][0]["scheme"] = "unregistered.java"
        self.assert_error("unsupported-symbol-scheme", document=document)

    def test_callable_disambiguator_must_match_declared_types(self):
        document = base_document()
        document["semanticModels"][0]["symbols"][0]["descriptors"][-1]["disambiguator"] = "()->java.lang.String"
        self.assert_error("callable-disambiguator-mismatch", document=document)

    def test_symbol_artifact_override_must_match(self):
        document = base_document()
        document["semanticModels"][0]["symbols"][0]["artifactSelectors"] = [{"purl": "pkg:maven/test/other@1.0"}]
        self.assert_error("artifact-not-matched", document=document)

    def test_all_required_digest_coverages_must_be_present(self):
        document = base_document()
        document["semanticModels"][0]["artifactSelectors"][0]["digests"].append({
            "algorithm": "sha-256", "coverage": "source-archive", "value": "b" * 64,
        })
        self.assert_error("artifact-applicability-indeterminate", document=document)

    def test_alternative_algorithm_for_same_coverage_need_not_be_comparable(self):
        document = base_document()
        document["semanticModels"][0]["artifactSelectors"][0]["digests"].append({
            "algorithm": "sha-512", "coverage": "binary", "value": "b" * 128,
        })
        result = adapter.project(self.loaded(document), self.artifact(), methods())
        self.assertEqual(result["outcome"], "applied")

    def test_version_range_is_indeterminate_without_vers_support(self):
        document = base_document()
        selector = document["semanticModels"][0]["artifactSelectors"][0]
        selector["purl"] = "pkg:maven/test/external"
        selector["versionRange"] = "vers:maven/>=1.0|<2.0"
        self.assert_error("artifact-applicability-indeterminate", document=document)

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

    def test_pinned_schema_rejects_unknown_core_fields(self):
        document = base_document()
        document["semanticModels"][0]["unknownCoreField"] = True
        with self.assertRaises(adapter.AdapterError) as caught:
            adapter.validate_schema(document, "test document")
        self.assertEqual(caught.exception.code, "schema-invalid")

    def test_unresolved_provenance_fails_closed(self):
        document = base_document()
        document["semanticModels"][0]["procedureSummaries"][0]["provenance"] = ["missing"]
        self.assert_error("unresolved-provenance", document=document)

    def test_shared_scenario_pack_loads_and_matches_retained_jar(self):
        loaded, artifact = adapter.load_scenario_pack(SCENARIO_MANIFEST)
        self.assertEqual(loaded.digest, "97873207ab6ffbc49bafbf4f2f0c08779081529ae1fedabaafb754f60f6fbb76")
        self.assertEqual(artifact["digests"][0]["value"], "d343c7d2fc3703ac426340bd6c7ae5ed4c414436f197b7a2cc98fc4a9357d8e8")


if __name__ == "__main__":
    unittest.main()
