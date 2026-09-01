import json
import hashlib
import tempfile
import unittest
from pathlib import Path

import results


HERE = Path(__file__).resolve().parent
SCENARIO = HERE.parent.parent / "scenarios" / "external-normalize"


class ResultsTests(unittest.TestCase):
    def test_retained_evidence_is_bound_to_current_shared_inputs(self):
        manifest_path = SCENARIO / "scenario.json"
        labels_path = SCENARIO / "labels.json"
        versions_path = HERE / "versions.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        pack_off = json.loads((HERE / "evidence" / "pack-off.json").read_text(encoding="utf-8"))
        pack_on = json.loads((HERE / "evidence" / "pack-on-unavailable.json").read_text(encoding="utf-8"))

        sha256 = lambda path: hashlib.sha256(path.read_bytes()).hexdigest()
        for record in (pack_off, pack_on):
            self.assertEqual(record["scenario"]["manifestSha256"], sha256(manifest_path))
            self.assertEqual(record["scenario"]["labelsSha256"], sha256(labels_path))
            self.assertEqual(record["consumer"]["configurationSha256"], sha256(versions_path))
            self.assertEqual(record["scenario"]["artifact"]["sha256"], manifest["binaryArtifact"]["sha256"])
        self.assertEqual(pack_off["run"]["status"], "complete")
        self.assertEqual(pack_on["run"]["diagnostic"], manifest["csmiPack"]["blocker"])
        self.assertIsNone(pack_on["metrics"])

    def evidence_paths(self, root: Path):
        cpg = root / "cpg.bin.zip"
        methods = root / "methods.json"
        cpg.write_bytes(b"same-cpg")
        methods.write_text(json.dumps([{
            "fullName": "ai.brokk.csmi.demo.ExternalNormalizer.normalize:java.lang.String(java.lang.String)",
            "signature": "java.lang.String(java.lang.String)",
            "isExternal": True,
            "hasReceiver": True,
            "parameterCount": 1,
        }]) + "\n", encoding="utf-8")
        return cpg, methods

    def test_pack_off_metrics_preserve_false_positive(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cpg, methods = self.evidence_paths(root)
            observations = root / "observations.json"
            observations.write_text(json.dumps({
                "schemaVersion": 1,
                "joernVersion": "4.0.592",
                "packEnabled": False,
                "flows": [
                    {"id": "constant.input-to-return", "observed": True, "pathCount": 1, "paths": [["constant"]]},
                    {"id": "normalize.input-to-return", "observed": True, "pathCount": 1, "paths": [["normalize"]]},
                ],
            }), encoding="utf-8")
            record, labels, _ = results.base_record(SCENARIO, cpg, methods, False)
            result = results.completed(record, labels, observations)
            self.assertEqual(result["counts"], {"truePositive": 1, "falsePositive": 1, "falseNegative": 0, "trueNegative": 0})
            self.assertEqual(result["metrics"]["precision"]["value"], 0.5)
            self.assertEqual(result["metrics"]["recall"]["value"], 1.0)
            self.assertEqual(len(result["analysis"]["externalMethods"]), 1)

    def test_pack_on_unavailable_is_not_counted_as_true_negative(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cpg, methods = self.evidence_paths(root)
            record, labels, manifest = results.base_record(SCENARIO, cpg, methods, True)
            result = results.unavailable(record, labels, manifest)
            self.assertEqual(result["run"]["status"], "unavailable")
            self.assertIsNone(result["counts"])
            self.assertIsNone(result["metrics"])
            self.assertTrue(all(flow["classification"] == "unresolved" for flow in result["flows"]))

    def test_completed_pack_on_requires_applied_adapter_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cpg, methods = self.evidence_paths(root)
            observations = root / "observations.json"
            observations.write_text(json.dumps({
                "joernVersion": "4.0.592",
                "packEnabled": True,
                "flows": [
                    {"id": "constant.input-to-return", "observed": False, "pathCount": 0, "paths": []},
                    {"id": "normalize.input-to-return", "observed": True, "pathCount": 1, "paths": [["normalize"]]},
                ],
            }), encoding="utf-8")
            record, labels, _ = results.base_record(SCENARIO, cpg, methods, True)
            with self.assertRaisesRegex(ValueError, "adapter evidence"):
                results.completed(record, labels, observations)

            semantics = root / "semantics.json"
            semantics.write_text(json.dumps({
                "outcome": "applied",
                "csmi": {"packDigest": "a" * 64, "semanticDocumentDigest": "b" * 64},
            }), encoding="utf-8")
            result = results.completed(record, labels, observations, semantics)
            self.assertEqual(result["counts"], {"truePositive": 1, "falsePositive": 0, "falseNegative": 0, "trueNegative": 1})
            self.assertEqual(result["csmiPack"]["packDigest"], "a" * 64)

            baseline = root / "pack-off.json"
            baseline_record = json.loads(json.dumps(result))
            baseline_record["analysis"]["packEnabled"] = False
            baseline_record["counts"]["falsePositive"] = 1
            baseline_record["counts"]["trueNegative"] = 0
            baseline.write_text(json.dumps(baseline_record), encoding="utf-8")
            results.validate_pack_on(result, baseline)

            baseline_record["counts"]["falsePositive"] = 0
            baseline.write_text(json.dumps(baseline_record), encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "no false positive or false negative"):
                results.validate_pack_on(result, baseline)

    def test_observation_label_mismatch_is_rejected(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            cpg, methods = self.evidence_paths(root)
            observations = root / "observations.json"
            observations.write_text(json.dumps({"joernVersion": "4.0.592", "packEnabled": False, "flows": []}), encoding="utf-8")
            record, labels, _ = results.base_record(SCENARIO, cpg, methods, False)
            with self.assertRaisesRegex(ValueError, "complete shared label set"):
                results.completed(record, labels, observations)


if __name__ == "__main__":
    unittest.main()
