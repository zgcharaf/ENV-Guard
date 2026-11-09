#!/usr/bin/env python3
"""Validate the public EnvGuard CI incident discovery register.

This is a metadata consistency check, NOT incident adjudication. It never
downloads URLs, runs incident code, imports remote modules, or creates labels.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re
from typing import Any

ID = re.compile(r"^CI-[0-9]{4}$")
ISSUE = re.compile(r"^https://github\.com/([A-Za-z0-9_.-]+)/([A-Za-z0-9_.-]+)/issues/([1-9][0-9]*)$")
ALLOWED_SCOPE = {"likely_ci", "needs_scope_review"}
ALLOWED_SOURCE = {
    "search_result_only",
    "issue_inspected",
    "issue_and_comments_inspected",
    "issue_comments_and_merged_pr_inspected",
}
RECORD_FIELDS = {
    "id", "source_url", "repo", "issue_number", "title",
    "observed_theme", "ci_scope_screen", "source_review",
    "evidence_summary", "adjudication_status",
}
FORBIDDEN_FIELDS = {
    "gold_label", "ground_truth", "root_cause_label", "fix_commit",
    "fix_pr_url", "independent_accuracy", "envguard_prediction",
}
REQUIRED_TOP = {
    "schema_version", "corpus_type", "discovered_on",
    "evaluated_incidents", "independent_adjudicated_labels",
    "publication_policy", "candidates",
}


def validate(data: Any) -> dict[str, object]:
    if not isinstance(data, dict) or not REQUIRED_TOP <= data.keys():
        raise ValueError("Missing discovery register metadata")
    if data["schema_version"] != "1.0" or data["corpus_type"] != "PUBLIC_ISSUE_DISCOVERY_QUEUE":
        raise ValueError("Unexpected discovery register type/version")
    if data["evaluated_incidents"] != 0 or data["independent_adjudicated_labels"] != 0:
        raise ValueError("Candidate discovery must not claim independently evaluated incidents")
    if not isinstance(data["candidates"], list) or not data["candidates"]:
        raise ValueError("Nonempty candidate list required")
    seen_ids: set[str] = set()
    seen_urls: set[str] = set()
    reviews = 0
    likely_ci = 0
    for i, row in enumerate(data["candidates"], 1):
        if not isinstance(row, dict):
            raise ValueError(f"Candidate {i} must be an object")
        keys = set(row)
        if keys != RECORD_FIELDS or (keys & FORBIDDEN_FIELDS):
            raise ValueError(f"Candidate {i} has invalid, missing or prohibited fields")
        cid = row["id"]
        url = row["source_url"]
        match = ISSUE.fullmatch(url) if isinstance(url, str) else None
        if not isinstance(cid, str) or not ID.fullmatch(cid) or not match:
            raise ValueError(f"Candidate {i} has invalid identifier or GitHub issue URL")
        if cid in seen_ids or url.lower() in seen_urls:
            raise ValueError(f"Duplicate issue or ID: {cid}")
        seen_ids.add(cid)
        seen_urls.add(url.lower())
        if row["repo"] != f"{match.group(1)}/{match.group(2)}":
            raise ValueError(f"Repository and issue link disagree: {cid}")
        if type(row["issue_number"]) is not int or row["issue_number"] != int(match.group(3)):
            raise ValueError(f"Issue number does not match URL: {cid}")
        if row["ci_scope_screen"] not in ALLOWED_SCOPE:
            raise ValueError(f"Invalid CI screening status: {cid}")
        if row["source_review"] not in ALLOWED_SOURCE:
            raise ValueError(f"Invalid source review status: {cid}")
        if row["adjudication_status"] != "not_adjudicated":
            raise ValueError(f"Public candidate entries must not contain review labels: {cid}")
        for k in ("title", "observed_theme", "evidence_summary"):
            v = row[k]
            if not isinstance(v, str) or not 8 <= len(v) <= 500:
                raise ValueError(f"Malformed text field {k}: {cid}")
        if row["ci_scope_screen"] == "likely_ci":
            likely_ci += 1
        if row["source_review"] != "search_result_only":
            reviews += 1
    return {
        "status": "valid_discovery_queue",
        "candidates": len(data["candidates"]),
        "likely_ci_leads": likely_ci,
        "source_issues_inspected": reviews,
        "ground_truth_labels": 0,
        "independently_evaluated": 0,
        "notice": "Discovery links only; no root-cause accuracy can be derived.",
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input", type=Path,
        default=Path(__file__).resolve().parent / "candidates.json",
    )
    args = parser.parse_args()
    result = validate(json.loads(args.input.read_text(encoding="utf-8")))
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
