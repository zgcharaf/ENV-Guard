from __future__ import annotations

import copy
import contextlib
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.cli import main
from envguard_ci.reporting import render, gitlab_codequality, github_annotations


def example_report():
    return {"status": "drift_detected", "schema_version": "1.0",
            "ci": {"command_exit_code": 1},
            "failure_analysis": {"root_cause_hypothesis": {
                "code": "WRONG_PYTHON_INTERPRETER", "summary": "Wrong runtime",
                "recommendation": "Use the intended .venv"}},
            "findings": [{"code": "PACKAGE_MISSING", "severity": "high",
                          "summary": "Dependency missing", "recommendation": "Install it"}]}


class ReportingV2Test(unittest.TestCase):
    def test_gitlab_minimum_schema_and_stable_fingerprints(self):
        output = gitlab_codequality(example_report(), anchor="pyproject.toml")
        self.assertEqual(len(output), 2)
        for finding in output:
            self.assertEqual(set(finding), {"check_name", "description", "fingerprint", "location", "severity"})
            self.assertEqual(finding["location"]["path"], "pyproject.toml")
            self.assertEqual(finding["location"]["lines"], {"begin": 1})
            self.assertRegex(finding["fingerprint"], r"^[a-f0-9]{64}$")
            self.assertIn("synthetic anchor", finding["description"])
        self.assertEqual(output, gitlab_codequality(copy.deepcopy(example_report())))

    def test_gitlab_reject_absolute_and_parent_paths(self):
        for bad in ("/etc/shadow", "../secret", "foo/../baz", "x//file", "C:/Users/test/file"):
            with self.subTest(bad=bad), self.assertRaises(ValueError):
                gitlab_codequality(example_report(), anchor=bad)

    def test_github_annotation_escapes_log_injection(self):
        report = example_report()
        report["findings"][0]["summary"] = "oops\n::error::injected\r100%"
        output = github_annotations(report)
        self.assertEqual(output.count("\n"), 2)
        self.assertIn("::error::injected", output)  # *encoded inside data*, not a new annotation
        self.assertIn("%25", output)
        self.assertNotIn("\r", output)
        self.assertEqual(sum(line.startswith("::error title=EnvGuard_") for line in output.splitlines()), 2)

    def test_cli_render_to_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            inp = Path(tmp) / "in.json"
            out = Path(tmp) / "codequality.json"
            inp.write_text(json.dumps(example_report()), encoding="utf-8")
            self.assertEqual(main(["render-report", "--input", str(inp), "--format", "gitlab-codequality", "--out", str(out)]), 0)
            self.assertEqual(len(json.loads(out.read_text())), 2)
            md = Path(tmp) / "report.md"
            self.assertEqual(main(["render-report", "--input", str(inp), "--format", "markdown", "--out", str(md)]), 0)
            self.assertIn("WRONG_PYTHON_INTERPRETER", md.read_text())
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                self.assertEqual(main(["render-report", "--input", str(inp), "--format", "github-annotations"]), 0)
            self.assertIn("::error title=EnvGuard_WRONG_PYTHON_INTERPRETER::", buf.getvalue())

    def test_unclassified_failure_generates_no_fake_root_cause(self):
        report = example_report()
        report["failure_analysis"] = {"root_cause_hypothesis": None}
        report["findings"] = []
        self.assertEqual(gitlab_codequality(report), [])
        self.assertIn("No findings", render(report, "markdown"))


if __name__ == "__main__":
    unittest.main()
