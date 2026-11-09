"""Optional GitLab artifacts integration; no external dependencies.

A baseline is fetched from the latest successful pipeline on a named ref.
Credentials are read from process environment, never copied to snapshots.
"""

from __future__ import annotations

import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

from .model import SnapshotError, validate_snapshot, write_json

MAX_BASELINE_BYTES = 40_000_000


class GitLabError(RuntimeError):
    """Baseline retrieval failed; never include the request token in messages."""


class _SafeRedirect(urllib.request.HTTPRedirectHandler):
    """Do not forward GitLab auth headers to an artifact CDN or another host."""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        redirected = super().redirect_request(req, fp, code, msg, headers, newurl)
        if redirected is None:
            return None
        old = urllib.parse.urlsplit(req.full_url)
        new = urllib.parse.urlsplit(newurl)
        if new.scheme != "https" and old.scheme == "https":
            raise GitLabError("Refusing HTTPS-to-HTTP artifact redirect")
        if (old.scheme, old.netloc) != (new.scheme, new.netloc):
            sensitive = {"private-token", "job-token", "authorization"}
            for name in list(redirected.headers) + list(redirected.unredirected_hdrs):
                if name.lower() in sensitive:
                    redirected.remove_header(name)
        return redirected


def _api_url(api: str, project: str, ref: str, job: str, artifact: str, allow_http: bool) -> str:
    parsed = urllib.parse.urlsplit(api)
    if (parsed.scheme != "https" and not (allow_http and parsed.scheme == "http")) or not parsed.hostname:
        raise GitLabError("Expected an HTTPS GitLab API URL (HTTP requires --allow-http)")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise GitLabError("Invalid API URL: credentials, query and fragment are not accepted")
    if not re.fullmatch(r"[0-9]+", project):
        raise GitLabError("GitLab project ID must be numeric")
    if not ref or ref in (".", ".."):
        raise GitLabError("Specify a baseline GitLab branch/tag ref")
    if not job or any(ord(c) < 32 for c in job):
        raise GitLabError("Invalid GitLab artifact job name")
    parts = artifact.split("/")
    if not parts or any(part in ("", ".", "..") for part in parts) or artifact.startswith("/"):
        raise GitLabError("Artifact must be a normalized relative path")
    # Encode each segment separately to preserve forward slashes for nested artifacts.
    path = "/".join(urllib.parse.quote(x, safe="") for x in parts)
    query = urllib.parse.urlencode({"job": job})
    return f"{api.rstrip('/')}/projects/{project}/jobs/artifacts/{urllib.parse.quote(ref, safe='')}/raw/{path}?{query}"


def fetch_baseline(
    output: str | Path,
    *,
    api_url: str | None = None,
    project_id: str | None = None,
    ref: str | None = None,
    job: str = "envguard:diagnose",
    artifact: str = "envguard-ci.json",
    allow_http: bool = False,
    opener: Any = None,
) -> dict[str, Any]:
    """Fetch, validate, then atomically publish a GitLab baseline snapshot.

    Explicit ENVGUARD_GITLAB_READ_TOKEN (private access token with minimal read
    permissions) is preferred. CI_JOB_TOKEN may work depending on GitLab tier and
    job-token permission policy. No anonymous/private fallback is attempted.
    """
    api = api_url or os.environ.get("CI_API_V4_URL", "")
    project = project_id or os.environ.get("CI_PROJECT_ID", "")
    branch = ref or os.environ.get("CI_DEFAULT_BRANCH", "")
    token = os.environ.get("ENVGUARD_GITLAB_READ_TOKEN")
    job_token = os.environ.get("CI_JOB_TOKEN") if not token else None
    if not (token or job_token):
        raise GitLabError("Set ENVGUARD_GITLAB_READ_TOKEN or run within an authorized GitLab CI job")
    url = _api_url(api, project, branch, job, artifact, allow_http)
    headers = {"Accept": "application/json", "User-Agent": "EnvGuard/0.2"}
    if token:
        headers["PRIVATE-TOKEN"] = token
    else:
        headers["JOB-TOKEN"] = job_token
    req = urllib.request.Request(url, headers=headers)
    opener = opener or urllib.request.build_opener(_SafeRedirect())
    try:
        with opener.open(req, timeout=20) as response:
            content = response.read(MAX_BASELINE_BYTES + 1)
    except urllib.error.HTTPError as exc:
        if exc.code == 404:
            raise GitLabError("No successful baseline artifact was found on the requested ref") from None
        if exc.code in (401, 403):
            raise GitLabError("GitLab denied access to baseline artifact; check token permissions and edition") from None
        raise GitLabError(f"GitLab artifacts API returned HTTP {exc.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise GitLabError(f"Could not retrieve GitLab baseline ({type(exc).__name__})") from None
    if len(content) > MAX_BASELINE_BYTES:
        raise GitLabError("Baseline artifact exceeds 40 MB")
    try:
        data = validate_snapshot(json.loads(content.decode("utf-8")))
    except (UnicodeError, json.JSONDecodeError, SnapshotError):
        raise GitLabError("GitLab artifact was not a valid EnvGuard snapshot") from None
    dest = Path(output)
    if str(output) == "-":
        write_json(data, "-")
    else:
        dest.parent.mkdir(parents=True, exist_ok=True)
        import tempfile
        tmp = None
        try:
            with tempfile.NamedTemporaryFile(mode="w", encoding="utf-8", dir=dest.parent,
                                             prefix=".envguard-baseline-", suffix=".tmp", delete=False) as fp:
                tmp = Path(fp.name)
                json.dump(data, fp, sort_keys=True, indent=2, ensure_ascii=False)
                fp.write("\n")
            tmp.replace(dest)
        finally:
            if tmp is not None:
                tmp.unlink(missing_ok=True)
    return data
