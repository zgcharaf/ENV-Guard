"""Cause-versus-symptom checks for EnvGuard 2.0."""
from __future__ import annotations

import copy
import json
import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.collection import snapshot
from envguard_ci.failure import diagnose_failure
from envguard_ci.model import fingerprint, read_snapshot
from envguard_ci.provenance import execution_context, invoked_python

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures" / "baseline.json"


class ProvenanceV2Test(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.baseline = read_snapshot(FIX)

    def _missing(self):
        curr = copy.deepcopy(self.baseline)
        name = curr["packages"].pop(0)["name"]
        curr["fingerprints"] = fingerprint(curr)
        return curr, name

    def test_wrong_interpreter_with_explicit_target_and_installed_package(self):
        curr, name = self._missing()
        ctx = execution_context(expected_python="/opt/expected/bin/python",
                                invoked_python_path="/opt/empty/bin/python")
        report = diagnose_failure(self.baseline, curr,
                   log=f"ModuleNotFoundError: No module named '{name}'", exit_code=1,
                   execution=ctx, expected_snapshot=self.baseline)
        self.assertEqual(report["root_cause_hypothesis"]["code"], "WRONG_PYTHON_INTERPRETER")
        self.assertNotIn("/opt/expected", json.dumps(report))
        self.assertEqual(ctx["interpreter_match"], False)

    def test_missing_dependency_when_expected_interpreter_used(self):
        curr, name = self._missing()
        ctx = execution_context(expected_python="/opt/expected/bin/python",
                                invoked_python_path="/opt/expected/bin/python")
        report = diagnose_failure(self.baseline, curr,
                   log=f"ModuleNotFoundError: No module named '{name}'", exit_code=1,
                   execution=ctx, expected_snapshot=curr)
        self.assertEqual(report["root_cause_hypothesis"]["code"], "MISSING_DISTRIBUTION_AT_RUNTIME")

    def test_no_wrong_interpreter_without_proof_of_expected_install(self):
        curr, name = self._missing()
        ctx = execution_context(expected_python="/opt/expected/bin/python",
                                invoked_python_path="/opt/empty/bin/python")
        report = diagnose_failure(self.baseline, curr,
                   log=f"ModuleNotFoundError: No module named '{name}'", exit_code=1,
                   execution=ctx, expected_snapshot=curr)
        self.assertNotEqual(report["root_cause_hypothesis"]["code"], "WRONG_PYTHON_INTERPRETER")

    def test_site_flag_changes_diagnosis_with_same_package_set(self):
        name = self.baseline["packages"][0]["name"]
        ctx = execution_context(command=[sys.executable, "-S", "-m", name],
                                expected_python=sys.executable)
        report = diagnose_failure(self.baseline, self.baseline,
                   log=f"python: No module named {name}", exit_code=1,
                   execution=ctx, expected_snapshot=self.baseline)
        self.assertEqual(report["root_cause_hypothesis"]["code"], "PYTHON_SITE_DISABLED")

    def test_site_flag_after_m_is_application_arg_not_python_flag(self):
        ctx = execution_context(command=[sys.executable, "-m", "thing", "-S"],
                                expected_python=sys.executable)
        self.assertFalse(ctx["flags"]["site_disabled"])

    def test_shell_wrapper_is_unknown_not_attributed(self):
        ctx = execution_context(command=["sh", "-c", "python -m x"],
                                expected_python=sys.executable)
        self.assertIsNone(ctx["interpreter_match"])
        self.assertIsNone(ctx["executed_python"])
        self.assertEqual(ctx["observation"], "unknown-wrapper-or-command")

    @unittest.skipIf(sys.platform == "win32", "Windows symlink creation requires developer mode or elevated privileges")
    def test_venv_symlinks_do_not_collapse_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            p1 = Path(tmp) / "first" / "bin" / "python"
            p2 = Path(tmp) / "second" / "bin" / "python"
            p1.parent.mkdir(parents=True)
            p2.parent.mkdir(parents=True)
            p1.symlink_to(sys.executable)
            p2.symlink_to(sys.executable)
            ctx = execution_context(expected_python=str(p1), invoked_python_path=str(p2), project=tmp)
            self.assertEqual(ctx["interpreter_match"], False)
            self.assertIn("$PROJECT/", ctx["expected_python"]["label"])

    def test_snapshot_contains_no_absolute_home_or_full_system_python_path(self):
        snap = snapshot(ROOT, python=sys.executable)
        prov = snap["runtime"]["provenance"]
        self.assertTrue(prov["executable"]["id"].startswith("sha256:"))
        self.assertTrue(isinstance(prov["import_owners"], dict))
        self.assertNotIn(str(Path.home()), json.dumps(snap))
        self.assertNotIn(sys.executable, json.dumps(snap))

    def test_canonical_runtime_fingerprint_not_machine_path_dependent(self):
        snap = snapshot(ROOT, python=sys.executable)
        other = copy.deepcopy(snap)
        other["runtime"]["provenance"]["executable"]["id"] = "sha256:replacement"
        self.assertEqual(fingerprint(snap)["runtime"], fingerprint(other)["runtime"])


if __name__ == "__main__":
    unittest.main()
