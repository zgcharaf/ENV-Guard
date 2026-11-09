#!/usr/bin/env python3
"""Public external incident replay: pytest / pytest-asyncio resolver conflict.

The pinned versions and diagnosis were selected from an already known public
issue and fix, so this is a DEVELOPMENT EXEMPLAR, not a blinded accuracy test.
Recreates only the conflicting PyPI package pair in pip's dry-run resolver. It
does not clone or execute the third-party application, or install those deps.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys
from typing import Any

REPO = Path(__file__).resolve().parents[1]
PUBLIC_ISSUE = "https://github.com/cvsz/zbase/issues/19"
FAILED_CI = "https://github.com/cvsz/zbase/actions/runs/42434561391"
FIX_PR = "https://github.com/cvsz/zbase/pull/24"
FIXED_CI = "https://github.com/cvsz/zbase/actions/runs/42434951881"


def command(version: str) -> list[str]:
    """Resolve a fixed all-wheel-only pair from public PyPI without installing it."""
    if version not in {"1.2.0", "1.4.0"}:
        raise ValueError("Only the two preregistered pytest-asyncio versions are permitted")
    return [
        sys.executable, "-m", "pip", "--isolated", "install",
        "--dry-run", "--ignore-installed", "--only-binary=:all:",
        "--no-input", "--disable-pip-version-check", "--index-url",
        "https://pypi.org/simple", "pytest==9.0.3",
        f"pytest-asyncio=={version}",
    ]


def observed_outcome(*, returncode: int, stdout: str, case: str,
                     report: dict[str, Any] | None) -> dict[str, Any]:
    hypothesis = ((report or {}).get("failure_analysis") or {}).get(
        "root_cause_hypothesis") or {}
    if not isinstance(hypothesis, dict):
        hypothesis = {}
    return {
        "case": case,
        "exit_code": returncode,
        "has_resolution_impossible": "ResolutionImpossible" in stdout,
        "has_conflict_explanation": (
            "conflicting dependencies" in stdout
            or "The conflict is caused by" in stdout
        ),
        "combined_output_sha256": hashlib.sha256(stdout.encode("utf-8")).hexdigest(),
        "envguard_observed_failure": ((report or {}).get("failure_analysis") or {}).get(
            "observed_failure"),
        "envguard_hypothesis": hypothesis.get("code"),
        "envguard_confidence": hypothesis.get("confidence"),
    }


def replay(*, result_dir: Path, timeout: int) -> dict[str, Any]:
    result_dir = result_dir.resolve()
    result_dir.mkdir(parents=True, exist_ok=True)
    outcomes: dict[str, dict[str, Any]] = {}
    env = dict(os.environ)
    # Avoid local user pip indexes, custom CA paths and startup overrides.
    # pip --isolated also ignores configuration and environment variables.
    for key in ("PYTHONPATH", "PYTHONHOME", "PIP_INDEX_URL",
                "PIP_EXTRA_INDEX_URL", "PIP_TRUSTED_HOST"):
        env.pop(key, None)

    for label, version in (("conflict", "1.2.0"), ("corrected", "1.4.0")):
        case_dir = result_dir / label
        case_dir.mkdir(parents=True, exist_ok=True)
        args = [
            sys.executable, "-m", "envguard_ci", "ci-run",
            "--project", str(REPO), "--python", sys.executable,
            "--snapshot-out", str(case_dir / "snapshot.json"),
            "--report-out", str(case_dir / "report.json"), "--",
            *command(version),
        ]
        try:
            run = subprocess.run(
                args, cwd=REPO, env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace",
                timeout=timeout, check=False,
            )
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError(f"Public PyPI resolver replay timed out: {label}") from exc
        report_path = case_dir / "report.json"
        report = json.loads(report_path.read_text(encoding="utf-8")) if report_path.exists() else None
        outcomes[label] = observed_outcome(
            returncode=run.returncode,
            stdout=run.stdout + "\n" + run.stderr,
            case=label, report=report,
        )

    conflict = outcomes["conflict"]
    correction = outcomes["corrected"]
    outcome_supported = (
        conflict["exit_code"] != 0
        and conflict["has_resolution_impossible"]
        and conflict["has_conflict_explanation"]
        and correction["exit_code"] == 0
    )
    summary = {
        "schema_version": "1.0",
        "experiment": "public_pypi_minimal_pair_resolution",
        "study_role": "public_development_exemplar",
        "is_independent_blind_test": False,
        "may_be_counted_in_holdout_accuracy": False,
        "source": {
            "issue": PUBLIC_ISSUE, "failed_ci": FAILED_CI,
            "fix_pr": FIX_PR, "fixed_ci": FIXED_CI,
        },
        "environment": {
            "python": platform.python_version(),
            "platform": platform.platform(),
        },
        "input_versions": {
            "pytest": "9.0.3",
            "conflicting_pytest_asyncio": "1.2.0",
            "corrected_pytest_asyncio": "1.4.0",
        },
        "constraints": [
            "Only PyPI wheel metadata is resolved; no package install or code execution from the third-party repository.",
            "This minimal pair omits the original project's other requirements.",
            "PyPI is accessed over HTTPS using pip's isolated configuration.",
            "The fixing version was known before this replay; not an independent incident classification.",
            "EnvGuard's diagnostic fields are recorded, not assumed correct.",
        ],
        "outcomes": outcomes,
        "status": "minimal_pair_reproduced" if outcome_supported else "replay_not_confirmed",
    }
    summary_path = result_dir / "replay-summary.json"
    summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return summary


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=Path("research-results/public-replay"))
    p.add_argument("--timeout", type=int, default=180)
    args = p.parse_args()
    if not 20 <= args.timeout <= 300:
        p.error("Use a timeout between 20 and 300 seconds")
    result = replay(result_dir=args.out, timeout=args.timeout)
    print(json.dumps({
        "status": result["status"], "study_role": result["study_role"],
        "outcomes": result["outcomes"],
        "summary": str(args.out / "replay-summary.json"),
    }, indent=2))
    return 0 if result["status"] == "minimal_pair_reproduced" else 1


if __name__ == "__main__":
    raise SystemExit(main())
