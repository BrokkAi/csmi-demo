#!/usr/bin/env python3

import hashlib
import json
import tempfile
import unittest
from pathlib import Path

import generate_model


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def symbol(name: str) -> dict:
    return {
        "id": name,
        "scheme": generate_model.JVM_SCHEME,
        "schemeVersion": generate_model.JVM_SCHEME_VERSION,
        "stability": "portable",
        "descriptors": [
            {"role": "namespace", "name": "org"},
            {"role": "namespace", "name": "example"},
            {"role": "type", "name": "OpaqueStrings"},
            {
                "role": "callable",
                "name": name,
                "disambiguator": "(java.lang.String)->java.lang.String",
            },
        ],
    }


def transfer() -> dict:
    return {
        "source": {"root": {"phase": "input", "role": "parameter", "position": 0}},
        "destination": {"root": {"phase": "output", "role": "result", "position": 0}},
    }


class GenerateModelTest(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.root = Path(self.directory.name)
        self.artifact = self.root / "fixture.jar"
        self.artifact.write_bytes(b"opaque fixture bytes")

    def tearDown(self):
        self.directory.cleanup()

    def document(self, receiver=None):
        artifact_digest = generate_model.sha256(self.artifact)
        declarations = []
        summaries = []
        completeness = []
        for name in ("normalize", "constant"):
            shape = {
                "kind": "method",
                "parameters": [{"position": 0, "binding": "positional", "required": True}],
                "results": [{"position": 0}],
            }
            if receiver is not None:
                shape["receiver"] = receiver
            declarations.append({"symbol": name, "category": "callable", "callable": shape})
            summaries.append({"callable": name, "transfers": [transfer()] if name == "normalize" else []})
            completeness.append(
                {"family": "procedure-summaries", "scope": {"callable": name}, "status": "complete"}
            )
        return {
            "documentType": "semantic-document",
            "schema": generate_model.SCHEMA,
            "semanticModelVersion": "0.1",
            "serializationVersion": "0.1-json",
            "semanticModels": [
                {
                    "artifactSelectors": [
                        {
                            "purl": "pkg:maven/org.example/opaque@1.0.0",
                            "digests": [
                                {
                                    "algorithm": "sha-256",
                                    "coverage": "whole-artifact",
                                    "value": artifact_digest,
                                }
                            ],
                        }
                    ],
                    "symbols": [symbol("normalize"), symbol("constant")],
                    "declarations": declarations,
                    "procedureSummaries": summaries,
                    "completenessStatements": completeness,
                }
            ],
        }

    def test_generates_exact_summary_neutral_and_trace(self):
        document = self.document()
        purl, summaries, neutrals, trace = generate_model.build_rows(document, self.artifact)
        self.assertEqual(purl, "pkg:maven/org.example/opaque@1.0.0")
        self.assertEqual(summaries[0][2:9], [False, "normalize", "(String)", "", "Argument[0]", "ReturnValue", "taint"])
        self.assertEqual(neutrals[0][2:], ["constant", "(String)", "summary", "manual"])
        self.assertEqual({row["predicate"] for row in trace}, {"summaryModel", "neutralModel"})

    def test_rejects_artifact_mismatch(self):
        document = self.document()
        self.artifact.write_bytes(b"different")
        with self.assertRaisesRegex(generate_model.Unsupported, "exactly one versioned whole-artifact"):
            generate_model.build_rows(document, self.artifact)

    def test_rejects_instance_callable_due_to_neutral_subtype_scope(self):
        with self.assertRaisesRegex(generate_model.Unsupported, "receiver-free"):
            generate_model.build_rows(self.document(receiver={"kind": "type"}), self.artifact)

    def test_manifest_resource_integrity_fails_closed(self):
        pack = self.root / "pack"
        pack.mkdir()
        model_bytes = json.dumps(self.document(), separators=(",", ":")).encode()
        model = pack / "model.json"
        model.write_bytes(model_bytes)
        manifest = {
            "documentType": "pack-manifest",
            "schema": generate_model.SCHEMA,
            "packFormatVersion": "0.1",
            "resources": [
                {
                    "path": "model.json",
                    "role": "semantic-document",
                    "mediaType": generate_model.MEDIA_TYPE,
                    "size": len(model_bytes),
                    "digest": {"algorithm": "sha-256", "value": digest(model_bytes)},
                }
            ],
        }
        path, loaded = generate_model.select_document(pack, manifest)
        self.assertEqual(path, model.resolve())
        self.assertEqual(loaded["documentType"], "semantic-document")
        manifest["resources"][0]["digest"]["value"] = "0" * 64
        with self.assertRaisesRegex(generate_model.Unsupported, "digest mismatch"):
            generate_model.select_document(pack, manifest)


if __name__ == "__main__":
    unittest.main()
