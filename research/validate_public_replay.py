#!/usr/bin/env python3
"""Validate bounded public resolver replay and prevent holdout contamination."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

ISSUE = "https://github.com/cvsz/zbase/issues/19"


def validate(record: object) -> dict[str, object]:
    if not isinstance(record, dict):
        raise ValueError("Expected a JSON object")
    if record.get("schema_version") != "1.0":
        raise ValueError("Wrong schema version")
    if record.get("study_role") != "public_development_exemplar":
        raise ValueError("Known-fix replay must remain a development exemplar")
    if record.get("is_independent_blind_test") is not False:
        raise ValueError("Cannot present public known-fix case as blind")
    if record.get("may_be_counted_in_holdout_accuracy") is not False:
        raise ValueError("Known-fix case must be excluded from field accuracy")
    if record.get("experiment") != "public_pypi_minimal_pair_resolution":
        raise ValueError("Unexpected experiment")
    if (record.get("source") or {}).get("issue") != ISSUE:
        raise ValueError("Unexpected issue source")
    if record.get("input_versions") != {
        "pytest": "9.0.3",
        "conflicting_pytest_asyncio": "1.2.0",
        "corrected_pytest_asyncio": "1.4.0",
    }:
        raise ValueError("Unexpected tested package pair")
    outcomes = record.get("outcomes")
    if not isinstance(outcomes, dict) or set(outcomes) != {"conflict", "corrected"}:
        raise ValueError("Expected both experiments")
    broken, fixed = outcomes["conflict"], outcomes["corrected"]
    if not isinstance(broken, dict) or not isinstance(fixed, dict):
        raise ValueError("Malformed outcomes")
    if broken.get("case") != "conflict" or fixed.get("case") != "corrected":
        raise ValueError("Experiment cases mismatch")
    if not isinstance(broken.get("exit_code"), int) or broken["exit_code"] == 0:
        raise ValueError("Initial package pair must fail resolution")
    if broken.get("has_resolution_impossible") is not True:
        raise ValueError("Missing pip conflict signature")
    if broken.get("has_conflict_explanation") is not True:
        raise ValueError("Missing resolver explanation")
    if fixed.get("exit_code") != 0 or record.get("status") != "minimal_pair_reproduced":
        raise ValueError("Corrected minimal pair did not resolve")
    for case in (broken, fixed):
        value = case.get("combined_output_sha256")
        if not isinstance(value, str) or len(value) != 64 or any(c not in "0123456789abcdef" for c in value):
            raise ValueError("Expected hashed—not raw—command output")
    prohibited = {"raw_log", "raw_output", "ground_truth", "blind_score", "independent_accuracy"}
    if prohibited & record.keys() or any(prohibited & case.keys() for case in outcomes.values()):
        raise ValueError("Private logs and blind/accuracy claims are prohibited")
    return {
        "status": "validated",
        "experiment": record["experiment"],
        "conflict_exit": broken["exit_code"],
        "correction_exit": fixed["exit_code"],
        "study_role": record["study_role"],
        "holdout_accuracy_eligible": False,
    }


def validate_disclosed_case() -> dict[str, object]:
    ledger_file = Path(__file__).resolve().parent / "public-exemplars" / "CI-0002.json"
    case = json.loads(ledger_file.read_text(encoding="utf-8"))
    if case.get("id") != "CI-0002" or case.get("source_repo") != "cvsz/zbase":
        raise ValueError("Public case source or ID changed")
    if case.get("study_role") != "public_development_exemplar":
        raise ValueError("Disclosed case cannot be used as blind ground truth")
    if case.get("holdout_eligible") is not False or case.get("independently_blind_adjudicated") is not False:
        raise ValueError("Disclosed case must be excluded from holdout metrics")
    return {"case": case["id"], "holdout_eligible": False}


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--input", type=Path, required=True)
    args = p.parse_args()
    result = validate(json.loads(args.input.read_text(encoding="utf-8")))
    result["public_case_exclusion"] = validate_disclosed_case()
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
