"""One command to reproduce and diagnose a wrong-Python CI failure.

Creates disposable venvs under lab/.envguard-runs; no registry download is needed.
Exits 0 only when the observed diagnosis and evidence ledger are correct.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "lab"))
from lab.run_lab import run, python_in  # noqa: E402


def main() -> int:
    out = ROOT / "lab" / ".envguard-runs"
    benchmark = run(out, names=["wrong_interpreter"])
    if not benchmark["cases"][0].get("passed"):
        return 1
    expected = python_in(out / "venvs" / "baseline")
    actual = python_in(out / "venvs" / "wrong_interpreter")
    report_path = out / "demo-ci-report.json"
    env = os.environ.copy()
    env["PYTHONPATH"] = str(ROOT / "src") + os.pathsep + env.get("PYTHONPATH", "")
    cmd = [sys.executable, "-m", "envguard_ci", "ci-run", "--project", str(ROOT / "lab" / "project"),
           "--python", str(expected), "--baseline", str(out / "baseline.json"),
           "--snapshot-out", str(out / "demo-ci-snapshot.json"),
           "--report-out", str(report_path), "--", str(actual), "-m", "riskbatch"]
    executed = subprocess.run(cmd, cwd=ROOT, env=env, timeout=90, check=False)
    if executed.returncode == 0:
        raise AssertionError("The intentionally failing job unexpectedly succeeded")
    report = json.loads(report_path.read_text(encoding="utf-8"))
    predicted = (report["failure_analysis"].get("root_cause_hypothesis") or {}).get("code")
    incident = out / "demo-ci-report.md"
    if predicted != "WRONG_PYTHON_INTERPRETER" or not incident.is_file():
        raise AssertionError(f"Demo did not identify the wrong Python: {predicted}")
    md = incident.read_text(encoding="utf-8")
    if "Evidence ledger" not in md or report.get("execution_provenance", {}).get("interpreter_match") is not False:
        raise AssertionError("The evidence-linked dossier is incomplete")
    print(f"DEMO PASS: {predicted}; failing exit={executed.returncode}; dossier={incident}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
