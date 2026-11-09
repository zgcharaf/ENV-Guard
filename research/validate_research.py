#!/usr/bin/env python3
"""Validate the shape and scope of controlled benchmark evidence without inflating claims."""
import json
from pathlib import Path
import sys


def main() -> int:
    if len(sys.argv) != 3:
        print("Usage: validate_research.py lab.json comparison.json")
        return 2
    lab = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    comparison = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
    cases = lab.get("cases")
    if not isinstance(cases, list) or len(cases) != 11:
        raise ValueError("Expected 11 defined controlled cases, including skips")
    evaluated = [c for c in cases if c.get("status") != "skipped"]
    injected = [c for c in evaluated if c.get("expected")]
    negative = [c for c in evaluated if not c.get("expected")]
    for item in injected + negative:
        if not isinstance(item.get("passed"), bool):
            raise ValueError("Missing per-case evaluation")
    metrics = lab.get("metrics") or {}
    if metrics.get("controlled_cases") != len(evaluated):
        raise ValueError("Controlled case count mismatch")
    if metrics.get("failed_cases") != len(injected):
        raise ValueError("Injected case count mismatch")
    if metrics.get("skipped_cases") != len(cases) - len(evaluated):
        raise ValueError("Skipped case count mismatch")
    rows = comparison.get("cases", [])
    if len(rows) != len(cases):
        raise ValueError("Comparator must report every defined lab case")
    if comparison.get("study_type") != "paired_controlled_environment_checks":
        raise ValueError("Unexpected comparison study type")
    for row in rows:
        if row.get("status") == "skipped_in_lab":
            continue
        if row.get("tools", {}).get("pip_check", {}).get("status") != "completed":
            raise ValueError("pip check was unavailable for an evaluated case")
        if row.get("tools", {}).get("uv_pip_check", {}).get("status") != "completed":
            raise ValueError("uv pip check was unavailable for an evaluated case")
    print(json.dumps({
        "status": "validated",
        "injected_cases": len(injected),
        "injected_label_matches": sum(c["passed"] for c in injected),
        "negative_controls": len(negative),
        "negative_false_attributions": sum(bool(c["predicted"]) for c in negative),
        "comparator_observations": len(rows),
        "notice": "These are developer-injected labels, NOT independent field accuracy.",
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
