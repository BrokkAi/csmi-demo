#!/usr/bin/env python3

import unittest

import verify_blocked


class VerifyBlockedTest(unittest.TestCase):
    def test_observed_labels_reads_exact_table_shape(self):
        self.assertEqual(
            verify_blocked.observed_labels({"#select": {"tuples": [["normalize.input-to-return"]]}}),
            ["normalize.input-to-return"],
        )

    def test_observed_labels_rejects_duplicate_rows(self):
        with self.assertRaisesRegex(verify_blocked.InvalidDiagnostic, "duplicate"):
            verify_blocked.observed_labels({"#select": {"tuples": [["same"], ["same"]]}})

    def test_report_preserves_blocker_without_metrics(self):
        scenario = {
            "scenario": {
                "id": "external-normalize",
                "version": "1.0.0",
                "status": "blocked",
                "labels": {"sha256": "labels"},
            },
            "binaryArtifact": {
                "purl": "pkg:maven/example/demo@1.0.0",
                "path": "analyzer-input/lib/demo.jar",
                "digestCoverage": "jar",
                "sha256": "artifact",
            },
            "analyzerBoundary": {"inputRoot": "analyzer-input", "excludedRoots": ["audit-source"]},
            "csmiPack": {
                "status": "unavailable",
                "blocker": {
                    "code": "summary.empty",
                    "path": "$.shards[1].payload.summaries[0]",
                    "upstreamIssue": "https://github.com/BrokkAi/bifrost-dev/issues/2841",
                },
            },
        }
        versions = {
            "CODEQL_CLI_VERSION": "2.26.4",
            "CODEQL_JAVA_ALL_VERSION": "9.2.3",
            "CODEQL_JAVA_ALL_SHA": "pack-sha",
            "CODEQL_LINUX_BUNDLE_SHA256": "bundle-sha",
        }
        report = verify_blocked.build_report(scenario, versions, ["ScenarioApplication.java"], [])
        self.assertEqual(report["status"], "blocked")
        self.assertEqual(report["packOffDiagnostic"]["status"], "diagnostic-only")
        self.assertIsNone(report["comparison"]["counts"])
        self.assertIsNone(report["comparison"]["precision"])
        self.assertIsNone(report["comparison"]["recall"])


if __name__ == "__main__":
    unittest.main()
