from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.failure import diagnose_failure
from envguard_ci.diagnostics import doctor
from envguard_ci.model import fingerprint, read_snapshot

FIX = Path(__file__).parent / "fixtures"


class FailureClassificationTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = read_snapshot(FIX / "baseline.json")

    def test_import_missing_with_correlated_distribution(self):
        bad = copy.deepcopy(self.baseline)
        missing_package = bad["packages"].pop(0)["name"]
        bad["fingerprints"] = fingerprint(bad)
        message = f'Traceback\nModuleNotFoundError: No module named \'{missing_package}\''
        diagnosis = diagnose_failure(self.baseline, bad, log=message, exit_code=1)
        self.assertEqual(diagnosis["root_cause_hypothesis"]["code"], "MISSING_DISTRIBUTION_AT_RUNTIME")
        self.assertIn("PACKAGE_MISSING", diagnosis["environment_correlations"])

    def test_python_m_no_traceback(self):
        name = self.baseline["packages"][0]["name"]
        bad = copy.deepcopy(self.baseline)
        bad["packages"] = [p for p in bad["packages"] if p["name"] != name]
        bad["fingerprints"] = fingerprint(bad)
        report = diagnose_failure(self.baseline, bad,
                                  log=f"/usr/local/bin/python: No module named {name}", exit_code=1)
        self.assertEqual(report["root_cause_hypothesis"]["code"], "MISSING_DISTRIBUTION_AT_RUNTIME")

    def test_native_library_redacts_absolute_path(self):
        log = "OSError: /home/private/user/libopaque.so: cannot open shared object file: No such file or directory"
        report = diagnose_failure(self.baseline, self.baseline, log=log, exit_code=1)
        self.assertEqual(report["root_cause_hypothesis"]["code"], "NATIVE_LIBRARY_LOAD_FAILURE")
        self.assertEqual(report["evidence"], {"library": "libopaque.so"})
        self.assertNotIn("/home/private/", str(report))

    def test_native_missing_symbol(self):
        report = diagnose_failure(self.baseline, self.baseline,
                                  log="AttributeError: /tmp/libscoremath.so: undefined symbol: score_native", exit_code=1)
        self.assertEqual(report["root_cause_hypothesis"]["code"], "NATIVE_SYMBOL_LOAD_FAILURE")

    def test_no_causal_claim_when_nonzero_without_signature(self):
        report = diagnose_failure(self.baseline, self.baseline, log="AssertionError: business rule", exit_code=1)
        self.assertIsNone(report["root_cause_hypothesis"])

    def test_success_does_not_attribute_errors_from_log(self):
        report = diagnose_failure(self.baseline, self.baseline,
                                  log="ModuleNotFoundError: No module named 'other'", exit_code=0)
        self.assertIsNone(report["root_cause_hypothesis"])

    def test_version_constraint_in_project(self):
        current = copy.deepcopy(self.baseline)
        pkg_name = current["packages"][0]["name"]
        current["project"]["dependencies"] = [pkg_name + ">=99.0,<100.0"]
        current["fingerprints"] = fingerprint(current)
        self.assertIn("UNSATISFIED_VERSION_CONSTRAINT", [f["code"] for f in doctor(current)["findings"]])

    def test_logs_capped(self):
        with self.assertRaisesRegex(ValueError, "2 MB"):
            diagnose_failure(self.baseline, self.baseline, log="a" * 2_000_001, exit_code=1)


if __name__ == "__main__":
    unittest.main()
