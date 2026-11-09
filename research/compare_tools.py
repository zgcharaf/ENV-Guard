#!/usr/bin/env python3
"""Paired observational audit for EnvGuard's controlled offline lab.

Not a root-cause head-to-head leaderboard: pip check and uv pip check validate
installed package metadata; EnvGuard also observes actual process failures.
All tools inspect the SAME per-case virtual environments. No installation,
dependency mutation, external requests, or raw output persistence occurs here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import shutil
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]
BASELINE_ENV_CASES = {"healthy", "native_library_missing", "native_symbol_mismatch"}
METADATA_ELIGIBLE = {"missing_dependency", "old_dependency_api"}


def executable(path: Path) -> Path:
    return path / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def observed_command(arguments: list[str], *, env: dict[str, str], timeout: int = 40) -> dict[str, object]:
    started = time.perf_counter()
    try:
        p = subprocess.run(arguments, cwd=ROOT, env=env, capture_output=True,
                           text=True, encoding="utf-8", errors="replace",
                           timeout=timeout, check=False)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return {"status": "timeout_or_launch_error", "kind": type(exc).__name__,
                "elapsed_seconds": round(time.perf_counter() - started, 4)}
    output = p.stdout + "\n" + p.stderr
    return {
        "status": "completed",
        "exit_code": p.returncode,
        "nonzero_exit": p.returncode != 0,
        "elapsed_seconds": round(time.perf_counter() - started, 4),
        "output_sha256": hashlib.sha256(output.encode("utf-8")).hexdigest()
    }


def version_of(cmd: list[str], env: dict[str, str]) -> str | None:
    try:
        p = subprocess.run(cmd, cwd=ROOT, env=env, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=20, check=False)
        return (p.stdout or p.stderr).strip()[:150] if p.returncode == 0 else None
    except (subprocess.TimeoutExpired, OSError):
        return None


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--lab-output", type=Path, default=Path("research-results/lab"))
    parser.add_argument("--out", type=Path, default=Path("research-results/comparison.json"))
    parser.add_argument("--require-uv", action="store_true", help="Fail if uv is not present")
    args = parser.parse_args()
    lab = args.lab_output.resolve()
    raw = lab / "benchmark.json"
    if not raw.is_file():
        parser.error("First run: python lab/run_lab.py --out research-results/lab")
    source = json.loads(raw.read_text(encoding="utf-8"))
    if not isinstance(source.get("cases"), list):
        raise ValueError("Malformed controlled lab data")
    env = dict(os.environ)
    env.update({"PIP_DISABLE_PIP_VERSION_CHECK": "1", "PIP_NO_INDEX": "1",
                "UV_OFFLINE": "1", "UV_NO_PYTHON_DOWNLOADS": "1",
                "PYTHONNOUSERSITE": "1"})
    # Do not accidentally select project-specific Python from outside the target venv.
    env.pop("VIRTUAL_ENV", None)
    env.pop("PYTHONHOME", None)
    env.pop("PYTHONPATH", None)
    uv = shutil.which("uv")
    if args.require_uv and not uv:
        raise RuntimeError("uv not found. Install a pinned uv version in the runner, then retry.")
    rows = []
    for c in source["cases"]:
        name = c["scenario"]
        if c.get("status") == "skipped":
            rows.append({"scenario": name, "status": "skipped_in_lab",
                         "reason": c.get("reason", "unavailable")})
            continue
        name_env = "baseline" if name in BASELINE_ENV_CASES else name
        py = executable(lab / "venvs" / name_env)
        if not py.is_file():
            raise FileNotFoundError(f"Missing lab interpreter for {name}: {py}")
        methods: dict[str, object] = {}
        methods["pip_check"] = observed_command([str(py), "-m", "pip", "check"], env=env)
        if uv:
            methods["uv_pip_check"] = observed_command([uv, "pip", "check",
                                                         "--python", str(py)], env=env)
        else:
            methods["uv_pip_check"] = {"status": "not_installed"}
        rows.append({
            "scenario": name,
            "cohort": ("metadata_dependency" if name in METADATA_ELIGIBLE
                       else "other_or_control"),
            "injected_label": c["expected"],
            "envguard_label": c["predicted"],
            "envguard_label_match": c["passed"],
            "tools": methods,
        })
    summary = {}
    for tool in ("pip_check", "uv_pip_check"):
        applicable = [r["tools"][tool] for r in rows if r.get("cohort") == "metadata_dependency"]
        completed = [r for r in applicable if r["status"] == "completed"]
        summary[tool] = {
            "metadata_cases_evaluated": len(completed),
            "metadata_cases_total": len(applicable),
            "nonzero_exits_on_metadata_cases": sum(bool(r["nonzero_exit"]) for r in completed),
            "note": ("A nonzero exit is a metadata-consistency signal, not an exact "
                     "injected root-cause label. Neither tool is scored as wrong "
                     "for faults outside its intended scope."),
        }
    result = {
        "schema_version": "1",
        "study_type": "paired_controlled_environment_checks",
        "status": "observed" if uv else "partial_no_uv",
        "lab_source": "lab.run_lab controlled injected cases",
        "git_commit": version_of(["git", "rev-parse", "HEAD"], env),
        "versions": {
            "python": sys.version.split()[0],
            "pip": version_of([sys.executable, "-m", "pip", "--version"], env),
            "uv": version_of([uv, "--version"], env) if uv else None,
            "platform": platform.platform(),
        },
        "lab_metrics": source.get("metrics"),
        "comparators": summary,
        "cases": rows,
        "limitations": [
            "Fault labels are authored by EnvGuard developers, not independent reviewers.",
            "Comparator checks address dependency metadata and are not interchangeable with failure-cause attribution.",
            "The benchmark does not rerun full failing jobs under comparators or measure end-to-end investigation time.",
            "Elapsed time is one non-warm controlled invocation per case; do not claim comparative speed from it.",
            "An exit code is an observation, not proof that a tool diagnosed the injected failure cause.",
            "The lab's baseline-native C++ cases require Linux and a C++ compiler.",
            "No external enterprise failure corpus has been evaluated.",
        ],
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(json.dumps({"status": result["status"], "cases": len(rows),
                      "summary": summary, "output": str(args.out)}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
