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
from envguard_ci.collection import snapshot
from envguard_ci.diagnostics import doctor
from envguard_ci.project import inspect_project

ROOT = Path(__file__).resolve().parents[1]
FIX = ROOT / "tests" / "fixtures"


class IntegrationTests(unittest.TestCase):
    def test_project_detection(self):
        project = inspect_project(ROOT)
        self.assertIn("pyproject.toml", [f["name"] for f in project["files"]])
        self.assertEqual(project["requires_python"], ">=3.11")

    def test_inspect_actual_interpreter_without_installation(self):
        result = snapshot(ROOT, python=sys.executable)
        self.assertTrue(result["packages"])
        self.assertTrue(result["runtime"]["version"])
        self.assertIn(result["platform"]["os"], ("linux", "darwin", "windows"))
        self.assertEqual(result["native"]["scan_status"], "disabled")
        # A developer's actual interpreter may already contain inconsistent
        # dependencies (for example a package demanding an older Pillow).
        # Collection should faithfully diagnose, not assume it is pristine.
        self.assertNotIn("FINGERPRINT_INVALID", [f["code"] for f in doctor(result)["findings"]])

    def test_cli_snapshot_and_diff_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "actual.json"
            self.assertEqual(main(["snapshot", "--project", str(ROOT), "--out", str(file)]), 0)
            actual = json.loads(file.read_text(encoding="utf-8"))
            self.assertEqual(actual["schema_version"], "1.0")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                status = main(["diff", "--baseline", str(FIX / "baseline.json"),
                               "--current", str(FIX / "version_drift.json"),
                               "--format", "json", "--fail-on", "medium"])
            self.assertEqual(status, 1)
            self.assertIn("PACKAGE_VERSION_DRIFT", [f["code"] for f in json.loads(buf.getvalue())["findings"]])

    def test_cli_non_drifting_snapshot_returns_zero(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            status = main(["diff", "--baseline", str(FIX / "baseline.json"),
                           "--current", str(FIX / "baseline.json"), "--fail-on", "high"])
        self.assertEqual(status, 0)


if __name__ == "__main__":
    unittest.main()
