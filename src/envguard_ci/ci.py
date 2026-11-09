"""Failure-preserving, streaming CI execution with automatic local analysis.

Stdout/stderr are echoed to the runner and only a bounded tail is analyzed in
memory. EnvGuard never stores raw command output in the diagnostic artifact.
"""
from __future__ import annotations

import codecs
import subprocess
import sys
from collections import deque
from pathlib import Path

from .collection import CollectionError, snapshot
from .comparability import assess_targets
from .diagnostics import diff, doctor
from .failure import diagnose_failure
from .model import SnapshotError, read_snapshot, write_json
from .provenance import execution_context, invoked_python
from .incident import build_incident, render_markdown
from .gitlab import fetch_baseline, GitLabError
from .github import fetch_github_baseline, GitHubError

_ORDER = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
LOG_TAIL = 120_000


def _execute(command: list[str], project: str) -> tuple[int, str]:
    """Run without a shell, echo child output, and bound retained log memory."""
    try:
        proc = subprocess.Popen(command, cwd=project, stdout=subprocess.PIPE,
                                stderr=subprocess.STDOUT, stdin=None)
    except FileNotFoundError:
        print("EnvGuard: wrapped executable not found", file=sys.stderr)
        return 127, "EnvGuard: executable not found"
    except PermissionError:
        print("EnvGuard: wrapped executable cannot be started", file=sys.stderr)
        return 126, "EnvGuard: executable cannot be started"
    except OSError:
        print("EnvGuard: OS rejected wrapped executable", file=sys.stderr)
        return 126, "EnvGuard: OS rejected executable"
    assert proc.stdout is not None
    decoder = codecs.getincrementaldecoder("utf-8")("replace")
    chunks: deque[str] = deque()
    total = 0
    def emit(text: str) -> None:
        nonlocal total
        if not text:
            return
        # stdout may not support all Unicode codepoints on Windows consoles.
        try:
            sys.stdout.write(text)
            sys.stdout.flush()
        except UnicodeEncodeError:
            sys.stdout.buffer.write(text.encode(sys.stdout.encoding or "utf-8", errors="replace"))
            sys.stdout.buffer.flush()
        chunks.append(text)
        total += len(text)
        while total > LOG_TAIL and chunks:
            excess = total - LOG_TAIL
            if len(chunks[0]) <= excess:
                total -= len(chunks.popleft())
            else:
                chunks[0] = chunks[0][excess:]
                total -= excess
    try:
        while True:
            block = proc.stdout.read(4096)
            if not block:
                break
            emit(decoder.decode(block))
        emit(decoder.decode(b"", final=True))
        return proc.wait(), "".join(chunks)
    except KeyboardInterrupt:
        proc.terminate()
        try:
            proc.wait(timeout=3)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()
        return 130, "".join(chunks)
    finally:
        proc.stdout.close()


def run_ci(
    command: list[str], *, project: str = ".", python: str | None = None,
    native: bool = False, snapshot_out: str = "envguard-ci.json",
    report_out: str = "envguard-report.json", incident_out: str | None = None, baseline: str | None = None,
    fail_on: str = "never", last_green: str | None = None,
    baseline_job: str = "envguard-ci:tests", baseline_artifact: str = "envguard-ci.json",
    github_workflow: str | None = None, github_artifact: str = "envguard-baseline",
    require_baseline: bool = False, baseline_ref: str | None = None,
) -> int:
    """Run command, capture the *executed* interpreter if directly observable.

    `--python` means explicitly expected interpreter, NOT necessarily the one
    used by the command. Shell wrappers cannot be observed from their argv.
    On errors, preserve the original command status and write a report.
    """
    if not command:
        raise ValueError("ci-run requires a command after --")
    project = str(Path(project).absolute())
    if baseline and last_green:
        raise ValueError("--baseline and --last-green cannot be combined")
    if last_green and last_green not in ("gitlab", "github"):
        raise ValueError("--last-green requires gitlab or github")
    baseline_data = None
    baseline_state = "explicit" if baseline else "not_requested"
    if last_green:
        import tempfile
        with tempfile.TemporaryDirectory(prefix='envguard-baseline-') as tmp:
            try:
                dest = str(Path(tmp) / 'baseline.json')
                if last_green == 'gitlab':
                    baseline_data = fetch_baseline(dest, ref=baseline_ref, job=baseline_job, artifact=baseline_artifact)
                else:
                    baseline_data = fetch_github_baseline(dest, branch=baseline_ref, workflow=github_workflow,
                           artifact_name=github_artifact, snapshot_name=baseline_artifact)
                baseline_state = "retrieved"
            except (GitLabError, GitHubError, ValueError, OSError):
                baseline_state = "unavailable"
                print("EnvGuard: requested successful baseline is unavailable; "
                      "comparison will be marked incomplete", file=sys.stderr)
                if require_baseline:
                    return 2
    invoked = invoked_python(command, project=project)
    observed_python = invoked or python or sys.executable
    context = execution_context(command=command, project=project, expected_python=python,
                                invoked_python_path=invoked)
    code, log_tail = _execute(command, project)
    try:
        current = snapshot(project, python=observed_python, native=native)
        write_json(current, snapshot_out)
        base = baseline_data if baseline_data is not None else (read_snapshot(baseline) if baseline else None)
        report = diff(base, current) if base else doctor(current)
        expected_snap = None
        if python and invoked and context["interpreter_match"] is False:
            expected_snap = snapshot(project, python=python)
        failure = (diagnose_failure(base or expected_snap or current, current,
                                    log=log_tail, exit_code=code, execution=context,
                                    expected_snapshot=expected_snap)
                   if code else None)
        report["ci"] = {
            "command_exit_code": code,
            "baseline_provided": bool(base),
            "baseline_source": baseline_state,
            "baseline_comparability": assess_targets(base, current) if base else None,
            "diagnostic_mode": "diff" if base else "doctor",
            "log_analysis": "bounded in-memory tail only; original log is not included",
            "executed_python_inspected": bool(invoked),
            "baseline_is_historical_predecessor_verified": False,
            "snapshot_available": True,
            "analysis_complete": True,
        }
        report["execution_provenance"] = context
        report["failure_analysis"] = ({k: v for k, v in failure.items() if k not in ("drift", "execution_provenance")}
                                      if failure else None)
        write_json(report, report_out)
        dossier = build_incident(report)
        destination = Path(incident_out) if incident_out else Path(report_out).with_suffix(".md")
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(render_markdown(dossier), encoding="utf-8")
        cause = ((failure or {}).get("root_cause_hypothesis") or {}).get("code", "unresolved") if code else "none"
        print(f"EnvGuard: {report['status']} ({len(report['findings'])} finding(s)); "
              f"failure={cause}; snapshot={snapshot_out} report={report_out}", file=sys.stderr)
        over_threshold = fail_on != "never" and any(
            _ORDER[f["severity"]] <= _ORDER[fail_on] for f in report["findings"])
        return code if code else (1 if over_threshold else 0)
    except (CollectionError, SnapshotError, ValueError, OSError) as exc:
        # Fail open for the *original command status* but never falsely claim
        # a clean environment: collection failure gets a minimal JSON report
        # and a dossier even when the target Python cannot start.
        print(f"envguard-ci: evidence collection failed ({type(exc).__name__}); "
              "wrapped command status preserved", file=sys.stderr)
        fallback = {
            "schema_version": "1.0", "status": "collection_failed",
            "error_type": type(exc).__name__,
            "ci": {"command_exit_code": code, "baseline_provided": bool(base if 'base' in locals() else False),
                   "baseline_source": baseline_state, "snapshot_available": False, "analysis_complete": False},
            "execution_provenance": context,
            "failure_analysis": None, "findings": [],
            "counts": {level: 0 for level in _ORDER},
            "disclaimer": "The target environment could not be inspected; no "
                          "root cause is established. Original command status retained.",
        }
        try:
            write_json(fallback, report_out)
            dossier = build_incident(fallback)
            destination = Path(incident_out) if incident_out else Path(report_out).with_suffix(".md")
            destination.parent.mkdir(parents=True, exist_ok=True)
            destination.write_text(render_markdown(dossier), encoding="utf-8")
        except (OSError, ValueError, TypeError) as writing_error:
            print(f"envguard-ci: could not persist fallback incident "
                  f"({type(writing_error).__name__})", file=sys.stderr)
        return code if code else 2
