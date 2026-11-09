"""Deterministic, explainable mismatch rules. No log hallucinations or ML scoring."""

from __future__ import annotations

import re
from typing import Any, Iterable

from .model import canonical_name, fingerprint, validate_snapshot
from .graph import graph
from .requirements import python_satisfies

_SEVERITY = {"critical": 0, "high": 1, "medium": 2, "low": 3, "info": 4}
_REQ = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_NUMVER = re.compile(r"^(\d+)\.(\d+)(?:\.(\d+))?")


def issue(code: str, severity: str, confidence: str, summary: str,
          evidence: Any, recommendation: str) -> dict[str, Any]:
    return {"code": code, "severity": severity, "confidence": confidence,
            "summary": summary, "evidence": evidence, "recommendation": recommendation}


def _ver(version: str | None) -> tuple[int, int, int] | None:
    if not isinstance(version, str):
        return None
    m = _NUMVER.match(version)
    return (int(m.group(1)), int(m.group(2)), int(m.group(3) or 0)) if m else None


def supports_python(spec: str | None, version: str | None) -> bool | None:
    """Full PEP 440 validation using PyPA packaging; unknown stays unknown."""
    return python_satisfies(spec, version)


def local_checks(snapshot: dict[str, Any], *, extras: Iterable[str] = ()) -> list[dict[str, Any]]:
    validate_snapshot(snapshot)
    found: list[dict[str, Any]] = []
    spec = snapshot["project"].get("requires_python")
    version = snapshot["runtime"].get("version")
    if supports_python(spec, version) is False:
        found.append(issue("PROJECT_PYTHON_UNSUPPORTED", "high", "high",
                           "Interpreter does not satisfy project requires-python",
                           {"requires_python": spec, "current_python": version},
                           "Select a compatible Python interpreter or correct the declared project constraint."))
    declared = snapshot.get("fingerprints") or {}
    computed = fingerprint(snapshot)
    for part in ("spec", "runtime"):
        if declared.get(part) and declared[part] != computed[part]:
            found.append(issue("FINGERPRINT_INVALID", "high", "high",
                               f"Stored {part} fingerprint does not match snapshot contents",
                               {"stored": declared[part], "recomputed": computed[part]},
                               "Recapture the environment; do not trust a modified snapshot."))
    manager = snapshot["project"].get("detected_managers") or []
    # More than one manager *can* be intentional (exports / migration).
    dedicated_locks = set(manager) & {"uv", "poetry", "pylock", "pipenv"}
    if len(dedicated_locks) > 1:
        found.append(issue("MULTIPLE_LOCK_FORMATS", "low", "high",
                           "Project contains several lockfile formats",
                           {"managers": sorted(dedicated_locks)},
                           "Declare one authoritative lockfile for CI; other formats may be intentional exports."))
    # A marker-aware installed metadata graph: applies PEP 508 environment
    # markers, propagates explicitly selected extras, and checks PEP 440
    # specifiers. Only active requirements can generate findings.
    evaluated = graph(snapshot, scope="environment", extras=extras)
    missing: dict[str, list[str]] = {}
    conflicting: list[dict[str, str]] = []
    for edge in evaluated["edges"]:
        if edge["status"] == "required_missing":
            missing.setdefault(edge["to"], []).append(edge["from"])
        elif edge["status"] == "required_incompatible":
            conflicting.append({
                "dependency": edge["to"], "required": edge["requirement"],
                "installed": edge["installed_version"], "required_by": edge["from"],
            })
    if conflicting:
        found.append(issue("UNSATISFIED_VERSION_CONSTRAINT", "high", "high",
                           "Installed package versions violate applicable PEP 440 constraints",
                           {"conflicts": sorted(conflicting, key=lambda x: (x["dependency"], x["required_by"]))},
                           "Review dependency declarations and lockfile; install a supported version using the same interpreter."))
    if missing:
        found.append(issue("UNSATISFIED_RUNTIME_DEPENDENCY", "high", "medium",
                           "Applicable declared dependencies are not installed",
                           {"missing": {k: sorted(set(v)) for k, v in sorted(missing.items())}},
                           "Check interpreter selection and the installation step; run the package manager's consistency check."))
    native = snapshot.get("native") or {}
    if native.get("scan_status") == "complete":
        available = set(native.get("libraries") or [])
        missing_libs: dict[str, list[str]] = {}
        for req in native.get("requirements") or []:
            for lib in req.get("needed") or []:
                if lib not in available:
                    missing_libs.setdefault(lib, []).append(req.get("extension", "unknown"))
        if missing_libs:
            found.append(issue("NATIVE_LIBRARY_UNRESOLVED", "medium", "medium",
                               "Native libraries were not found in the dynamic linker cache",
                               {"libraries": {k: sorted(set(v)) for k, v in sorted(missing_libs.items())}},
                               "Check rpath and vendored libraries before treating this as a genuine loader failure; inspect LD_DEBUG or the container image."))
        # Compare symbols only when a provider has been successfully scanned.
        provided = native.get("provided_symbols") or {}
        missing_syms: dict[str, dict[str, list[str]]] = {}
        for req in native.get("requirements") or []:
            required = set(req.get("symbol_versions") or [])
            if not required:
                continue
            known: set[str] = set()
            for lib in req.get("needed") or []:
                known.update(provided.get(lib) or [])
            # Only report a symbol family if provider symbols for that family
            # were successfully identified; otherwise it is not verifiable.
            for family in ("GLIBCXX_", "CXXABI_", "GLIBC_"):
                candidates = {v for v in required if v.startswith(family)}
                have = {v for v in known if v.startswith(family)}
                absent = sorted(candidates - have) if have else []
                if absent:
                    missing_syms.setdefault(req.get("extension", "unknown"), {})[family] = absent
        if missing_syms:
            found.append(issue("SYMBOL_VERSION_UNAVAILABLE", "high", "medium",
                               "A binary requests symbol versions absent from scanned providers",
                               {"missing_symbols": missing_syms},
                               "Rebuild against the target ABI baseline or update the runtime library after checking compatibility."))
    return found


def diff(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    validate_snapshot(baseline)
    validate_snapshot(current)
    findings = local_checks(current)
    b = baseline["runtime"]
    c = current["runtime"]
    bp = baseline["platform"]
    cp = current["platform"]
    if b.get("environment_kind") != c.get("environment_kind"):
        findings.append(issue("ENVIRONMENT_KIND_DRIFT", "low", "high",
                              "Environment isolation kinds differ (venv versus system)",
                              {"baseline": b.get("environment_kind"), "current": c.get("environment_kind")},
                              "Confirm tests use the intended Python executable and install destination."))
    if b.get("implementation") != c.get("implementation"):
        findings.append(issue("PYTHON_IMPLEMENTATION_MISMATCH", "high", "high",
                              "Python implementations differ", {"baseline": b.get("implementation"), "current": c.get("implementation")},
                              "Use the same implementation in CI and development, or test both explicitly."))
    bv, cv = _ver(b.get("version")), _ver(c.get("version"))
    if bv and cv and bv[:2] != cv[:2]:
        findings.append(issue("PYTHON_MINOR_MISMATCH", "high", "high",
                              "Python major/minor versions differ",
                              {"baseline": b.get("version"), "current": c.get("version")},
                              "Pin the intended interpreter minor version in the project and CI runner."))
    elif bv and cv and bv != cv:
        findings.append(issue("PYTHON_PATCH_MISMATCH", "info", "high",
                              "Python patch versions differ",
                              {"baseline": b.get("version"), "current": c.get("version")},
                              "Review only if this change impacts native dependencies or known interpreter fixes."))
    for key, code, severity, message in (
        ("os", "OS_MISMATCH", "high", "Operating systems differ"),
        ("arch", "ARCH_MISMATCH", "high", "CPU architectures differ"),
        ("libc", "LIBC_MISMATCH", "medium", "C library/runtime identifiers differ"),
    ):
        x, y = bp.get(key), cp.get(key)
        if x and y and x != y:
            findings.append(issue(code, severity, "high", message,
                                  {"baseline": x, "current": y},
                                  "Build and validate native wheels on the same target platform, or publish per-platform artifacts."))
    if b.get("soabi") and c.get("soabi") and b["soabi"] != c["soabi"]:
        findings.append(issue("ABI_MISMATCH", "high", "high",
                              "CPython extension ABI identifiers differ",
                              {"baseline": b["soabi"], "current": c["soabi"]},
                              "Use wheels compatible with the target Python ABI; rebuild extensions as needed."))
    bf = {item["name"]: item["sha256"] for item in baseline["project"].get("files") or []}
    cf = {item["name"]: item["sha256"] for item in current["project"].get("files") or []}
    for name in sorted(set(bf) - set(cf)):
        findings.append(issue("LOCKFILE_MISSING" if ("lock" in name or name.startswith("pylock")) else "PROJECT_FILE_MISSING",
                              "high", "high", f"Project file missing: {name}",
                              {"file": name, "baseline_sha256": bf[name]},
                              "Restore the expected file, or intentionally migrate the CI installation workflow."))
    for name in sorted(set(bf) & set(cf)):
        if bf[name] != cf[name]:
            findings.append(issue("LOCKFILE_CHANGED" if ("lock" in name or name.startswith("pylock")) else "PROJECT_FILE_CHANGED",
                                  "medium", "high", f"Project file has changed: {name}",
                                  {"file": name, "baseline_sha256": bf[name], "current_sha256": cf[name]},
                                  "Review the dependency/configuration diff and ensure CI installs from the intended file."))
    bpacks = {canonical_name(p["name"]): p for p in baseline["packages"]}
    cpacks = {canonical_name(p["name"]): p for p in current["packages"]}
    missing = sorted(set(bpacks) - set(cpacks))
    if missing:
        findings.append(issue("PACKAGE_MISSING", "high", "high",
                              f"{len(missing)} baseline packages absent from current environment",
                              {"packages": [{"name": name, "baseline_version": bpacks[name]["version"]} for name in missing]},
                              "Check that CI installs dependencies using the same interpreter and intended dependency groups."))
    extras = sorted(set(cpacks) - set(bpacks))
    if extras:
        findings.append(issue("PACKAGE_ADDED", "info", "high",
                              f"{len(extras)} packages present only in current environment",
                              {"packages": extras},
                              "Verify additional packages are intentional; they do not necessarily indicate a defect."))
    changed = [{"name": name, "baseline": bpacks[name]["version"], "current": cpacks[name]["version"]}
               for name in sorted(set(bpacks) & set(cpacks))
               if bpacks[name]["version"] != cpacks[name]["version"]]
    metadata_changed = [name for name in sorted(set(bpacks) & set(cpacks))
                        if sorted(bpacks[name].get("requires") or []) != sorted(cpacks[name].get("requires") or [])]
    if metadata_changed:
        findings.append(issue("PACKAGE_METADATA_DRIFT", "medium", "high",
                              "Installed distributions declare different dependency metadata",
                              {"packages": metadata_changed},
                              "Compare installed wheel metadata and build provenance; identical version strings do not prove identical distributions."))
    if changed:
        findings.append(issue("PACKAGE_VERSION_DRIFT", "medium", "high",
                              f"{len(changed)} installed package versions differ",
                              {"packages": changed},
                              "Reconcile the lockfile and resolved install; version drift is not by itself proof of the failure."))
    tags_changed = []
    for name in sorted(set(bpacks) & set(cpacks)):
        bt = sorted(bpacks[name].get("wheel_tags") or [])
        ct = sorted(cpacks[name].get("wheel_tags") or [])
        if bt and ct and bt != ct:
            tags_changed.append({"name": name, "baseline": bt, "current": ct})
    if tags_changed:
        findings.append(issue("WHEEL_TAG_DIFFERENCE", "medium", "high",
                              "Installed distribution wheel compatibility tags differ",
                              {"packages": tags_changed},
                              "Check binary wheel selection and platform compatibility."))
    findings.sort(key=lambda x: (_SEVERITY[x["severity"]], x["code"]))
    significant = any(f["severity"] in ("critical", "high", "medium") for f in findings)
    return {
        "schema_version": "1.0", "status": "drift_detected" if significant else "no_significant_drift_detected",
        "disclaimer": "Differences and local checks are evidence, not proof of CI failure causation or complete environment equivalence.",
        "baseline_fingerprints": baseline.get("fingerprints") or fingerprint(baseline),
        "current_fingerprints": current.get("fingerprints") or fingerprint(current),
        "findings": findings, "counts": {severity: sum(f["severity"] == severity for f in findings)
                                           for severity in _SEVERITY},
    }


def doctor(snapshot: dict[str, Any], *, extras: Iterable[str] = ()) -> dict[str, Any]:
    validate_snapshot(snapshot)
    findings = sorted(local_checks(snapshot, extras=extras), key=lambda x: (_SEVERITY[x["severity"]], x["code"]))
    dependencies = graph(snapshot, scope="environment", extras=extras)
    return {"dependency_summary": dependencies["stats"], "selected_extras": dependencies["selected_extras"], "schema_version": "1.0", "status": "findings" if findings else "no_local_findings",
            "disclaimer": "Local checks are not a proof of reproducibility or CI compatibility.",
            "fingerprints": snapshot.get("fingerprints") or fingerprint(snapshot),
            "findings": findings, "counts": {s: sum(f["severity"] == s for f in findings) for s in _SEVERITY}}
