"""Run real, intentionally broken offline installs and measure diagnoses.

Controlled fault injection gives known expected causes; it is not an independent
real-world evaluation corpus. No network required, no Docker required.
"""
from __future__ import annotations

import argparse
import json
import os
import pathlib
import shutil
import subprocess
import sys
import time
import venv
from typing import Any

ROOT = pathlib.Path(__file__).resolve().parents[1]
LAB = ROOT / "lab"
SRC = ROOT / "src"
sys.path.insert(0, str(SRC))

from envguard_ci.collection import snapshot
from envguard_ci.failure import diagnose_failure
from envguard_ci.model import write_json
from envguard_ci.provenance import execution_context
from scripts.build_wheels import build_all

CASES = {
    "healthy": {"install": ["riskbatch==0.1.0", "scorecodec==1.0.0"], "expected": None},
    "missing_dependency": {"install": ["riskbatch==0.1.0"], "expected": "MISSING_DISTRIBUTION_AT_RUNTIME"},
    "wrong_interpreter": {"install": [], "expected": "WRONG_PYTHON_INTERPRETER"},
    "site_disabled": {"install": ["riskbatch==0.1.0", "scorecodec==1.0.0"], "expected": "PYTHON_SITE_DISABLED", "site_disabled": True},
    "old_dependency_api": {"install": ["riskbatch==0.1.0", "scorecodec==0.8.0"], "expected": "PACKAGE_API_VERSION_INCOMPATIBILITY"},
    "compatible_upgrade": {"install": ["riskbatch==0.1.0", "scorecodec==1.1.0"], "expected": None},
    "business_assertion_failure": {"install": ["riskbatch==0.1.0", "scorecodec==1.0.0"],
                                   "expected": None, "unrelated_failure": True},
    "installer_unavailable": {"install": [], "expected": "PACKAGE_RESOLUTION_UNAVAILABLE",
                              "installer": ["scorecodec==999.0.0"]},
    "installer_conflict": {"install": [], "expected": "DEPENDENCY_RESOLUTION_CONFLICT",
                           "installer": ["riskbatch==0.1.0", "scorecodec==0.8.0"]},
    "native_library_missing": {"install": ["riskbatch==0.1.0", "scorecodec==1.0.0"], "expected": "NATIVE_LIBRARY_LOAD_FAILURE", "native": "missing"},
    "native_symbol_mismatch": {"install": ["riskbatch==0.1.0", "scorecodec==1.0.0"], "expected": "NATIVE_SYMBOL_LOAD_FAILURE", "native": "old"},
}


def invoke(cmd: list[str], *, env: dict[str, str] | None = None,
           cwd: pathlib.Path | None = None, require: bool = False) -> subprocess.CompletedProcess[str]:
    result = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                            errors="replace", cwd=cwd, env=env, timeout=90)
    if require and result.returncode:
        raise RuntimeError(f"Command failed: {cmd[0]} (exit={result.returncode})\n{result.stderr[-2000:]}")
    return result


def python_in(venv_dir: pathlib.Path) -> pathlib.Path:
    return venv_dir / ("Scripts/python.exe" if sys.platform == "win32" else "bin/python")


def prepare_env(where: pathlib.Path, wheels: pathlib.Path, packages: list[str]) -> pathlib.Path:
    if where.exists():
        shutil.rmtree(where)
    venv.EnvBuilder(with_pip=True, clear=False).create(where)
    python = python_in(where)
    if packages:
        invoke([str(python), "-m", "pip", "install", "--no-index", "--disable-pip-version-check",
                "--no-deps", "--find-links", str(wheels), *packages], require=True)
    return python


def compile_libs(where: pathlib.Path) -> dict[str, pathlib.Path] | None:
    compiler = shutil.which("g++") or shutil.which("clang++")
    if not compiler or sys.platform != "linux":
        return None
    where.mkdir(parents=True, exist_ok=True)
    out: dict[str, pathlib.Path] = {}
    for kind, filename in (("good", "scoremath_good.cpp"), ("old", "scoremath_old.cpp")):
        target = where / kind / "libscoremath.so"
        target.parent.mkdir(parents=True, exist_ok=True)
        invoke([compiler, "-shared", "-fPIC", "-std=c++17", str(LAB / "native" / filename),
                "-o", str(target)], require=True)
        out[kind] = target
    return out


def execute_case(python: pathlib.Path, *, libpath: str | None = None,
                 native: bool = False, site_disabled: bool = False) -> subprocess.CompletedProcess[str]:
    env = os.environ.copy()
    if libpath is not None:
        env["RISKBATCH_NATIVE_LIBRARY"] = libpath
    return invoke([str(python)] + (["-S"] if site_disabled else []) + ["-m", "riskbatch"] + (["--native"] if native else []),
                  env=env, cwd=LAB / "project")


def run(out: pathlib.Path, *, names: list[str] | None = None) -> dict[str, Any]:
    t0 = time.monotonic()
    out.mkdir(parents=True, exist_ok=True)
    wheels = out / "wheels"
    built = build_all(wheels)
    native_libs = compile_libs(out / "native-libs")
    baseline_python = prepare_env(out / "venvs" / "baseline", wheels,
                                  ["riskbatch==0.1.0", "scorecodec==1.0.0"])
    baseline_snap = snapshot(project=LAB / "project", python=str(baseline_python))
    write_json(baseline_snap, str(out / "baseline.json"))
    baseline_run = execute_case(baseline_python)
    if baseline_run.returncode:
        raise RuntimeError("Known-good baseline did not run:\n" + baseline_run.stderr[-2000:])
    records: list[dict[str, Any]] = []
    for name, scenario in CASES.items():
        if names is not None and name not in names:
            continue
        if scenario.get("native") and not native_libs:
            records.append({"scenario": name, "status": "skipped", "reason": "Linux C++ compiler unavailable"})
            continue
        candidate_python = (baseline_python if name == "healthy" or scenario.get("native")
                            else prepare_env(out / "venvs" / name, wheels, scenario["install"]))
        libpath = None
        if scenario.get("native") == "missing":
            libpath = str(out / "does-not-exist" / "libscoremath.so")
        if scenario.get("native") == "old":
            libpath = str(native_libs["old"])
        if scenario.get("native"):
            healthy_native = execute_case(baseline_python, libpath=str(native_libs["good"]), native=True)
            if healthy_native.returncode:
                raise RuntimeError("Known-good native baseline failed: " + healthy_native.stderr[-2000:])
        if scenario.get("installer"):
            cmd = [str(candidate_python), "-m", "pip", "install", "--no-index", "--disable-pip-version-check",
                   "--find-links", str(wheels), *scenario["installer"]]
            proc = invoke(cmd, cwd=LAB / "project")
        elif scenario.get("unrelated_failure"):
            cmd = [str(candidate_python), "-c", "raise AssertionError('business rule deliberately violated')"]
            proc = invoke(cmd, cwd=LAB / "project")
        else:
            cmd = [str(candidate_python)] + (["-S"] if scenario.get("site_disabled") else []) + ["-m", "riskbatch"]
            proc = execute_case(candidate_python, libpath=libpath, native=bool(scenario.get("native")),
                                site_disabled=bool(scenario.get("site_disabled")))
        snap = snapshot(project=LAB / "project", python=str(candidate_python))
        expected_python = baseline_python if name == "wrong_interpreter" else candidate_python
        context = execution_context(command=cmd, project=LAB / "project", expected_python=str(expected_python))
        report = diagnose_failure(baseline_snap, snap, log=proc.stdout + "\n" + proc.stderr,
                                  exit_code=proc.returncode, execution=context,
                                  expected_snapshot=baseline_snap if name == "wrong_interpreter" else snap)
        case_dir = out / "cases" / name
        case_dir.mkdir(parents=True, exist_ok=True)
        write_json(snap, str(case_dir / "current.json"))
        write_json(context, str(case_dir / "execution.json"))
        write_json(report, str(case_dir / "diagnosis.json"))
        (case_dir / "execution.log").write_text(proc.stdout + "\n" + proc.stderr, encoding="utf-8")
        predicted = (report.get("root_cause_hypothesis") or {}).get("code")
        expected = scenario["expected"]
        correctly_failed = (proc.returncode != 0) == (expected is not None or scenario.get("unrelated_failure", False))
        success = predicted == expected and correctly_failed
        record = {"scenario": name, "exit_code": proc.returncode, "expected": expected,
                  "predicted": predicted, "passed": success,
                  "is_non_environment_failure": bool(scenario.get("unrelated_failure")),
                  "drift_findings": sorted({f["code"] for f in report["drift"]["findings"]})}
        records.append(record)
        print(f"{'PASS' if success else 'FAIL'} {name:25} exit={proc.returncode} expected={expected} predicted={predicted}", flush=True)
    evaluated = [r for r in records if r.get("status") != "skipped"]
    failed = [r for r in evaluated if r["expected"] is not None]
    benign = [r for r in evaluated if r["expected"] is None and not r["is_non_environment_failure"]]
    unrelated = [r for r in evaluated if r["is_non_environment_failure"]]
    correct = sum(r["passed"] for r in failed)
    metrics = {
        "controlled_cases": len(evaluated),
        "failed_cases": len(failed),
        "benign_controls": len(benign),
        "unrelated_failing_controls": len(unrelated),
        "correct_injected_labels_at_1": correct,
        "injected_label_accuracy_at_1": (correct / len(failed)) if failed else None,
        "correct_root_cause_at_1": correct,  # Backward-compatible legacy name; NOT a blind root-cause benchmark.
        "root_cause_accuracy_at_1": (correct / len(failed)) if failed else None,
        "benign_false_alarms": sum(r["predicted"] is not None for r in benign),
        "unrelated_failure_false_alarms": sum(r["predicted"] is not None for r in unrelated),
        "skipped_cases": len(records) - len(evaluated),
        "elapsed_seconds": round(time.monotonic() - t0, 2),
        "caveat": "Controlled injected failure-category labels, NOT independent root-cause accuracy on enterprise CI incidents.",
    }
    output = {"version": "1.0", "metrics": metrics, "cases": records}
    write_json(output, str(out / "benchmark.json"))
    print("RESULTS:", json.dumps(metrics, sort_keys=True), flush=True)
    return output


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=pathlib.Path, default=LAB / ".envguard-runs")
    parser.add_argument("--case", action="append", choices=sorted(CASES), help="Run only selected scenarios (repeatable)")
    args = parser.parse_args()
    summary = run(args.out.resolve(), names=args.case)
    if any(not case.get("passed", True) for case in summary["cases"]):
        raise SystemExit(1)
