#!/usr/bin/env python3

import unittest

import verify_results


class VerifyResultsTest(unittest.TestCase):
    def test_observed_labels_accepts_known_exact_rows(self):
        self.assertEqual(
            verify_results.observed_labels(
                {"#select": {"tuples": [["normalize.input-to-return"]]}},
                {"normalize.input-to-return"},
            ),
            {"normalize.input-to-return"},
        )

    def test_observed_labels_rejects_unknown_and_duplicates(self):
        with self.assertRaisesRegex(verify_results.InvalidResult, "unknown"):
            verify_results.observed_labels({"#select": {"tuples": [["invented"]]}}, set())
        with self.assertRaisesRegex(verify_results.InvalidResult, "duplicate"):
            verify_results.observed_labels({"#select": {"tuples": [["same"], ["same"]]}}, {"same"})

    def test_classification_preserves_undefined_precision(self):
        labels = [{"id": "negative", "expected": False}, {"id": "positive", "expected": True}]
        flows, counts, metrics = verify_results.classify(labels, set())
        self.assertEqual([flow["classification"] for flow in flows], ["TN", "FN"])
        self.assertEqual(counts, {"truePositive": 0, "falsePositive": 0, "falseNegative": 1, "trueNegative": 1})
        self.assertEqual(metrics["precision"], {"defined": False, "numerator": 0, "denominator": 0})

    def test_pack_on_classifies_positive_and_near_miss(self):
        labels = [{"id": "negative", "expected": False}, {"id": "positive", "expected": True}]
        flows, counts, metrics = verify_results.classify(labels, {"positive"})
        self.assertEqual([flow["classification"] for flow in flows], ["TN", "TP"])
        self.assertEqual(counts["truePositive"], 1)
        self.assertEqual(metrics["recall"]["value"], 1.0)


if __name__ == "__main__":
    unittest.main()
