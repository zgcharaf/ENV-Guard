"""CLI entry point for snapshots, diffs and local checks."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from . import __version__
from .collection import CollectionError, snapshot
from .diagnostics import diff, doctor
from .graph import graph
from .ci import run_ci
from .gitlab import GitLabError, fetch_baseline
from .failure import diagnose_failure
from .model import SnapshotError, read_snapshot, write_json
from .provenance import execution_context
from .reporting import read_report, render
from .incident import build_incident, render_markdown
from .artifacts import inspect_wheel, ArtifactError
from .verification import verify_interpreter_selection, VerificationError
from .certify import certify_wheel, CertificationError
from .github import fetch_github_baseline, GitHubError

_PRIORITIES = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}


def _parse() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="envguard-ci", description="Diagnose Python environment drift; never modify installs.")
    p.add_argument("--version", action="version", version=f"envguard-ci {__version__}")
    sub = p.add_subparsers(dest="command", required=True)
    snap = sub.add_parser("snapshot", help="Capture interpreter, packages, project and optional native libraries")
    snap.add_argument("--project", default=".", help="Project root (default: current directory)")
    snap.add_argument("--python", default=sys.executable, help="Interpreter to inspect (default: current Python)")
    snap.add_argument("--native", action="store_true", help="Inspect ELF extension requirements and ldconfig on Linux")
    snap.add_argument("--out", default="-", help="Output JSON file or '-' for stdout")
    dc = sub.add_parser("diff", help="Compare an expected known-good environment to a current environment")
    dc.add_argument("--baseline", required=True, help="Snapshot of known-good environment")
    dc.add_argument("--current", required=True, help="Snapshot of current or failing environment")
    dc.add_argument("--format", choices=("text", "json"), default="text")
    dc.add_argument("--out", default="-", help="File for results; '-' means stdout")
    dc.add_argument("--fail-on", choices=("never", "critical", "high", "medium", "low", "info"), default="never")
    d = sub.add_parser("doctor", help="Run deterministic local checks on a snapshot")
    d.add_argument("--snapshot", required=True, help="Captured snapshot path")
    d.add_argument("--extra", action="append", default=[], help="Project extra to validate (repeatable)")
    d.add_argument("--format", choices=("text", "json"), default="text")
    d.add_argument("--out", default="-")
    d.add_argument("--fail-on", choices=("never", "critical", "high", "medium", "low", "info"), default="never")
    g = sub.add_parser("graph", help="Inspect installed distribution dependency graph")
    g.add_argument("--snapshot", required=True)
    g.add_argument("--scope", choices=("project", "environment"), default="project", help="Project graph by default; environment checks all installed packages")
    g.add_argument("--focus", help="Inspect an installed package, e.g. pandas (overrides scope)")
    g.add_argument("--extra", action="append", default=[], help="Select an extra on the project or focused package (repeatable)")
    g.add_argument("--show-inactive", action="store_true", help="Show skipped extras, marker-excluded and unknown edges")
    g.add_argument("--format", choices=("text", "json"), default="text")
    g.add_argument("--out", default="-")
    cr = sub.add_parser("ci-run", help="Run CI command and save diagnostics even on failure")
    cr.add_argument("--project", default=".")
    cr.add_argument("--python", help="Explicitly expected interpreter (enables wrong-interpreter diagnosis)")
    cr.add_argument("--native", action="store_true")
    cr.add_argument("--snapshot-out", default="envguard-ci.json")
    cr.add_argument("--report-out", default="envguard-report.json")
    cr.add_argument("--incident-out", help="Markdown dossier; defaults to report filename with .md suffix")
    cr.add_argument("--baseline", help="Optional known-good snapshot; otherwise run local doctor")
    cr.add_argument("--fail-on", choices=("never", "critical", "high", "medium", "low", "info"), default="never")
    cr.add_argument("exec", nargs=argparse.REMAINDER, help="Command to run, preceded by --")
    inv = sub.add_parser("investigate", help="Wrap command and optionally fetch latest successful CI baseline")
    inv.add_argument("--project", default=".")
    inv.add_argument("--python", help="Explicit expected interpreter")
    inv.add_argument("--native", action="store_true")
    inv.add_argument("--snapshot-out", default="envguard-ci.json")
    inv.add_argument("--report-out", default="envguard-report.json")
    inv.add_argument("--incident-out")
    inv.add_argument("--baseline", help="Known-good snapshot file")
    inv.add_argument("--last-green", choices=("gitlab", "github"), help="Fetch latest successful workflow snapshot (not necessarily previous commit)")
    inv.add_argument("--baseline-ref", help="Branch/tag containing the successful baseline")
    inv.add_argument("--baseline-job", default="envguard-ci:tests", help="GitLab successful job name")
    inv.add_argument("--baseline-artifact", default="envguard-ci.json", help="Filename inside artifact archive")
    inv.add_argument("--github-workflow", help="GitHub workflow ID or filename")
    inv.add_argument("--github-artifact", default="envguard-baseline", help="GitHub Actions artifact name")
    inv.add_argument("--require-baseline", action="store_true", help="Do not execute if requested baseline is unavailable")
    inv.add_argument("--fail-on", choices=("never", "critical", "high", "medium", "low", "info"), default="never")
    inv.add_argument("exec", nargs=argparse.REMAINDER, help="Command after --")
    wh = sub.add_parser("inspect-wheel", help="Offline wheel SHA256 and RECORD integrity checks; no code execution")
    wh.add_argument("--wheel", required=True)
    wh.add_argument("--approved-sha256")
    wh.add_argument("--out", default="-")
    ve = sub.add_parser("verify-interpreter", help="Explicit local experiment: compare two Python interpreters running same program")
    ve.add_argument("--project", default=".")
    ve.add_argument("--original-python", required=True)
    ve.add_argument("--candidate-python", required=True)
    ve.add_argument("--allow-local-execution", action="store_true", help="Acknowledges unsandboxed application code execution twice")
    ve.add_argument("--timeout", type=int, default=60)
    ve.add_argument("--out", default="repair-experiment.json")
    ve.add_argument("exec", nargs=argparse.REMAINDER)
    cert = sub.add_parser("certify-wheel", help="Import-smoke a wheel inside a pinned offline Docker runtime")
    cert.add_argument("--wheel", required=True)
    cert.add_argument("--image", required=True)
    cert.add_argument("--module", required=True)
    cert.add_argument("--wheelhouse")
    cert.add_argument("--approved-sha256")
    cert.add_argument("--allow-mutable-image", action="store_true")
    cert.add_argument("--timeout", type=int, default=150)
    cert.add_argument("--out", default="deployment-proof.json")
    af = sub.add_parser("diagnose-failure", help="Correlate a real failed process log with environment snapshots")
    af.add_argument("--baseline", required=True)
    af.add_argument("--current", required=True)
    af.add_argument("--log", required=True, help="File containing failure output (not included in report)")
    af.add_argument("--exit-code", type=int, default=1)
    af.add_argument("--execution", help="Optional execution provenance JSON (produced by failure lab)")
    af.add_argument("--expected-python", help="Explicitly intended interpreter for the failed command")
    af.add_argument("--invoked-python", help="Actual directly invoked Python executable")
    af.add_argument("--format", choices=("text", "json"), default="text")
    af.add_argument("--out", default="-")
    t = sub.add_parser("triage", help="Render an evidence-linked incident dossier from a CI report")
    t.add_argument("--report", required=True, help="ci-run JSON report")
    t.add_argument("--format", choices=("markdown", "json"), default="markdown")
    t.add_argument("--out", default="-", help="Output file or '-' for stdout")
    rpt = sub.add_parser("render-report", help="Render a CI diagnostic as Markdown, GitLab Code Quality or GitHub annotations")
    rpt.add_argument("--input", required=True, help="EnvGuard report JSON")
    rpt.add_argument("--format", required=True, choices=("markdown", "github-annotations", "gitlab-codequality"))
    rpt.add_argument("--out", default="-", help="File path or stdout")
    rpt.add_argument("--anchor", default="pyproject.toml", help="GitLab Code Quality synthetic repository-relative location")
    gh = sub.add_parser("github-baseline", help="Fetch successful GitHub Actions snapshot (read-only)")
    gh.add_argument("--repo", help="OWNER/REPO")
    gh.add_argument("--ref", help="Default branch name")
    gh.add_argument("--workflow", required=True, help="Workflow filename or ID")
    gh.add_argument("--artifact-name", default="envguard-baseline")
    gh.add_argument("--snapshot-name", default="envguard-ci.json")
    gh.add_argument("--out", default="envguard-baseline.json")
    gl = sub.add_parser("gitlab-baseline", help="Fetch a known-good snapshot from a successful GitLab pipeline")
    gl.add_argument("--out", default="envguard-baseline.json")
    gl.add_argument("--api-url", help="Default: CI_API_V4_URL")
    gl.add_argument("--project-id", help="Default: CI_PROJECT_ID")
    gl.add_argument("--ref", help="Default: CI_DEFAULT_BRANCH")
    gl.add_argument("--job", default="envguard:diagnose")
    gl.add_argument("--artifact", default="envguard-ci.json")
    gl.add_argument("--allow-http", action="store_true", help="Only for trusted internal self-hosted GitLab")
    return p


def _display(result: dict[str, Any]) -> str:
    lines = [f"EnvGuard: {result['status']}", "=" * 66, result["disclaimer"], ""]
    if not result["findings"]:
        lines.append("No findings for implemented checks (not a guarantee of equivalent environments).")
    for i, finding in enumerate(result["findings"], 1):
        lines.append(f"{i:>2}. [{finding['severity'].upper()}] {finding['code']}")
        lines.append(f"    {finding['summary']}")
        evidence = json.dumps(finding["evidence"], ensure_ascii=False, sort_keys=True)
        if len(evidence) > 750:
            evidence = evidence[:747] + "..."
        lines.append(f"    Evidence: {evidence}")
        lines.append(f"    Confidence: {finding['confidence']}")
        lines.append(f"    Next step: {finding['recommendation']}")
        lines.append("")
    if result.get("dependency_summary"):
        counts = result["dependency_summary"]
        lines.append("Dependency checks: " + ", ".join(
            f"{name}={counts[name]}" for name in
            ("installed_packages", "required_satisfied", "required_missing",
             "required_incompatible", "optional_unselected", "marker_excluded", "unresolved")))
    lines.append("Counts: " + ", ".join(f"{s}={n}" for s, n in result["counts"].items()))
    return "\n".join(lines) + "\n"


def _display_graph(report: dict[str, Any], *, show_inactive: bool = False) -> str:
    lines = [f"EnvGuard dependency graph — {report['scope']} scope", "=" * 55,
             report["disclaimer"], ""]
    labels = {"required_satisfied": "OK", "required_missing": "MISSING",
              "required_incompatible": "CONFLICT", "required_unverifiable": "UNVERIFIED",
              "optional_unselected": "OPTIONAL", "marker_excluded": "NOT APPLICABLE",
              "unknown": "UNKNOWN"}
    hidden = 0
    for e in report["edges"]:
        if not show_inactive and e["status"] in {"optional_unselected", "marker_excluded", "unknown"}:
            hidden += 1
            continue
        lines.append(f"  {e['from']} -> {e['to']} [{labels[e['status']]}] {e['requirement']}")
    if hidden:
        lines.append(f"  ... {hidden} inactive/unresolved edges hidden; --show-inactive to inspect")
    if not report["edges"]:
        lines.append("  No dependency edges in selected scope; try --scope environment or --focus NAME.")
    lines.append("")
    lines.append("Stats: " + ", ".join(f"{k}={v}" for k, v in report["stats"].items()))
    return "\n".join(lines) + "\n"


def _emit(result: dict[str, Any], fmt: str, dest: str) -> None:
    if fmt == "json":
        write_json(result, dest)
    else:
        text = _display(result)
        if dest == "-":
            print(text, end="")
        else:
            path = Path(dest)
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")


def _exit_code(result: dict[str, Any], level: str) -> int:
    if level == "never":
        return 0
    return 1 if any(_PRIORITIES[f["severity"]] <= _PRIORITIES[level] for f in result["findings"]) else 0


def main(argv: list[str] | None = None) -> int:
    args = _parse().parse_args(argv)
    try:
        if args.command == "inspect-wheel":
            write_json(inspect_wheel(args.wheel, approved_sha256=args.approved_sha256), args.out)
            return 0
        if args.command == "verify-interpreter":
            command = args.exec[1:] if args.exec and args.exec[0] == "--" else args.exec
            verification = verify_interpreter_selection(project=args.project,
                original_python=args.original_python, candidate_python=args.candidate_python,
                arguments=command, allow_local_execution=args.allow_local_execution,
                timeout=args.timeout, output=args.out)
            print(f"EnvGuard repair experiment: {verification['status']} ({args.out})")
            return 0 if verification['status'] == 'observed_candidate_succeeds' else 1
        if args.command == "certify-wheel":
            certification = certify_wheel(wheel=args.wheel, image=args.image, module=args.module,
                wheelhouse=args.wheelhouse, approved_sha256=args.approved_sha256,
                require_digest=not args.allow_mutable_image, timeout=args.timeout, output=args.out)
            print(f"EnvGuard target-image smoke test: {certification['status']} ({args.out})")
            return 0 if certification['status'] == 'passed' else 1
        if args.command == "investigate":
            command = args.exec[1:] if args.exec and args.exec[0] == "--" else args.exec
            return run_ci(command, project=args.project, python=args.python, native=args.native,
                snapshot_out=args.snapshot_out, report_out=args.report_out, incident_out=args.incident_out,
                baseline=args.baseline, fail_on=args.fail_on, last_green=args.last_green,
                baseline_job=args.baseline_job, baseline_artifact=args.baseline_artifact,
                github_workflow=args.github_workflow, github_artifact=args.github_artifact,
                require_baseline=args.require_baseline, baseline_ref=args.baseline_ref)
        if args.command == "ci-run":
            cmd = args.exec[1:] if args.exec and args.exec[0] == "--" else args.exec
            return run_ci(cmd, project=args.project, python=args.python, native=args.native,
                          snapshot_out=args.snapshot_out, report_out=args.report_out, incident_out=args.incident_out,
                          baseline=args.baseline, fail_on=args.fail_on)
        if args.command == "github-baseline":
            fetch_github_baseline(args.out, repo=args.repo, branch=args.ref, workflow=args.workflow,
                                  artifact_name=args.artifact_name, snapshot_name=args.snapshot_name)
            return 0
        if args.command == "gitlab-baseline":
            fetch_baseline(args.out, api_url=args.api_url, project_id=args.project_id,
                           ref=args.ref, job=args.job, artifact=args.artifact,
                           allow_http=args.allow_http)
            return 0
        if args.command == "triage":
            dossier = build_incident(read_report(args.report))
            if args.format == "json":
                write_json(dossier, args.out)
            else:
                output = render_markdown(dossier)
                if args.out == "-":
                    print(output, end="")
                else:
                    target = Path(args.out)
                    target.parent.mkdir(parents=True, exist_ok=True)
                    target.write_text(output, encoding="utf-8")
            return 0
        if args.command == "render-report":
            output = render(read_report(args.input), args.format, anchor=args.anchor)
            if args.out == "-":
                print(output, end="")
            else:
                target = Path(args.out)
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_text(output, encoding="utf-8")
            return 0
        if args.command == "diagnose-failure":
            logfile = Path(args.log)
            if logfile.stat().st_size > 2_000_000:
                raise ValueError("Log exceeds 2 MB")
            execution = None
            if args.execution:
                path = Path(args.execution)
                if path.stat().st_size > 100_000:
                    raise ValueError("Execution provenance file exceeds 100 KB")
                execution = json.loads(path.read_text(encoding="utf-8"))
                if not isinstance(execution, dict) or execution.get("schema_version") != "1.0":
                    raise ValueError("Invalid execution provenance file")
            elif args.expected_python or args.invoked_python:
                execution = execution_context(expected_python=args.expected_python,
                                              invoked_python_path=args.invoked_python)
            report = diagnose_failure(read_snapshot(args.baseline), read_snapshot(args.current),
                                      log=logfile.read_text(encoding="utf-8", errors="replace"),
                                      exit_code=args.exit_code, execution=execution,
                                      expected_snapshot=read_snapshot(args.baseline) if execution else None)
            if args.format == "json":
                write_json(report, args.out)
            else:
                cause = report["root_cause_hypothesis"]
                output = (f"Observed failure: {report['observed_failure'] or 'unclassified'}\n"
                          f"Hypothesis: {cause['code'] if cause else 'none'}\n"
                          f"Confidence: {cause['confidence'] if cause else 'n/a'}\n"
                          f"Supporting environment findings: {', '.join(report['environment_correlations']) or 'none'}\n"
                          f"Recommendation: {cause['recommendation'] if cause else 'Inspect original command output'}\n"
                          f"Environment diff findings: {len(report['drift']['findings'])}\n")
                if args.out == "-":
                    print(output, end="")
                else:
                    Path(args.out).write_text(output, encoding="utf-8")
            return 0
        if args.command == "snapshot":
            write_json(snapshot(project=args.project, python=args.python, native=args.native), args.out)
            return 0
        if args.command == "graph":
            result = graph(read_snapshot(args.snapshot), scope=args.scope, focus=args.focus, extras=args.extra)
            if args.format == "json":
                write_json(result, args.out)
            else:
                output = _display_graph(result, show_inactive=args.show_inactive)
                if args.out == "-":
                    print(output, end="")
                else:
                    path = Path(args.out)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    path.write_text(output, encoding="utf-8")
            return 0
        if args.command == "diff":
            result = diff(read_snapshot(args.baseline), read_snapshot(args.current))
        elif args.command == "doctor":
            result = doctor(read_snapshot(args.snapshot), extras=args.extra)
        else:
            raise AssertionError(args.command)
        _emit(result, args.format, args.out)
        return _exit_code(result, args.fail_on)
    except (SnapshotError, CollectionError, GitLabError, GitHubError, ArtifactError, VerificationError, CertificationError, ValueError, OSError) as exc:
        print(f"envguard-ci: {exc}", file=sys.stderr)
        return 2
