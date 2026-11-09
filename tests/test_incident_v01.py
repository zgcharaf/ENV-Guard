"""Open-alpha incident dossier behavioral and safety guarantees."""
from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from envguard_ci.cli import main
from envguard_ci.incident import build_incident, render_markdown


def sample(*, code="WRONG_PYTHON_INTERPRETER", exit_code=1, observed="module_missing",
           known=True, baseline=True):
    return {
        "schema_version": "1.0", "status": "drift_detected", "findings": [
            {"code": "PACKAGE_MISSING", "severity": "high", "summary": "Baseline wheel absent"}
        ],
        "ci": {"command_exit_code": exit_code, "baseline_provided": baseline},
        "execution_provenance": {
            "observation": "direct-python-argv" if known else "unknown-wrapper",
            "explicit_expected": bool(known), "interpreter_match": False if known else None,
            "expected_python": {"label": "$PROJECT/.venv/bin/python"},
            "executed_python": {"label": "/usr/bin/python"},
        },
        "failure_analysis": {
            "observed_failure": observed,
            "root_cause_hypothesis": ({"code": code, "confidence": "high",
                                       "summary": "Used another interpreter."} if code else None),
            "evidence": {"import_name": "riskbatch"},
        },
        "fingerprints": {"runtime": "sha256:fake", "spec": "sha256:anotherfake"},
    }


class IncidentDossierTests(unittest.TestCase):
    def test_wrong_interpreter_supported_with_source_pointers(self):
        incident = build_incident(sample())
        self.assertEqual(incident["outcome"], "supported_hypothesis")
        self.assertEqual(incident["hypothesis"]["confidence"], "high")
        self.assertTrue(any(x["source"] == "/execution_provenance/interpreter_match" for x in incident["evidence"]))
        self.assertTrue(incident["baseline_provided"])
        self.assertFalse(incident["patch_validated"])
        self.assertFalse(incident["automatic_changes_made"])
        self.assertTrue(all(not x["verified"] for x in incident["checks"]))

    def test_unobserved_interpreter_must_not_be_high_confidence(self):
        i = build_incident(sample(known=False))
        self.assertEqual(i["hypothesis"]["confidence"], "low")
        self.assertEqual(i["outcome"], "unresolved_environment_cause")
        self.assertTrue(any("not directly observed" in x for x in i["uncertainties"]))

    def test_missing_module_without_evidence_is_unresolved(self):
        i = build_incident(sample(code="PYTHON_IMPORT_FAILURE", known=False, baseline=False))
        self.assertEqual(i["outcome"], "unresolved_environment_cause")
        self.assertTrue(any("No known-good CI baseline" in x for x in i["uncertainties"]))

    def test_unrelated_failure_not_misclassified(self):
        i = build_incident(sample(code=None, observed=None, exit_code=1))
        self.assertEqual(i["outcome"], "unclassified_failure")
        self.assertIsNone(i["hypothesis"]["code"])
        self.assertTrue(any("may be unrelated" in x for x in i["uncertainties"]))

    def test_success_has_no_remediation(self):
        i = build_incident(sample(code=None, observed=None, exit_code=0))
        self.assertEqual(i["outcome"], "command_succeeded")
        self.assertFalse(i["checks"])

    def test_log_injection_and_raw_argv_not_carried(self):
        x = sample()
        x["failure_analysis"]["root_cause_hypothesis"]["summary"] = "x\n## EVIL\x1b[31m <img src=x>"
        x["secret_api_key"] = "SECRET-WOULD-BE-BAD"
        x["execution_provenance"]["argv"] = ["python", "--token", "PRIVATE-TOKEN"]
        md = render_markdown(build_incident(x))
        self.assertNotIn("\n## EVIL", md)
        self.assertNotIn("SECRET-WOULD-BE-BAD", md)
        self.assertNotIn("PRIVATE-TOKEN", md)
        self.assertNotIn("<img", md)
        self.assertNotIn("\x1b", md)

    def test_malformed_json_fields_are_rejected(self):
        x = sample()
        x["failure_analysis"]["evidence"] = ["unexpected-list"]
        with self.assertRaisesRegex(ValueError, "Invalid failure analysis"):
            build_incident(x)
        x = sample()
        x["failure_analysis"] = ["unexpected-list"]
        with self.assertRaisesRegex(ValueError, "Invalid CI diagnostic"):
            build_incident(x)

    def test_deterministic_incident_id(self):
        self.assertEqual(build_incident(sample())["incident_id"], build_incident(sample())["incident_id"])

    def test_cli_triage_json_and_markdown(self):
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            rpt = d / "report.json"
            rpt.write_text(json.dumps(sample()), encoding="utf-8")
            markdown, jpath = d / "incident.md", d / "incident.json"
            self.assertEqual(main(["triage", "--report", str(rpt), "--out", str(markdown)]), 0)
            self.assertEqual(main(["triage", "--report", str(rpt), "--format", "json", "--out", str(jpath)]), 0)
            self.assertIn("Evidence ledger", markdown.read_text())
            self.assertEqual(json.loads(jpath.read_text())["schema_version"], "0.1.0")

    def test_cli_run_auto_writes_incident_even_when_command_fails(self):
        import sys
        with tempfile.TemporaryDirectory() as tmp:
            d = Path(tmp)
            snapshot = d / "ci.json"
            report = d / "report.json"
            code = main(["ci-run", "--project", str(d), "--python", sys.executable,
                         "--snapshot-out", str(snapshot), "--report-out", str(report),
                         "--", sys.executable, "-m", "__this_module_is_intentionally_absent__"])
            self.assertNotEqual(code, 0)
            md = report.with_suffix(".md")
            self.assertTrue(report.is_file())
            self.assertTrue(md.is_file())
            content = md.read_text()
            self.assertIn("unresolved", content)
            self.assertIn("No dependency changes were made", content)


if __name__ == "__main__":
    unittest.main()
