import copy
import importlib.util
import json
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("java_jvm_verify", HERE / "verify.py")
java_jvm_verify = importlib.util.module_from_spec(spec)
assert spec.loader
spec.loader.exec_module(java_jvm_verify)


class JavaJvmProfileConsumerTest(unittest.TestCase):
    def setUp(self):
        self.document = json.loads((HERE / "fixtures" / "java-jvm-mapping.json").read_text())
        self.candidate = {
            "javaRelease": 17,
            "classFileMajor": 61,
            "targetPlatform": "jvm",
        }

    def test_projects_all_four_profiles_without_merging_identity(self):
        result = java_jvm_verify.project(self.document, self.candidate)
        self.assertEqual(result["status"], "complete")
        self.assertEqual(
            [profile["identifier"] for profile in result["profiles"]],
            [
                "csmi.java-source-identity",
                "csmi.jvm-binary-identity",
                "csmi.java-jvm-mapping",
                "csmi.jvm-compatibility",
            ],
        )
        source = result["meanings"]["sourceIdentity"]
        binary = result["meanings"]["binaryIdentity"]
        self.assertEqual(source["scheme"], "csmi.java-source-identity")
        self.assertEqual(binary["scheme"], "csmi.jvm-binary-identity")
        self.assertNotEqual(source, binary)
        self.assertEqual(binary["binaryEntity"]["descriptor"], "(Ljava/lang/String;)Ljava/lang/String;")
        self.assertEqual(result["meanings"]["mapping"]["coverage"], "complete")
        self.assertEqual(result["meanings"]["compatibility"]["status"], "compatible")

    def assert_failure(self, mutate, code, candidate=None):
        mutated = copy.deepcopy(self.document)
        mutate(mutated)
        with self.assertRaises(java_jvm_verify.ConsumerFailure) as caught:
            java_jvm_verify.project(mutated, self.candidate if candidate is None else candidate)
        self.assertEqual(caught.exception.code, code)

    def test_missing_candidate_release_is_indeterminate(self):
        candidate = {"classFileMajor": 61, "targetPlatform": "jvm"}
        with self.assertRaises(java_jvm_verify.ConsumerFailure) as caught:
            java_jvm_verify.project(self.document, candidate)
        self.assertEqual(caught.exception.code, "incomplete-compatibility-evidence")

    def test_unsupported_required_profile_fails_closed(self):
        self.assert_failure(
            lambda document: document["semanticModels"][0]["vocabularyUses"][0].update(version="0.2"),
            "unsupported-required-profile",
        )

    def test_mapping_target_must_be_exact_binary_identity_not_a_name(self):
        self.assert_failure(
            lambda document: document["semanticModels"][0]["extensionFacts"][0]["payload"].update(binarySymbols=["normalize"]),
            "invalid-mapping",
        )

    def test_malformed_mapping_target_fails_closed(self):
        self.assert_failure(
            lambda document: document["semanticModels"][0]["extensionFacts"][0]["payload"].update(binarySymbols=[{"name": "normalize"}]),
            "malformed-model",
        )

    def test_descriptor_resemblance_without_exact_binary_identity_fails_closed(self):
        self.assert_failure(
            lambda document: document["semanticModels"][0]["symbols"][1]["descriptors"][3].update(disambiguator="(Ljava/lang/String;)Ljava/lang/Object;"),
            "invalid-binary-identity",
        )

    def test_established_mapping_requires_evidence(self):
        self.assert_failure(
            lambda document: document["semanticModels"][0]["extensionFacts"][0]["payload"].pop("evidence"),
            "missing-mapping-evidence",
        )

    def test_complete_coverage_cannot_hide_partial_mapping(self):
        def mutate(document):
            payload = document["semanticModels"][0]["extensionFacts"][0]["payload"]
            payload["resolution"] = "indeterminate"

        self.assert_failure(mutate, "incomplete-mapping")

    def test_incomplete_mapping_coverage_fails_closed(self):
        self.assert_failure(
            lambda document: document["semanticModels"][0]["completenessStatements"][0].update(status="partial"),
            "incomplete-mapping-coverage",
        )

    def test_reversed_compatibility_range_is_invalid(self):
        def mutate(document):
            document["semanticModels"][0]["compatibilityConstraints"][0]["value"]["constraints"]["javaRelease"] = {"minimum": 21, "maximum": 17}

        self.assert_failure(mutate, "invalid-compatibility-constraints")

    def test_candidate_constraints_are_inclusive_and_fail_on_incompatibility(self):
        candidate = {"javaRelease": 16, "classFileMajor": 61, "targetPlatform": "jvm"}
        with self.assertRaises(java_jvm_verify.ConsumerFailure) as caught:
            java_jvm_verify.project(self.document, candidate)
        self.assertEqual(caught.exception.code, "incompatible-constraints")

    def test_wrong_platform_is_incompatible(self):
        candidate = {"javaRelease": 17, "classFileMajor": 61, "targetPlatform": "android"}
        with self.assertRaises(java_jvm_verify.ConsumerFailure) as caught:
            java_jvm_verify.project(self.document, candidate)
        self.assertEqual(caught.exception.code, "incompatible-constraints")


if __name__ == "__main__":
    unittest.main()
