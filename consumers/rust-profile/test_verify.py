import copy
import importlib.util
import json
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("rust_verify", HERE / "verify.py")
rust_verify = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(rust_verify)


class RustProfileConsumerTest(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((HERE / "fixtures" / "rust-profile.json").read_text())

    def test_projects_resolver_proven_meanings(self):
        result = rust_verify.project(self.document)
        self.assertEqual(result["profile"], {
            "identifier": "csmi.rust",
            "version": "0.1.0",
            "scheme": "csmi.rust.source-item",
            "schemeVersion": "0.1.0",
        })
        meanings = result["meanings"]
        self.assertEqual(meanings["crateRoot"]["descriptors"][-1]["disambiguator"], "lib:acme_codec")
        self.assertEqual(meanings["inherentAssociatedFunction"]["owner"]["descriptors"][-1]["name"], "Record")
        self.assertEqual(meanings["inherentAssociatedFunction"]["genericParameter"]["descriptors"][-1]["name"], "0")
        self.assertEqual(meanings["traitImplementation"]["traitItem"]["descriptors"][-1]["name"], "display")
        self.assertEqual(meanings["generation"]["portability"], "portable")
        self.assertEqual(meanings["nativeBoundary"]["cardinality"], "one-to-one")

    def assert_failure(self, mutate, code):
        mutated = copy.deepcopy(self.document)
        mutate(mutated)
        with self.assertRaises(rust_verify.ConsumerFailure) as caught:
            rust_verify.project(mutated)
        self.assertEqual(caught.exception.code, code)

    def test_name_only_trait_mapping_fails_closed(self):
        self.assert_failure(
            lambda document: document["semanticModels"][0]["extensionFacts"][2]["payload"]["associatedItems"].__setitem__(0, {"providedItem": "recordDisplay", "traitItem": "recordDisplay"}),
            "invalid-associated-item",
        )

    def test_crate_name_heuristic_fails_closed(self):
        self.assert_failure(
            lambda document: document["semanticModels"][0]["extensionFacts"][0]["payload"].update(crateName="acme-codec"),
            "invalid-crate-mapping",
        )

    def test_unsupported_profile_fails_closed(self):
        self.assert_failure(
            lambda document: document["semanticModels"][0]["vocabularyUses"][0].update(version="0.2.0"),
            "unsupported-required-profile",
        )

    def test_missing_configuration_evidence_is_indeterminate(self):
        config = self.document["semanticModels"][0]["compatibilityConstraints"][0]["value"]
        incomplete = copy.deepcopy(config)
        incomplete.pop("cfgAtoms")
        with self.assertRaises(rust_verify.ConsumerFailure) as caught:
            rust_verify.project(self.document, incomplete)
        self.assertEqual(caught.exception.code, "configuration-indeterminate")

    def test_trait_method_name_without_structural_identity_fails_closed(self):
        self.assert_failure(
            lambda document: document["semanticModels"][0]["extensionFacts"][2]["payload"].update(trait="missingTrait"),
            "invalid-implementation",
        )

    def test_portable_generation_without_output_evidence_fails_closed(self):
        def mutate(document):
            document["semanticModels"][0]["extensionFacts"][3]["payload"].pop("outputSha256")

        self.assert_failure(mutate, "invalid-generation")

    def test_native_mapping_cannot_resolve_a_different_source_by_name(self):
        self.assert_failure(
            lambda document: document["semanticModels"][0]["extensionFacts"][4]["payload"].update(source="recordDisplay"),
            "invalid-native-boundary",
        )


if __name__ == "__main__":
    unittest.main()
