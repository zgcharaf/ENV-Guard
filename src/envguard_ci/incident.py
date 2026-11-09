"""Human-reviewable, evidence-linked CI incident dossiers.

An incident is a *triage aid*, never a verified fix. The ledger references exact
fields in the diagnostic JSON. No arbitrary log content, argv, or environment
variables are copied into the dossier. No commands are executed.
"""
from __future__ import annotations

import hashlib
import json
import re
from typing import Any

_GENERIC = {"PYTHON_IMPORT_FAILURE", "PYTHON_IMPORT_SYMBOL_FAILURE"}
_SUPPORTED = {
    "WRONG_PYTHON_INTERPRETER", "PYTHON_SITE_DISABLED", "MISSING_DISTRIBUTION_AT_RUNTIME",
    "PACKAGE_API_VERSION_INCOMPATIBILITY", "NATIVE_LIBRARY_LOAD_FAILURE",
    "NATIVE_SYMBOL_LOAD_FAILURE", "NATIVE_SYMBOL_VERSION_MISSING",
}

# These are inspection commands, not patch commands. Do not interpolate
# captured log values or interpreter paths into executable snippets.
_CHECKS: dict[str, list[tuple[str, str | None]]] = {
    "WRONG_PYTHON_INTERPRETER": [
        ("Check which Python and virtual environment each CI step selects.", 'python -c "import sys; print(sys.executable); print(sys.prefix)"'),
        ("Check packages with the *same executable* used by the failing step.", "python -m pip list --format=freeze"),
        ("Re-run tests with the explicitly intended executable; do not install packages globally.", None),
    ],
    "PYTHON_SITE_DISABLED": [
        ("Check whether site initialization was disabled by Python flags.", 'python -c "import sys; print(sys.flags.no_site); print(sys.path)"'),
        ("Remove -S only after confirming it was unintended.", None),
    ],
    "MISSING_DISTRIBUTION_AT_RUNTIME": [
        ("Check the packages installed in the interpreter used by the failed command.", "python -m pip list --format=freeze"),
        ("Check installed dependency constraints.", "python -m pip check"),
        ("Compare package installation and interpreter selection with the known-good job.", None),
    ],
    "PYTHON_IMPORT_FAILURE": [
        ("Confirm the module spelling and which package, if any, provides it.", None),
        ("Inspect the executable and import search path in the failing context.", 'python -c "import sys; print(sys.executable); print(sys.path)"'),
        ("Check whether the package was declared for that dependency group.", None),
    ],
    "PACKAGE_API_VERSION_INCOMPATIBILITY": [
        ("Compare the failing and known-good installed package versions.", "python -m pip list --format=freeze"),
        ("Verify that the project's version constraints support the imported API.", None),
        ("Run the failing import under the candidate version before editing constraints.", None),
    ],
    "DEPENDENCY_RESOLUTION_CONFLICT": [
        ("Inspect the full resolver conflict explanation in the original CI log.", None),
        ("Review lockfile, constraints and enabled dependency groups.", None),
        ("Try a clean resolution in an isolated environment; avoid relaxing pins without evidence.", None),
    ],
    "PACKAGE_RESOLUTION_UNAVAILABLE": [
        ("Check package index configuration, network reachability, Python version and platform wheel availability.", None),
        ("Compare configured indexes and constraints with the successful runner (without logging credentials).", None),
    ],
    "WHEEL_BUILD_FAILED": [
        ("Find the first compiler or build-backend error in the original CI log.", None),
        ("Check build isolation, compiler, headers and native dependencies.", None),
    ],
    "NATIVE_LIBRARY_LOAD_FAILURE": [
        ("Inspect required shared libraries without executing the untrusted binary (e.g., readelf -d on Linux).", None),
        ("Compare ABI-compatible system libraries and loader search paths on the target runner.", None),
    ],
    "NATIVE_SYMBOL_LOAD_FAILURE": [
        ("Compare required and exported symbols on the target runtime.", None),
        ("Rebuild the extension against the supported ABI baseline in an isolated runner.", None),
    ],
    "NATIVE_SYMBOL_VERSION_MISSING": [
        ("Inspect required GLIBC/GLIBCXX/CXXABI symbols and target library exports.", None),
        ("Rebuild against a compatible baseline; do not blindly upgrade system libraries.", None),
    ],
    "WINDOWS_DLL_LOAD_FAILURE": [
        ("Inspect the extension and target DLL architecture and runtime dependencies.", None),
        ("Compare Visual C++ runtime availability and DLL search paths.", None),
    ],
    "PYTHON_IMPORT_SYMBOL_FAILURE": [
        ("Confirm the module exports the requested symbol and verify the installed version.", None),
        ("Compare the package metadata with a known-good interpreter.", None),
    ],
}


def _text(value: Any, limit: int = 400) -> str:
    """Strip control sequences and constrain text from a potentially untrusted report."""
    raw = str(value)
    raw = re.sub(r"\x1b(?:\[[0-?]*[ -/]*[@-~]|\][^\x07]*(?:\x07|\x1b\\))", "", raw)
    raw = "".join(c for c in raw if ord(c) >= 32 and ord(c) != 127)
    return " ".join(raw.split())[:limit]


def _item(claim: str, pointer: str, strength: str) -> dict[str, str]:
    return {"claim": _text(claim), "source": pointer, "role": strength}


def build_incident(report: dict[str, Any]) -> dict[str, Any]:
    """Generate a deterministic dossier from a standard ``ci-run`` report.

    No log reconstruction, source-code execution, online lookup or assumption
    that environment drift *caused* the failure.
    """
    if not isinstance(report, dict) or not isinstance(report.get("status"), str):
        raise ValueError("Expected an EnvGuard ci-run diagnostic JSON object")
    ci = report.get("ci") or {}
    failure = report.get("failure_analysis") or {}
    provenance = report.get("execution_provenance") or {}
    if not isinstance(ci, dict) or not isinstance(failure, dict) or not isinstance(provenance, dict):
        raise ValueError("Invalid CI diagnostic fields")
    hypothesis = failure.get("root_cause_hypothesis") or {}
    error_evidence = failure.get("evidence") or {}
    if not isinstance(hypothesis, dict) or not isinstance(error_evidence, dict):
        raise ValueError("Invalid failure analysis fields")
    exit_code = ci.get("command_exit_code")
    if not isinstance(exit_code, int) or isinstance(exit_code, bool):
        exit_code = None
    failed = exit_code is not None and exit_code != 0
    code = _text(hypothesis.get("code")) if failed and hypothesis else None
    confidence = hypothesis.get("confidence", "low") if code else None
    if code and confidence not in {"low", "medium", "high"}:
        confidence = "low"
    observed = _text(failure.get("observed_failure")) if failed and failure.get("observed_failure") else None
    known = provenance.get("observation") == "direct-python-argv"
    baseline = bool(ci.get("baseline_provided"))
    if report["status"] == "collection_failed":
        outcome = "collection_failed"
    elif exit_code is None:
        outcome = "unknown"
    elif not failed:
        outcome = "command_succeeded"
    elif code is None:
        outcome = "unclassified_failure"
    elif code in _GENERIC or confidence == "low":
        outcome = "unresolved_environment_cause"
    else:
        outcome = "supported_hypothesis"

    evidence: list[dict[str, str]] = []
    if exit_code is not None:
        evidence.append(_item(f"Wrapped command returned exit code {exit_code}", "/ci/command_exit_code", "observation"))
    if observed:
        evidence.append(_item(f"Recognized failure signature: {observed}", "/failure_analysis/observed_failure", "observation"))
    if known:
        expected = provenance.get("expected_python") or {}
        executed = provenance.get("executed_python") or {}
        match = provenance.get("interpreter_match")
        if isinstance(expected, dict) and isinstance(executed, dict) and match is False:
            evidence.append(_item("Directly invoked Python differs from explicitly expected Python", "/execution_provenance/interpreter_match", "supports"))
            if expected.get("label"):
                evidence.append(_item("Expected: " + _text(expected["label"], 180), "/execution_provenance/expected_python/label", "context"))
            if executed.get("label"):
                evidence.append(_item("Executed: " + _text(executed["label"], 180), "/execution_provenance/executed_python/label", "context"))
        elif match is True:
            evidence.append(_item("Directly invoked Python matches the selected Python", "/execution_provenance/interpreter_match", "context"))
    for key in ("import_name", "missing_symbol", "required_symbol_version", "distribution_requested", "library", "module", "wheel_distribution"):
        val = error_evidence.get(key)
        if isinstance(val, str) and val:
            evidence.append(_item(f"Parsed {key.replace('_', ' ')}: {_text(val, 150)}", f"/failure_analysis/evidence/{key}", "observation"))
    baseline_check = ci.get("baseline_comparability")
    if isinstance(baseline_check, dict) and baseline_check.get("status") == "different_target":
        evidence.append(_item("Baseline and current snapshots target different platforms/interpreters",
                              "/ci/baseline_comparability/status", "context"))
        if code in {"MISSING_DISTRIBUTION_AT_RUNTIME", "PACKAGE_API_VERSION_INCOMPATIBILITY"}:
            confidence = "low"
            outcome = "unresolved_environment_cause"
    if code == "WRONG_PYTHON_INTERPRETER":
        # Enforce that the high-confidence interpreter claim has evidence.
        if not (known and provenance.get("interpreter_match") is False and provenance.get("explicit_expected")):
            confidence = "low"
            outcome = "unresolved_environment_cause"
    findings = [f for f in report.get("findings") or [] if isinstance(f, dict)]
    for idx, finding in enumerate(findings[:4]):
        if finding.get("code"):
            evidence.append(_item("Environment check: " + _text(finding["code"], 100), f"/findings/{idx}/code", "correlation_only"))

    limitations = ["The error signature is not proof of the underlying cause; no repair was executed or verified."]
    if not baseline:
        limitations.append("No known-good CI baseline supplied; cross-run causality was not tested.")
    elif isinstance(baseline_check, dict):
        if baseline_check.get("status") == "different_target":
            limitations.append("Baseline and failing job target different environments; "
                               "dependency drift may be expected rather than causal.")
        elif baseline_check.get("status") == "insufficient_metadata":
            limitations.append("Insufficient target metadata to establish that the baseline "
                               "and failing job are comparable.")
    if not known:
        limitations.append("The command's Python interpreter was not directly observed; wrappers and child processes are not traced.")
    if failed and code is None:
        limitations.append("No supported Python environment signature matched this failure; it may be unrelated to dependencies.")
    if observed == "module_missing" and code == "PYTHON_IMPORT_FAILURE":
        limitations.append("Import names need not match distribution names; package ownership is unresolved.")
    if report["status"] == "collection_failed":
        limitations.append("Environment snapshot collection failed; diagnostics may be incomplete.")
    if outcome == "command_succeeded":
        limitations = ["The command succeeded. A clean check is not proof of environment reproducibility."]

    selected_checks = _CHECKS.get(code or "", [
        ("Inspect the original failing CI logs and first relevant exception.", None),
        ("Compare Python version, invoked interpreter and installed packages with a working job.", None),
    ]) if failed else []
    checks = [{"action": action, "command": cmd, "verified": False} for action, cmd in selected_checks]
    fps = report.get("fingerprints") or {}
    if not isinstance(fps, dict):
        fps = {}
    digest_payload = {"exit_code": exit_code, "observed": observed, "code": code,
                      "spec": fps.get("spec"), "runtime": fps.get("runtime")}
    incident_id = hashlib.sha256(json.dumps(digest_payload, sort_keys=True).encode()).hexdigest()[:16]
    return {
        "schema_version": "0.1.0",
        "incident_id": incident_id,
        "outcome": outcome,
        "command_exit_code": exit_code,
        "observed_failure": observed,
        "hypothesis": {
            "code": code,
            "confidence": confidence,
            "summary": _text(hypothesis.get("summary", ""), 500) if code else None,
        },
        "evidence": evidence,
        "uncertainties": limitations,
        "checks": checks,
        "automatic_changes_made": False,
        "patch_validated": False,
        "baseline_provided": baseline,
        "privacy": "No raw logs, full argv, environment variables, or absolute interpreter paths are copied into this dossier.",
    }


def render_markdown(incident: dict[str, Any]) -> str:
    def esc(v: Any) -> str:
        # Markdown and HTML escaping for values derived from external logs/data.
        s = _text(v).replace("\\", "\\\\").replace("`", "\\`")
        s = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
        for token in ("[", "]", "|", "*", "_"):
            s = s.replace(token, "\\" + token)
        return s

    h = incident["hypothesis"]
    lines = ["# EnvGuard CI incident dossier", "",
             f"Incident ID: `{incident['incident_id']}`",
             f"Execution: **{esc(incident['outcome'])}**",
             f"Command exit code: `{incident['command_exit_code']}`", "",
             "## Observed vs inferred", "",
             f"- **Observed failure:** `{_text(incident['observed_failure'] or 'No classified signature')}`",
             f"- **Root-cause hypothesis:** `{_text(h['code'] or 'Undetermined')}`",
             f"- **Confidence:** {esc(h['confidence'] or 'Not applicable')}"]
    if h["summary"]:
        lines += [f"- **Explanation:** {esc(h['summary'])}"]
    lines += ["", "## Evidence ledger", ""]
    if incident["evidence"]:
        for item in incident["evidence"]:
            lines.append(f"- {esc(item['claim'])} (`{_text(item['source'])}`, `{_text(item['role'])}`)")
    else:
        lines.append("- No supported environment observation available")
    lines += ["", "## Safe next checks", ""]
    for index, check in enumerate(incident["checks"], 1):
        lines.append(f"{index}. {esc(check['action'])}")
        if check["command"]:
            lines += ["", "   ```text", "   " + check["command"], "   ```", ""]
    if not incident["checks"]:
        lines.append("- No remediation needed for a successful command")
    lines += ["", "## What this does **not** establish", ""]
    lines += ["- " + esc(v) for v in incident["uncertainties"]]
    lines += ["", "No dependency changes were made. No patch has been validated.", ""]
    return "\n".join(lines)
