from __future__ import annotations

import copy
import json
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.diagnostics import diff, doctor, supports_python
from envguard_ci.model import fingerprint, read_snapshot

FIX = Path(__file__).parent / "fixtures"


class DiagnosticsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.base = read_snapshot(FIX / "baseline.json")
        cls.cases = json.loads((FIX / "cases.json").read_text())

    def test_baseline_clean(self):
        result = doctor(self.base)
        self.assertEqual(result["findings"], [])

    def test_each_fixture_has_expected_failure(self):
        for fixture, expected in self.cases.items():
            with self.subTest(fixture=fixture):
                data = read_snapshot(FIX / f"{fixture}.json")
                result = diff(self.base, data)
                self.assertIn(expected, [finding["code"] for finding in result["findings"]])
                self.assertIn(result["status"], ("drift_detected", "no_significant_drift_detected"))

    def test_same_snapshot_is_unchanged(self):
        actual = diff(self.base, self.base)
        self.assertEqual(actual["findings"], [])
        self.assertEqual(actual["status"], "no_significant_drift_detected")

    def test_skip_optional_and_marker_dependencies(self):
        sample = copy.deepcopy(self.base)
        sample["packages"][1]["requires"] = ["not-installed; python_version < '3'", "other-lib @ https://example.com/a.whl"]
        sample["fingerprints"] = fingerprint(sample)
        self.assertNotIn("UNSATISFIED_RUNTIME_DEPENDENCY", [f["code"] for f in doctor(sample)["findings"]])

    def test_unknown_native_scan_does_not_invent_missing_libraries(self):
        sample = copy.deepcopy(self.base)
        sample["native"] = {"scan_status": "partial", "libraries": [],
                            "requirements": [{"extension": "x.so", "needed": ["libmissing.so"]}]}
        sample["fingerprints"] = fingerprint(sample)
        self.assertNotIn("NATIVE_LIBRARY_UNRESOLVED", [f["code"] for f in doctor(sample)["findings"]])

    def test_invalid_fingerprint_is_flagged(self):
        sample = copy.deepcopy(self.base)
        sample["runtime"]["version"] = "3.13.5"
        self.assertIn("FINGERPRINT_INVALID", [f["code"] for f in doctor(sample)["findings"]])

    def test_python_constraints(self):
        self.assertTrue(supports_python(">=3.11,<3.14", "3.13.5"))
        self.assertFalse(supports_python(">=3.12", "3.11.9"))
        self.assertFalse(supports_python("==3.11", "3.12.0"))
        self.assertFalse(supports_python("==3.13", "3.13.5"))
        self.assertTrue(supports_python("==3.13.*", "3.13.5"))
        self.assertTrue(supports_python("~=3.11", "3.13.5"))


if __name__ == "__main__":
    unittest.main()
