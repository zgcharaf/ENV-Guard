"""Public-release behavior: crash-consistent artifacts, privacy, exit codes."""
from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from envguard_ci.ci import run_ci
from envguard_ci.collection import CollectionError, snapshot
from envguard_ci.incident import build_incident
from envguard_ci.model import write_json
from envguard_ci.project import inspect_project
from envguard_ci.reporting import render


class ReleaseReliabilityTests(unittest.TestCase):
    def test_json_atomic_replacement_and_validity(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "nested" / "report.json"
            write_json({"status": "first", "number": 1}, output)
            write_json({"status": "second", "number": 2}, output)
            self.assertEqual(json.loads(output.read_text())["status"], "second")
            self.assertFalse(list(output.parent.glob(".envguard-*.tmp")))

    def test_json_write_failure_preserves_existing_document(self):
        with tempfile.TemporaryDirectory() as tmp:
            output = Path(tmp) / "report.json"
            output.write_text('{"original": true}\n', encoding="utf-8")
            with patch("envguard_ci.model.os.replace", side_effect=OSError("simulated disk failure")):
                with self.assertRaises(OSError):
                    write_json({"new": True}, output)
            self.assertEqual(json.loads(output.read_text()), {"original": True})
            self.assertFalse(list(Path(tmp).glob(".envguard-*.tmp")))

    def test_probing_error_does_not_expose_stderr(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("envguard_ci.collection.subprocess.run", return_value=SimpleNamespace(
                returncode=1, stdout="", stderr="my-private-token=SECRET-123")):
                with self.assertRaises(CollectionError) as problem:
                    snapshot(tmp, python=sys.executable)
            self.assertNotIn("SECRET-123", str(problem.exception))
            self.assertIn("stderr withheld", str(problem.exception))

    def test_large_project_file_is_rejected_before_reading(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "requirements.txt"
            with target.open("wb") as stream:
                stream.truncate(40_000_001)
            with self.assertRaisesRegex(ValueError, "exceeds 40 MB"):
                inspect_project(Path(tmp))

    def test_failed_collection_preserves_failing_command_and_dossier(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            report = root / "report.json"
            current = root / "snapshot.json"
            with patch("envguard_ci.ci.snapshot", side_effect=CollectionError("private-token-internal")):
                code = run_ci([sys.executable, "-c", "raise SystemExit(27)"],
                              project=tmp, python=sys.executable,
                              report_out=str(report), snapshot_out=str(current))
            self.assertEqual(code, 27)
            self.assertFalse(current.exists())
            data = json.loads(report.read_text())
            self.assertEqual(data["status"], "collection_failed")
            self.assertFalse(data["ci"]["analysis_complete"])
            self.assertFalse(data["ci"]["snapshot_available"])
            self.assertEqual(data["ci"]["command_exit_code"], 27)
            self.assertNotIn("private-token-internal", report.read_text())
            dossier = report.with_suffix(".md")
            self.assertTrue(dossier.exists())
            self.assertIn("collection\\_failed", dossier.read_text())
            self.assertIn("Not applicable", dossier.read_text())
            self.assertEqual(build_incident(data)["outcome"], "collection_failed")
            self.assertIn("ENVIRONMENT_COLLECTION_FAILED", render(data, "markdown"))

    def test_failed_collection_after_success_marks_diagnostic_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch("envguard_ci.ci.snapshot", side_effect=CollectionError("unavailable")):
                code = run_ci([sys.executable, "-c", "pass"], project=tmp,
                              report_out=str(Path(tmp) / "report.json"))
            self.assertEqual(code, 2)
            data = json.loads((Path(tmp) / "report.json").read_text())
            self.assertEqual(data["ci"]["command_exit_code"], 0)

    def test_actual_missing_executable_exit_code_remains_127(self):
        with tempfile.TemporaryDirectory() as tmp:
            code = run_ci(["envguard-ci-no-such-binary-release-check"],
                          project=tmp, report_out=str(Path(tmp) / "report.json"),
                          snapshot_out=str(Path(tmp) / "snapshot.json"))
            self.assertEqual(code, 127)
            self.assertEqual(json.loads((Path(tmp) / "report.json").read_text())["ci"]["command_exit_code"], 127)


if __name__ == "__main__":
    unittest.main()
