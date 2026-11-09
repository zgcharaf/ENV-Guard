"""Conservative installer error recognizers (text classified; causes not fabricated)."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.failure import diagnose_failure
from envguard_ci.model import read_snapshot

BASE = read_snapshot(Path(__file__).parent / "fixtures" / "baseline.json")


class InstallerV2Test(unittest.TestCase):
    def test_pip_missing_distribution(self):
        d = diagnose_failure(BASE, BASE, log="ERROR: No matching distribution found for scorecodec==99.0", exit_code=1)
        self.assertEqual(d["root_cause_hypothesis"]["code"], "PACKAGE_RESOLUTION_UNAVAILABLE")
        self.assertEqual(d["evidence"]["distribution_requested"], "scorecodec")

    def test_pip_resolution_conflict(self):
        d = diagnose_failure(BASE, BASE, log="ERROR: Cannot install A and B because these package versions have conflicting dependencies.\nERROR: ResolutionImpossible", exit_code=1)
        self.assertEqual(d["root_cause_hypothesis"]["code"], "DEPENDENCY_RESOLUTION_CONFLICT")

    def test_uv_and_poetry_conflicts(self):
        for raw in ("× No solution found when resolving dependencies:", "Because A depends on B, version solving failed."):
            with self.subTest(log=raw):
                d = diagnose_failure(BASE, BASE, log=raw, exit_code=1)
                self.assertEqual(d["root_cause_hypothesis"]["code"], "DEPENDENCY_RESOLUTION_CONFLICT")

    def test_failed_wheel_build(self):
        d = diagnose_failure(BASE, BASE, log="ERROR: Failed building wheel for example-native", exit_code=1)
        self.assertEqual(d["root_cause_hypothesis"]["code"], "WHEEL_BUILD_FAILED")

    def test_versioned_cpp_symbol(self):
        d = diagnose_failure(BASE, BASE, log="ImportError: /usr/lib/libstdc++.so.6: version `GLIBCXX_3.4.30' not found", exit_code=1)
        self.assertEqual(d["root_cause_hypothesis"]["code"], "NATIVE_SYMBOL_VERSION_MISSING")
        self.assertNotIn("/usr/lib", str(d["evidence"]))

    def test_windows_dll_error(self):
        d = diagnose_failure(BASE, BASE, log="ImportError: DLL load failed while importing _mylib: The specified module could not be found.", exit_code=1)
        self.assertEqual(d["root_cause_hypothesis"]["code"], "WINDOWS_DLL_LOAD_FAILURE")

    def test_successful_command_not_diagnosed_from_prior_error_text(self):
        d = diagnose_failure(BASE, BASE, log="ERROR: No matching distribution found for fake", exit_code=0)
        self.assertIsNone(d["root_cause_hypothesis"])


if __name__ == "__main__":
    unittest.main()
