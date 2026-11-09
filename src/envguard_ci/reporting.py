"""Deterministic CI presentation formats; never executes code or calls APIs."""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any

from .model import digest

_MAX_REPORT = 8_000_000


def read_report(path: str | Path) -> dict[str, Any]:
    path = Path(path)
    if path.stat().st_size > _MAX_REPORT:
        raise ValueError("Report exceeds 8 MB")
    try:
        report = json.loads(path.read_text(encoding="utf-8"))
    except (ValueError, UnicodeError) as exc:
        raise ValueError("Invalid report JSON") from exc
    if not isinstance(report, dict) or not isinstance(report.get("status"), str):
        raise ValueError("Expected EnvGuard diagnostic report")
    if "findings" in report and (not isinstance(report["findings"], list)
                                 or len(report["findings"]) > 10000):
        raise ValueError("Invalid diagnostic finding list")
    return report


def _clean(value: object, *, limit: int = 500) -> str:
    # Avoid newlines in annotations and Markdown; arbitrary report contents
    # must never generate untrusted workflow command directives.
    text = re.sub(r"\x1b\[[0-9;]*[A-Za-z]", "", str(value))
    return " ".join(text.split())[:limit]


def _entries(report: dict[str, Any]) -> list[dict[str, str]]:
    result = []
    if report.get("status") == "collection_failed":
        result.append({"code": "ENVIRONMENT_COLLECTION_FAILED", "severity": "high",
                       "summary": "EnvGuard could not inspect the target Python environment; root cause is unknown.",
                       "recommendation": "Check whether the chosen Python interpreter exists and starts successfully."})
    ci = report.get("ci") or {}
    failure = report.get("failure_analysis") or {}
    cause = failure.get("root_cause_hypothesis") or {}
    if cause and ci.get("command_exit_code", 0):
        result.append({"code": _clean(cause.get("code", "UNCLASSIFIED"), limit=100),
                       "severity": "high", "summary": _clean(cause.get("summary", "Observed environment failure")),
                       "recommendation": _clean(cause.get("recommendation", "Review the diagnostic report"))})
    for finding in report.get("findings") or []:
        if isinstance(finding, dict):
            result.append({"code": _clean(finding.get("code", "UNKNOWN"), limit=100),
                           "severity": _clean(finding.get("severity", "info"), limit=15),
                           "summary": _clean(finding.get("summary", "")),
                           "recommendation": _clean(finding.get("recommendation", ""))})
    return result[:100]


def markdown_report(report: dict[str, Any]) -> str:
    lines = ["# EnvGuard CI diagnostics", "", f"**Status:** {_clean(report['status'])}"]
    ci = report.get("ci") or {}
    if "command_exit_code" in ci:
        lines.append(f"**Command exit code:** `{ci['command_exit_code']}`")
    lines += ["", "## Findings", ""]
    entries = _entries(report)
    if not entries:
        lines.append("No findings for implemented checks. This does not prove environment equivalence.")
    for item in entries:
        # Escape pipe and formatting metacharacters from untrusted report text.
        def esc(s: str) -> str:
            return s.replace("\\", "\\\\").replace("`", "\\`").replace("[", "\\[").replace("|", "\\|")
        lines.extend([f"### {esc(item['code'])} ({esc(item['severity'])})", "",
                      esc(item["summary"]), "", f"Next step: {esc(item['recommendation'])}", ""])
    lines.extend(["> Findings are diagnostic hypotheses and environment observations, not guaranteed causes.", ""])
    return "\n".join(lines)


def github_annotations(report: dict[str, Any]) -> str:
    # Workflow commands need encoded user-controlled message content.
    def esc(value: str) -> str:
        return value.replace("%", "%25").replace("\r", "%0D").replace("\n", "%0A")
    result: list[str] = []
    for item in _entries(report):
        level = "error" if item["severity"] in ("critical", "high") else "warning" if item["severity"] == "medium" else "notice"
        title = re.sub(r"[^A-Za-z0-9_-]", "_", item["code"])[:80]
        result.append(f"::{level} title=EnvGuard_{title}::{esc(item['summary'])} | Next: {esc(item['recommendation'])}")
    return "\n".join(result) + ("\n" if result else "")


def gitlab_codequality(report: dict[str, Any], anchor: str = "pyproject.toml") -> list[dict[str, Any]]:
    # GitLab Code Quality requires a repository file/line for every issue. The
    # anchor is explicitly synthetic: no false claim that line 1 is defective.
    anchor = anchor.replace("\\", "/")
    if (anchor.startswith("/") or re.match(r"^[A-Za-z]:", anchor)
        or any(s in ("", ".", "..") for s in anchor.split("/"))):
        raise ValueError("GitLab anchor must be a normalized repository-relative file path")
    severity = {"critical": "blocker", "high": "critical", "medium": "major",
                "low": "minor", "info": "info"}
    issues = []
    for item in _entries(report):
        description = f"[EnvGuard CI environment; synthetic anchor] {item['code']}: {item['summary']} Next: {item['recommendation']}"
        issues.append({"description": description,
                       "check_name": "envguard/" + item["code"],
                       "fingerprint": digest({"code": item["code"], "description": description, "anchor": anchor}).split(":", 1)[1],
                       "severity": severity.get(item["severity"], "info"),
                       "location": {"path": anchor, "lines": {"begin": 1}}})
    return issues


def render(report: dict[str, Any], fmt: str, anchor: str = "pyproject.toml") -> str:
    if fmt == "markdown":
        return markdown_report(report)
    if fmt == "github-annotations":
        return github_annotations(report)
    if fmt == "gitlab-codequality":
        return json.dumps(gitlab_codequality(report, anchor=anchor), indent=2, sort_keys=True) + "\n"
    raise ValueError("Unsupported report format")
