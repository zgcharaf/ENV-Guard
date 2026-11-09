#!/usr/bin/env python3
"""Validate public ARM64 wheel static study, not a runtime compatibility claim."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import re

SHA = re.compile(r"[0-9a-f]{64}")
REQ = re.compile(r"GLIBCXX_(\d+)\.(\d+)\.(\d+)")


def validate(data: dict[str, object]) -> dict[str, object]:
    if data.get("schema_version") != "1.0":
        raise ValueError("Invalid data format")
    if data.get("experiment") != "public_aarch64_wheel_static_symbol_audit":
        raise ValueError("Unexpected experiment")
    if data.get("study_role") != "known_issue_static_development_exemplar":
        raise ValueError("Must remain a disclosed known-issue example")
    if data.get("independent_blind_test") is not False or data.get("holdout_eligible") is not False:
        raise ValueError("No inferred independent accuracy allowed")
    if data.get("platform_tag") != "manylinux_2_28_aarch64":
        raise ValueError("Unexpected platform")
    observations = data.get("observations")
    if not isinstance(observations, list) or len(observations) != 2:
        raise ValueError("Expected exactly broken and later-release wheel")
    old, new = observations
    if [old.get("version"), new.get("version")] != ["3.8.0", "3.8.2"]:
        raise ValueError("Versions do not match registered experiment")
    for obs in observations:
        if obs.get("filename") != (
            f"casadi-{obs['version']}-cp310-none-manylinux_2_28_aarch64.whl"
        ):
            raise ValueError("Wrong wheel")
        if not isinstance(obs.get("wheel_sha256"), str) or not SHA.fullmatch(obs["wheel_sha256"]):
            raise ValueError("No SHA256 identity")
        if obs.get("elf_loaded_or_executed") is not False:
            raise ValueError("Wheel code must not be executed")
        if not str(obs.get("elf_member", "")).endswith("/_casadi.so"):
            raise ValueError("Wrong inspected member")
        if not REQ.fullmatch(str(obs.get("max_required_glibcxx"))):
            raise ValueError("Missing required GLIBCXX record")
    def as_parts(item: dict[str, object]) -> tuple[int, ...]:
        match = REQ.fullmatch(str(item["max_required_glibcxx"]))
        assert match is not None
        return tuple(map(int, match.groups()))
    if as_parts(old) <= as_parts(new) or data.get("status") != "abi_requirement_reduced":
        raise ValueError("No observed reduction in required symbol version")
    return {
        "status": "validated_static_symbol_reduction",
        "source_versions": [old["version"], new["version"]],
        "observed_max_requirements": [
            old["max_required_glibcxx"], new["max_required_glibcxx"]
        ],
        "blind_accuracy_eligible": False,
        "actual_import_tested": False,
        "actual_target_runtime_tested": False,
    }



def validate_published_ledger() -> dict[str, object]:
    """Protect the public-known-fix classification of ABI-0001."""
    file = Path(__file__).resolve().parent / "public-exemplars" / "ABI-0001-observed-2026-11-09.json"
    record = json.loads(file.read_text(encoding="utf-8"))
    if record.get("case_id") != "ABI-0001":
        raise ValueError("Wrong case ID in permanent native ABI evidence")
    if record.get("study_role") != "known_issue_static_development_exemplar":
        raise ValueError("Disclosed ABI study must remain an example")
    if record.get("holdout_eligible") is not False or record.get("independent_blind_test") is not False:
        raise ValueError("Disclosed study must be ineligible for blind benchmark")
    expected = [("3.8.0", "GLIBCXX_3.4.32"), ("3.8.2", "GLIBCXX_3.4.21")]
    rows = (record.get("evidence") or {}).get("results")
    if not isinstance(rows, list) or [(r.get("version"), r.get("max_required_glibcxx")) for r in rows] != expected:
        raise ValueError("Permanent static results differ from hosted evidence")
    for r in rows:
        if not SHA.fullmatch(str(r.get("sha256"))):
            raise ValueError("No immutable wheel identity")
    return {"case_id": "ABI-0001", "holdout_eligible": False, "permanent_evidence_valid": True}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    outcome = validate(data)
    outcome["published_case_ledger"] = validate_published_ledger()
    print(json.dumps(outcome, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
