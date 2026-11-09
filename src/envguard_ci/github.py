"""Read-only GitHub Actions last-successful-workflow artifact retrieval.

The workflow and artifact names are explicit, and tokens are never written to
reports or forwarded to a different host by HTTP redirects.
"""
from __future__ import annotations

import io
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from typing import Any

from .gitlab import _SafeRedirect
from .model import SnapshotError, validate_snapshot, write_json


class GitHubError(RuntimeError):
    pass


def _repo(value: str) -> str:
    if not re.fullmatch(r"[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+", value or ""):
        raise GitHubError("Expected repository OWNER/REPO")
    return value


def _request_json(opener: Any, url: str, token: str, *, maximum: int = 2_000_000) -> Any:
    req = urllib.request.Request(url, headers={
        "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28", "User-Agent": "EnvGuard-CI/1.0-rc1"})
    try:
        with opener.open(req, timeout=20) as stream:
            payload = stream.read(maximum + 1)
        if len(payload) > maximum:
            raise GitHubError("GitHub API payload exceeded configured limit")
        return json.loads(payload)
    except (urllib.error.HTTPError, urllib.error.URLError, TimeoutError, OSError, UnicodeError, ValueError) as exc:
        raise GitHubError(f"GitHub API request failed ({type(exc).__name__})") from None


def fetch_github_baseline(output: str, *, repo: str | None = None, branch: str | None = None,
                          workflow: str | None = None, artifact_name: str = "envguard-baseline",
                          snapshot_name: str = "envguard-ci.json", opener: Any = None) -> dict[str, Any]:
    """Fetch snapshot from the most recent successful workflow run on branch.

    This is the latest successful matching run, which is not necessarily the
    historical predecessor of a particular failing commit.
    """
    repo = _repo(repo or os.environ.get("GITHUB_REPOSITORY", ""))
    branch = branch or os.environ.get("ENVGUARD_DEFAULT_BRANCH", "")
    workflow = workflow or os.environ.get("ENVGUARD_GITHUB_WORKFLOW", "")
    token = os.environ.get("ENVGUARD_GITHUB_READ_TOKEN") or os.environ.get("GITHUB_TOKEN")
    if not token:
        raise GitHubError("Missing GITHUB_TOKEN or ENVGUARD_GITHUB_READ_TOKEN")
    if not branch or not workflow or len(branch) > 250 or len(workflow) > 250:
        raise GitHubError("Provide --ref and --workflow for the successful baseline")
    if any(x in ("", ".", "..") for x in snapshot_name.split("/")):
        raise GitHubError("Invalid snapshot artifact path")
    if not re.fullmatch(r"[A-Za-z0-9_.-]{1,120}", artifact_name):
        raise GitHubError("Invalid GitHub artifact name")
    opener = opener or urllib.request.build_opener(_SafeRedirect())
    root = f"https://api.github.com/repos/{repo}"
    wf = urllib.parse.quote(workflow, safe="")
    query = urllib.parse.urlencode({"branch": branch, "status": "success", "per_page": 10})
    runs = _request_json(opener, f"{root}/actions/workflows/{wf}/runs?{query}", token)
    if not isinstance(runs, dict) or not isinstance(runs.get("workflow_runs"), list):
        raise GitHubError("Unexpected GitHub workflow runs response")
    for run in runs["workflow_runs"]:
        if not isinstance(run, dict) or run.get("conclusion") != "success" or not isinstance(run.get("id"), int):
            continue
        run_id = run["id"]
        response = _request_json(opener, f"{root}/actions/runs/{run_id}/artifacts?per_page=100", token)
        artifacts = response.get("artifacts") if isinstance(response, dict) else None
        if not isinstance(artifacts, list):
            raise GitHubError("Unexpected GitHub artifacts response")
        for art in artifacts:
            if not isinstance(art, dict) or art.get("name") != artifact_name or art.get("expired") or not isinstance(art.get("id"), int):
                continue
            if art.get("size_in_bytes", 0) > 40_000_000:
                raise GitHubError("GitHub artifact exceeds 40 MB")
            req = urllib.request.Request(f"{root}/actions/artifacts/{art['id']}/zip", headers={
                "Authorization": f"Bearer {token}", "Accept": "application/vnd.github+json",
                "User-Agent": "EnvGuard-CI/1.0-rc1"})
            try:
                with opener.open(req, timeout=20) as stream:
                    blob = stream.read(40_000_001)
                if len(blob) > 40_000_000:
                    raise GitHubError("Downloaded artifact exceeded 40 MB")
                with zipfile.ZipFile(io.BytesIO(blob)) as z:
                    names = z.namelist()
                    if names.count(snapshot_name) != 1:
                        raise GitHubError("GitHub artifact has missing/duplicate snapshot")
                    item = z.getinfo(snapshot_name)
                    if item.file_size > 40_000_000:
                        raise GitHubError("Snapshot exceeds 40 MB")
                    snapshot = validate_snapshot(json.loads(z.read(item)))
            except (zipfile.BadZipFile, UnicodeError, json.JSONDecodeError, SnapshotError, OSError,
                    urllib.error.URLError, urllib.error.HTTPError) as exc:
                raise GitHubError(f"Invalid GitHub snapshot artifact ({type(exc).__name__})") from None
            write_json(snapshot, output)
            return snapshot
    raise GitHubError("No successful workflow snapshot artifact found on requested branch")
