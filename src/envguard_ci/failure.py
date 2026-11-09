"""Evidence-based classification of real process failures.

Never run logs as commands or send them to an LLM. We extract constrained error
signatures, then correlate those with independently collected environment drift.
"""
from __future__ import annotations

import re
from typing import Any

from .diagnostics import diff
from .model import canonical_name, validate_snapshot


ERROR_PATTERNS = (
    # Common installer messages, not proof of why the index/constraint failed.
    ("resolution_unavailable", re.compile(r"No matching distribution found for\s+([A-Za-z0-9_.-]+)", re.I)),
    ("resolver_conflict", re.compile(r"(?:ResolutionImpossible|conflicting dependencies|No solution found when resolving dependencies|version solving failed)", re.I)),
    ("wheel_build", re.compile(r"Failed building wheel for\s+([A-Za-z0-9_.-]+)", re.I)),
    ("native_symbol_version", re.compile(r"version ['`]?((?:GLIBCXX|CXXABI|GLIBC)_[0-9.]+)['`]?\s+not found", re.I)),
    ("dll_load", re.compile(r"ImportError:\s+DLL load failed while importing\s+([A-Za-z0-9_.]+)", re.I)),
    # `python -m absent` fails before a traceback; there is no ModuleNotFoundError.
    ("module_missing", re.compile(r"(?:^|\n)[^\n]*\bpython(?:[0-9.]*|\.exe)?:\s+No module named\s+([a-zA-Z0-9_.]+)")),
    ("module_missing", re.compile(r"ModuleNotFoundError:\s+No module named ['\"]([a-zA-Z0-9_.]+)['\"]")),
    ("import_symbol", re.compile(r"ImportError:\s+cannot import name ['\"]([a-zA-Z0-9_]+)['\"] from ['\"]([a-zA-Z0-9_.]+)['\"]")),
    ("native_missing", re.compile(r"(?:OSError|ImportError):\s+([^\n:]*?\.so(?:\.\d+)*):\s+cannot open shared object file")),
    ("native_symbol", re.compile(r"(?:AttributeError|OSError|ImportError):\s+[^\n]*?undefined symbol:\s+([a-zA-Z0-9_]+)")),
)


def _signature(log: str) -> tuple[str, tuple[str, ...]] | None:
    # Select the last traceback signature, not arbitrary earlier log lines.
    matches = []
    for kind, pattern in ERROR_PATTERNS:
        for match in pattern.finditer(log[-100_000:]):
            matches.append((match.end(), kind, match.groups()))
    if not matches:
        return None
    _, kind, groups = max(matches, key=lambda x: x[0])
    return kind, groups


def _distribution_owners(snap: dict[str, Any], import_root: str) -> set[str]:
    """Only metadata-backed owners, with a weak package-name fallback.

    Import roots are not guaranteed to match distribution names (Pillow/PIL).
    """
    owners = snap.get("runtime", {}).get("provenance", {}).get("import_owners", {})
    mapped = owners.get(import_root, []) if isinstance(owners, dict) else []
    matches = {canonical_name(v) for v in mapped if isinstance(v, str)}
    if matches:
        return matches
    fallback = canonical_name(import_root)
    if any(canonical_name(p["name"]) == fallback for p in snap["packages"]):
        return {fallback}
    return set()


def diagnose_failure(baseline: dict[str, Any], current: dict[str, Any],
                     *, log: str, exit_code: int,
                     execution: dict[str, Any] | None = None,
                     expected_snapshot: dict[str, Any] | None = None) -> dict[str, Any]:
    validate_snapshot(baseline)
    validate_snapshot(current)
    if expected_snapshot is not None:
        validate_snapshot(expected_snapshot)
    if len(log) > 2_000_000:
        raise ValueError("Log exceeds 2 MB; provide a bounded failure excerpt")
    drift = diff(baseline, current)
    codes = {f["code"] for f in drift["findings"]}
    source = {canonical_name(p["name"]): p["version"] for p in baseline["packages"]}
    target = {canonical_name(p["name"]): p["version"] for p in current["packages"]}
    sig = _signature(log)
    cause: dict[str, Any] | None = None
    evidence: dict[str, Any] = {}
    supported_by: list[str] = []
    observed: str | None = None
    if sig:
        kind, args = sig
        observed = kind
        if kind == "module_missing":
            root = args[0].split(".")[0]
            baseline_owners = _distribution_owners(baseline, root)
            current_owners = _distribution_owners(current, root)
            expected_owners = _distribution_owners(expected_snapshot, root) if expected_snapshot else set()
            absent_in_current = bool(baseline_owners) and not (baseline_owners & set(target))
            expected_contains = bool(expected_owners & {canonical_name(p["name"]) for p in expected_snapshot["packages"]}) if expected_snapshot else False
            flags = (execution or {}).get("flags") or {}
            mismatch = ((execution or {}).get("interpreter_match") is False
                        and (execution or {}).get("explicit_expected") is True
                        and (execution or {}).get("observation") == "direct-python-argv")
            evidence = {"import_name": args[0],
                        "baseline_candidate_distributions": sorted(baseline_owners),
                        "current_candidate_distributions": sorted(current_owners)}
            if flags.get("site_disabled") and bool(current_owners):
                cause = {"code": "PYTHON_SITE_DISABLED", "confidence": "high",
                         "summary": "Python was invoked with -S, disabling automatic site initialization while the module's distribution is present.",
                         "recommendation": "Remove -S or intentionally configure the required import paths for the executed command."}
                supported_by = ["direct Python argv -S", "installed distribution metadata"]
            elif mismatch and absent_in_current and expected_contains:
                cause = {"code": "WRONG_PYTHON_INTERPRETER", "confidence": "high",
                         "summary": "The failed command ran a different Python executable from the explicitly selected environment containing the needed package.",
                         "recommendation": "Invoke the selected environment's Python executable; install and test with the same interpreter."}
                evidence["expected_interpreter"] = execution.get("expected_python", {}).get("label")
                evidence["executed_interpreter"] = execution.get("executed_python", {}).get("label")
                supported_by = ["explicit interpreter selection", "direct Python argv", "package present in expected runtime"]
            elif absent_in_current:
                cause = {"code": "MISSING_DISTRIBUTION_AT_RUNTIME", "confidence": "high" if baseline_owners else "medium",
                         "summary": "An import failed, and a candidate baseline distribution is absent in the failing interpreter. An interpreter-selection issue cannot be ruled out without execution provenance.",
                         "recommendation": "Confirm the executed interpreter, then install the declared package into that environment."}
                supported_by = [c for c in ("PACKAGE_MISSING", "UNSATISFIED_RUNTIME_DEPENDENCY") if c in codes]
            else:
                cause = {"code": "PYTHON_IMPORT_FAILURE", "confidence": "low",
                         "summary": "A Python module import failed; installed distribution metadata alone cannot establish its cause.",
                         "recommendation": "Inspect executed interpreter, sys.path, module ownership, site startup flags and editable installs."}
        elif kind == "resolution_unavailable":
            evidence = {"distribution_requested": args[0]}
            cause = {"code": "PACKAGE_RESOLUTION_UNAVAILABLE", "confidence": "medium",
                     "summary": "The installer found no eligible distribution for the requested requirement.",
                     "recommendation": "Check configured indexes, exact version, Python requires-python, platform tags and network access; do not assume the package was unpublished."}
        elif kind == "resolver_conflict":
            cause = {"code": "DEPENDENCY_RESOLUTION_CONFLICT", "confidence": "medium",
                     "summary": "The package manager reported an unsatisfiable dependency resolution.",
                     "recommendation": "Inspect the installer's constraint explanation, selected extras/groups and constraints/lockfiles; do not loosen versions blindly."}
        elif kind == "wheel_build":
            evidence = {"wheel_distribution": args[0]}
            cause = {"code": "WHEEL_BUILD_FAILED", "confidence": "medium",
                     "summary": "A source distribution failed to build a Python wheel; the compiler or missing prerequisite is not yet known.",
                     "recommendation": "Inspect the first compiler/build-backend error, toolchain and Python header dependencies before changing package pins."}
        elif kind == "native_symbol_version":
            evidence = {"required_symbol_version": args[0]}
            cause = {"code": "NATIVE_SYMBOL_VERSION_MISSING", "confidence": "high",
                     "summary": "The dynamic loader reports a missing versioned native symbol.",
                     "recommendation": "Inspect the extension's required ABI symbols and target runtime library exports, then align build/runtime compatibility."}
        elif kind == "dll_load":
            evidence = {"module": args[0]}
            cause = {"code": "WINDOWS_DLL_LOAD_FAILURE", "confidence": "medium",
                     "summary": "A Windows native extension could not load one or more DLL dependencies.",
                     "recommendation": "Inspect architecture, runtime DLL search paths and Visual C++ runtime compatibility; the exact missing DLL is not established."}
        elif kind == "import_symbol":
            symbol, module = args
            root = canonical_name(module.split(".")[0])
            evidence = {"missing_symbol": symbol, "module": module}
            if root in source and root in target and source[root] != target[root]:
                cause = {"code": "PACKAGE_API_VERSION_INCOMPATIBILITY", "confidence": "medium",
                         "summary": "An import symbol is missing from a distribution whose installed version differs from the baseline.",
                         "recommendation": "Check the package's API against the application's declared compatible version range."}
                supported_by = [c for c in ("PACKAGE_VERSION_DRIFT", "UNSATISFIED_VERSION_CONSTRAINT") if c in codes]
            else:
                cause = {"code": "PYTHON_IMPORT_SYMBOL_FAILURE", "confidence": "low",
                         "summary": "A requested symbol is absent; version drift alone does not establish causation.",
                         "recommendation": "Verify the import target, selected package distribution, and exported API."}
        elif kind == "native_missing":
            # Never include directories or absolute paths from potentially sensitive logs.
            soname = args[0].replace("\\", "/").rsplit("/", 1)[-1]
            evidence = {"library": soname}
            cause = {"code": "NATIVE_LIBRARY_LOAD_FAILURE", "confidence": "high",
                     "summary": "The dynamic loader could not locate a shared library.",
                     "recommendation": "Check the runtime image and library search paths; package or mount the intended ABI-compatible library."}
        elif kind == "native_symbol":
            evidence = {"missing_symbol": args[0]}
            cause = {"code": "NATIVE_SYMBOL_LOAD_FAILURE", "confidence": "high",
                     "summary": "A loaded native library does not export a required symbol.",
                     "recommendation": "Compare native library versions/exports and rebuild against the supported target ABI."}
    return {
        "schema_version": "1.0",
        "exit_code": exit_code,
        "command_failed": exit_code != 0,
        "observed_failure": observed,
        "root_cause_hypothesis": cause if exit_code != 0 else None,
        "evidence": evidence if exit_code != 0 else {},
        "environment_correlations": supported_by if exit_code != 0 else [],
        "execution_provenance": execution,
        "drift": drift,
        "disclaimer": "Signatures confirm observed exceptions; root-cause explanations require reproduction. "
                      "Distribution names need not match import names. Raw logs and full interpreter paths are not included in this report.",
    }
