from __future__ import annotations

import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.cli import main

ROOT = Path(__file__).resolve().parents[1]


class CIEvidenceV2Test(unittest.TestCase):
    def test_ci_run_classifies_real_missing_module_without_raw_logs_in_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            manifest, report = Path(tmp) / "ci.json", Path(tmp) / "report.json"
            with contextlib.redirect_stdout(io.StringIO()) as out:
                rc = main(["ci-run", "--project", str(ROOT), "--python", sys.executable,
                           "--snapshot-out", str(manifest), "--report-out", str(report),
                           "--", sys.executable, "-m", "unlikely_nonexistent_envguard_2_test_module"])
            self.assertNotEqual(rc, 0)
            data = json.loads(report.read_text(encoding="utf-8"))
            self.assertEqual(data["ci"]["command_exit_code"], rc)
            self.assertEqual(data["failure_analysis"]["observed_failure"], "module_missing")
            self.assertEqual(data["execution_provenance"]["interpreter_match"], True)
            self.assertNotIn("unlikely_nonexistent_envguard_2_test_module", json.dumps(data.get("ci")))
            self.assertEqual(data["failure_analysis"]["root_cause_hypothesis"]["code"], "PYTHON_IMPORT_FAILURE")

    def test_ci_run_success_has_no_failure_hypothesis(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            with contextlib.redirect_stdout(io.StringIO()):
                rc = main(["ci-run", "--project", str(ROOT), "--python", sys.executable,
                           "--snapshot-out", str(Path(tmp) / "ci.json"), "--report-out", str(report),
                           "--", sys.executable, "-c", "print('CI-OK')"])
            self.assertEqual(rc, 0)
            self.assertIsNone(json.loads(report.read_text())["failure_analysis"])

    def test_ci_run_does_not_mask_missing_command_exit_127(self):
        with tempfile.TemporaryDirectory() as tmp:
            report = Path(tmp) / "report.json"
            rc = main(["ci-run", "--project", str(ROOT),
                       "--snapshot-out", str(Path(tmp) / "ci.json"), "--report-out", str(report),
                       "--", "envguard-executable-that-does-not-exist"])
            self.assertEqual(rc, 127)
            self.assertEqual(json.loads(report.read_text())["ci"]["command_exit_code"], 127)


if __name__ == "__main__":
    unittest.main()
