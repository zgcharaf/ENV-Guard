"""GitLab baseline API and failure-preserving CI runner tests (no network)."""

from __future__ import annotations

import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import urllib.error
import urllib.request
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.cli import main
from envguard_ci.gitlab import GitLabError, _SafeRedirect, _api_url, fetch_baseline
from envguard_ci.model import read_snapshot

ROOT = Path(__file__).resolve().parents[1]
BASE = ROOT / "tests" / "fixtures" / "baseline.json"


class MockResponse:
    def __init__(self, content: bytes):
        self.content = content
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        pass
    def read(self, size):
        return self.content[:size]


class MockOpener:
    def __init__(self, content: bytes | None, fail_code: int | None = None):
        self.content = content
        self.fail_code = fail_code
        self.request = None
    def open(self, request, timeout=None):
        self.request = request
        if self.fail_code:
            raise urllib.error.HTTPError(request.full_url, self.fail_code, "failure", None, None)
        return MockResponse(self.content)


class GitLabTests(unittest.TestCase):
    def test_api_url_gitlab_encoded(self):
        self.assertEqual(_api_url("https://gitlab.example.com/api/v4", "42", "release/v1", "envguard:diagnose", "reports/envguard-ci.json", False),
            "https://gitlab.example.com/api/v4/projects/42/jobs/artifacts/release%2Fv1/raw/reports/envguard-ci.json?job=envguard%3Adiagnose")
        for bad in ("../x.json", "/tmp/a.json", "a//x.json"):
            with self.assertRaises(GitLabError):
                _api_url("https://gitlab.example.com/api/v4", "42", "main", "job", bad, False)
        with self.assertRaises(GitLabError):
            _api_url("http://gitlab.example.com/api/v4", "42", "main", "job", "x.json", False)

    def test_fetch_baseline_validate_and_atomic_save(self):
        opener = MockOpener(BASE.read_bytes())
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"ENVGUARD_GITLAB_READ_TOKEN": "mock-secret"}):
            dest = Path(d) / "baseline.json"
            res = fetch_baseline(dest, api_url="https://gitlab.example.com/api/v4", project_id="42", ref="main", opener=opener)
            self.assertEqual(res["schema_version"], "1.0")
            self.assertEqual(read_snapshot(dest)["fingerprints"], res["fingerprints"])
            self.assertEqual(opener.request.get_header("Private-token"), "mock-secret")
            self.assertNotIn("mock-secret", dest.read_text())

    def test_missing_artifact_does_not_create_baseline(self):
        opener = MockOpener(None, 404)
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"ENVGUARD_GITLAB_READ_TOKEN": "mock-secret"}):
            dest = Path(d) / "baseline.json"
            with self.assertRaisesRegex(GitLabError, "No successful baseline"):
                fetch_baseline(dest, api_url="https://gitlab.example.com/api/v4", project_id="42", ref="main", opener=opener)
            self.assertFalse(dest.exists())

    def test_invalid_artifact_not_written(self):
        opener = MockOpener(b"<html>login required</html>")
        with tempfile.TemporaryDirectory() as d, patch.dict(os.environ, {"ENVGUARD_GITLAB_READ_TOKEN": "mock-secret"}):
            dest = Path(d) / "baseline.json"
            with self.assertRaisesRegex(GitLabError, "not a valid"):
                fetch_baseline(dest, api_url="https://gitlab.example.com/api/v4", project_id="42", ref="main", opener=opener)
            self.assertFalse(dest.exists())

    def test_redirect_strips_auth_when_host_changes(self):
        req = urllib.request.Request("https://gitlab.example.com/api/v4/foo", headers={"JOB-TOKEN": "secret", "PRIVATE-TOKEN": "also-secret"})
        redirect = _SafeRedirect().redirect_request(req, None, 302, "Found", {}, "https://cdn.example.org/artifact.json")
        self.assertNotIn("Job-token", redirect.headers)
        self.assertNotIn("Private-token", redirect.headers)
        with self.assertRaises(GitLabError):
            _SafeRedirect().redirect_request(req, None, 302, "Found", {}, "http://cdn.example.org/insecure")

    def test_ci_run_failed_command_still_emits_snapshot_and_report(self):
        with tempfile.TemporaryDirectory() as d:
            sn = Path(d) / "envguard-ci.json"
            report = Path(d) / "envguard-report.json"
            code = main(["ci-run", "--project", str(ROOT), "--snapshot-out", str(sn), "--report-out", str(report),
                         "--", sys.executable, "-c", "raise SystemExit(7)"])
            self.assertEqual(code, 7)
            self.assertEqual(read_snapshot(sn)["schema_version"], "1.0")
            obj = json.loads(report.read_text())
            self.assertEqual(obj["ci"]["command_exit_code"], 7)
            self.assertEqual(obj["ci"]["diagnostic_mode"], "doctor")

    def test_ci_run_success_with_baseline_and_no_exit_masking(self):
        with tempfile.TemporaryDirectory() as d:
            sn = Path(d) / "envguard-ci.json"
            report = Path(d) / "envguard-report.json"
            code = main(["ci-run", "--project", str(ROOT), "--snapshot-out", str(sn), "--report-out", str(report),
                         "--baseline", str(BASE), "--", sys.executable, "-c", "print('ok')"])
            self.assertEqual(code, 0)
            obj = json.loads(report.read_text())
            self.assertTrue(obj["ci"]["baseline_provided"])
            self.assertEqual(obj["ci"]["diagnostic_mode"], "diff")


if __name__ == "__main__":
    unittest.main()
