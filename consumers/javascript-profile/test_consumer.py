import copy
import importlib.util
import json
import pathlib
import unittest


HERE = pathlib.Path(__file__).resolve().parent
ROOT = HERE.parents[1]
SPEC = importlib.util.spec_from_file_location("consumer", HERE / "consumer.py")
consumer = importlib.util.module_from_spec(SPEC)
assert SPEC.loader
SPEC.loader.exec_module(consumer)


class ConsumerTest(unittest.TestCase):
    def setUp(self):
        self.pack = json.loads((ROOT / "scenarios/node-builtin-alias/pack.json").read_text())
        self.cases = json.loads((ROOT / "scenarios/node-builtin-alias/cases.json").read_text())

    def test_pack_off_and_on(self):
        off = consumer.interpret(self.pack, self.cases, False)
        on = consumer.interpret(self.pack, self.cases, True)
        self.assertEqual(off["counts"], {"truePositive": 0, "falsePositive": 0, "falseNegative": 2, "trueNegative": 1})
        self.assertEqual(on["counts"], {"truePositive": 2, "falsePositive": 0, "falseNegative": 0, "trueNegative": 1})
        self.assertEqual(on["cases"][0]["resolvedSymbol"], on["cases"][1]["resolvedSymbol"])
        self.assertIsNone(on["cases"][2]["resolvedSymbol"])

    def test_rejects_unsupported_required_profile(self):
        mutated = copy.deepcopy(self.pack)
        mutated["semanticModels"][0]["vocabularyUses"][0]["version"] = "0.2.0"
        with self.assertRaisesRegex(consumer.UnsupportedModel, "unsupported-required-profile"):
            consumer.interpret(mutated, self.cases, True)

    def test_rejects_artifact_mismatch(self):
        mutated = copy.deepcopy(self.cases)
        mutated["candidateArtifact"]["sha256"] = "0" * 64
        with self.assertRaisesRegex(consumer.UnsupportedModel, "artifact-indeterminate-or-not-matched"):
            consumer.interpret(self.pack, mutated, True)

    def test_rejects_binding_identity_mismatch(self):
        mutated = copy.deepcopy(self.pack)
        payload = mutated["semanticModels"][0]["symbols"][0]["extensions"][0]["payload"]
        payload["canonicalModule"] = "./child_process"
        with self.assertRaisesRegex(consumer.UnsupportedModel, "identity-or-binding-mismatch"):
            consumer.interpret(mutated, self.cases, True)


if __name__ == "__main__":
    unittest.main()
