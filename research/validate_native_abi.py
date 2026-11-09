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


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    print(json.dumps(validate(data), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
