"""Regenerate reproducible synthetic environment-drift snapshots."""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.model import fingerprint

ROOT = Path(__file__).parent / "fixtures"
ROOT.mkdir(parents=True, exist_ok=True)

base = {
    "schema_version": "1.0", "captured_at": "2026-10-21T00:00:00+00:00",
    "project": {
        "files": [{"name": "pyproject.toml", "sha256": "a" * 64},
                  {"name": "uv.lock", "sha256": "b" * 64}],
        "detected_managers": ["uv"], "requires_python": ">=3.11",
        "dependencies": ["requests>=2", "numpy>=2"]},
    "runtime": {"version": "3.12.7", "implementation": "CPython",
                "soabi": "cpython-312-x86_64-linux-gnu", "environment_kind": "venv",
                "executable_name": "python"},
    "platform": {"os": "linux", "arch": "x86_64", "libc": "glibc-2.36"},
    "packages": [
        {"name": "numpy", "version": "2.1.0", "requires": [], "wheel_tags": ["cp312-cp312-manylinux_2_17_x86_64"], "origin_hash": None},
        {"name": "requests", "version": "2.32.3", "requires": ["urllib3>=1.21"], "wheel_tags": ["py3-none-any"], "origin_hash": None},
        {"name": "urllib3", "version": "2.2.2", "requires": [], "wheel_tags": ["py3-none-any"], "origin_hash": None}],
    "native": {"scan_status": "disabled", "libraries": [], "requirements": [], "provided_symbols": {}, "notes": []},
}

def save(name, obj):
    obj["fingerprints"] = fingerprint(obj)
    (ROOT / f"{name}.json").write_text(json.dumps(obj, indent=2, sort_keys=True) + "\n")

save("baseline", base)

cases = {
    "python_minor": "PYTHON_MINOR_MISMATCH",
    "python_impl": "PYTHON_IMPLEMENTATION_MISMATCH",
    "operating_system": "OS_MISMATCH",
    "arch": "ARCH_MISMATCH",
    "libc": "LIBC_MISMATCH",
    "abi": "ABI_MISMATCH",
    "lockfile_changed": "LOCKFILE_CHANGED",
    "lockfile_missing": "LOCKFILE_MISSING",
    "package_missing": "PACKAGE_MISSING",
    "version_drift": "PACKAGE_VERSION_DRIFT",
    "wheel_tag": "WHEEL_TAG_DIFFERENCE",
    "unsatisfied_dependency": "UNSATISFIED_RUNTIME_DEPENDENCY",
    "project_python": "PROJECT_PYTHON_UNSUPPORTED",
    "multiple_lock_formats": "MULTIPLE_LOCK_FORMATS",
    "missing_native_lib": "NATIVE_LIBRARY_UNRESOLVED",
    "symbol_version": "SYMBOL_VERSION_UNAVAILABLE",
    "metadata_drift": "PACKAGE_METADATA_DRIFT",
    "environment_kind": "ENVIRONMENT_KIND_DRIFT"
}
for name, code in cases.items():
    current = copy.deepcopy(base)
    if name == "python_minor":
        current["runtime"]["version"] = "3.11.9"
    elif name == "environment_kind":
        current["runtime"]["environment_kind"] = "system"
    elif name == "metadata_drift":
        current["packages"][1]["requires"] = ["urllib3>=2.3"]
    elif name == "python_impl":
        current["runtime"]["implementation"] = "PyPy"
    elif name == "operating_system":
        current["platform"]["os"] = "windows"
    elif name == "arch":
        current["platform"]["arch"] = "aarch64"
    elif name == "libc":
        current["platform"]["libc"] = "glibc-2.31"
    elif name == "abi":
        current["runtime"]["soabi"] = "cpython-311-x86_64-linux-gnu"
    elif name == "lockfile_changed":
        current["project"]["files"][1]["sha256"] = "c" * 64
    elif name == "lockfile_missing":
        current["project"]["files"].pop()
    elif name == "package_missing":
        current["packages"].pop(0)
    elif name == "version_drift":
        current["packages"][1]["version"] = "2.31.0"
    elif name == "wheel_tag":
        current["packages"][0]["wheel_tags"] = ["cp312-cp312-manylinux_2_28_x86_64"]
    elif name == "unsatisfied_dependency":
        current["project"]["dependencies"].append("some-missing-library>=2")
    elif name == "project_python":
        current["project"]["requires_python"] = ">=3.13"
    elif name == "multiple_lock_formats":
        current["project"]["detected_managers"].append("poetry")
        current["project"]["files"].append({"name": "poetry.lock", "sha256": "d" * 64})
    elif name == "missing_native_lib":
        current["native"] = {"scan_status": "complete", "libraries": ["libc.so.6"],
                             "requirements": [{"extension": "_fast.so", "package": "numpy",
                                               "needed": ["libcustom.so.4"], "symbol_versions": []}],
                             "provided_symbols": {}, "notes": []}
    elif name == "symbol_version":
        current["native"] = {"scan_status": "complete", "libraries": ["libstdc++.so.6"],
                             "requirements": [{"extension": "_fast.so", "package": "numpy",
                                               "needed": ["libstdc++.so.6"],
                                               "symbol_versions": ["GLIBCXX_3.4.30"]}],
                             "provided_symbols": {"libstdc++.so.6": ["GLIBCXX_3.4.28", "GLIBCXX_3.4.29"]},
                             "notes": []}
    save(name, current)
(ROOT / "cases.json").write_text(json.dumps(cases, indent=2, sort_keys=True) + "\n")
print(f"Generated baseline plus {len(cases)} fixtures")
