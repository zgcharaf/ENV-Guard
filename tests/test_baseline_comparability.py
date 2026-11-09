from __future__ import annotations
import copy
import json
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.comparability import assess_targets
from envguard_ci.incident import build_incident

BASE = json.loads((Path(__file__).resolve().parent / "fixtures" / "baseline.json").read_text())


class ComparabilityTests(unittest.TestCase):
    def test_same_target(self):
        x = assess_targets(BASE, copy.deepcopy(BASE))
        self.assertIn(x["status"], ("comparable", "insufficient_metadata"))
        self.assertEqual(x["dimensions_differing"], [])

    def test_other_operating_system_not_comparable(self):
        other = copy.deepcopy(BASE)
        other["platform"]["os"] = "windows" if BASE["platform"]["os"] != "windows" else "linux"
        x = assess_targets(BASE, other)
        self.assertEqual(x["status"], "different_target")
        self.assertIn("os", x["dimensions_differing"])

    def test_different_python_minor_not_comparable(self):
        other = copy.deepcopy(BASE)
        other["runtime"]["version"] = "3.11.9"
        BASE_VERSION = BASE["runtime"].get("version")
        if BASE_VERSION and BASE_VERSION.startswith("3.11."):
            other["runtime"]["version"] = "3.13.1"
        self.assertEqual(assess_targets(BASE, other)["status"], "different_target")

    def test_unsupported_baseline_weakens_package_only_cause(self):
        incident = build_incident({
            "schema_version": "1.0", "status": "drift_detected", "findings": [],
            "ci": {"command_exit_code": 1, "baseline_provided": True,
                   "baseline_comparability": {"status": "different_target"}},
            "failure_analysis": {"observed_failure": "module_missing",
                                 "root_cause_hypothesis": {"code": "MISSING_DISTRIBUTION_AT_RUNTIME", "confidence": "high",
                                                           "summary": "Package missing."}, "evidence": {"import_name": "demo"}},
            "execution_provenance": {"observation": "unknown-wrapper-or-command"},
        })
        self.assertEqual(incident["hypothesis"]["confidence"], "low")
        self.assertEqual(incident["outcome"], "unresolved_environment_cause")
        self.assertTrue(any("different environments" in s for s in incident["uncertainties"]))

if __name__ == "__main__":
    unittest.main()
