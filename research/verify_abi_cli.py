#!/usr/bin/env python3
"""Hosted smoke test for EnvGuard's NEW inspect-wheel-abi CLI.

Independently known CasADi issue, not a blind accuracy benchmark.
Wheels are SHA-256 verified against official PyPI JSON and never installed or imported.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys
import tempfile

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.replay_native_abi import request_release_metadata, download_wheel


EXPECTED = {"3.8.0": "GLIBCXX_3.4.32", "3.8.2": "GLIBCXX_3.4.21"}
MEMBER = "casadi/_casadi.so"


def run(dest: Path) -> dict[str, object]:
    records = []
    for version, expected in EXPECTED.items():
        with tempfile.TemporaryDirectory(prefix="envguard-abi-cli-") as td:
            root = Path(td)
            meta = request_release_metadata(version)
            wheel = download_wheel(version, root, meta)
            output = root / "wheel-static.json"
            cmd = [sys.executable, "-m", "envguard_ci", "inspect-wheel-abi",
                   "--wheel", str(wheel), "--approved-sha256", meta["sha256"],
                   "--member", MEMBER, "--out", str(output)]
            proc = subprocess.run(cmd, cwd=Path(__file__).resolve().parents[1],
                                  capture_output=True, text=True, encoding="utf-8",
                                  errors="replace", timeout=120, check=False)
            if proc.returncode or not output.is_file():
                raise RuntimeError(f"EnvGuard CLI rejected known wheel {version}; code={proc.returncode}")
            report = json.loads(output.read_text(encoding="utf-8"))
            if report.get("status") != "static_elf_scanned":
                raise ValueError("Wheel static ELF inspection incomplete")
            objects = report.get("objects", [])
            if len(objects) != 1 or objects[0]["member"] != MEMBER:
                raise ValueError("Unexpected scanned ELF member")
            versions = objects[0]["required_versions_by_provider"].get("libstdc++.so.6", [])
            glibcxx = [x for x in versions if x.startswith("GLIBCXX_")]
            if not glibcxx:
                raise ValueError("No GLIBCXX requirements captured by CLI")
            max_requirement = max(glibcxx, key=lambda s: tuple(map(int, s.removeprefix("GLIBCXX_").split("."))))
            if max_requirement != expected:
                raise ValueError(f"Unexpected {version} max GLIBCXX version ({max_requirement})")
            if objects[0].get("executed_or_loaded") is not False:
                raise ValueError("CLI must not execute native library")
            records.append({
                "version": version, "wheel_name": meta["name"],
                "wheel_sha256": meta["sha256"],
                "member": MEMBER,
                "member_sha256": objects[0]["sha256"],
                "max_required_glibcxx": max_requirement,
                "target_manifest_used": False,
            })
    record = {
        "schema_version": "1.0",
        "study": "known_public_CasADi_wheel_static_CLI_regression",
        "status": "observed_known_issue_symbol_versions",
        "independent_blind_test": False,
        "holdout_eligible": False,
        "actual_import_tested": False,
        "source_issue": "https://github.com/casadi/casadi/issues/4402",
        "observations": records,
        "limitations": [
            "This is an independently sourced known issue, not blinded attribution.",
            "Only one ELF member per wheel inspected; wheel code is never executed.",
            "No target-runtime symbols were provided; no actual load failure was reproduced.",
        ],
    }
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_text(json.dumps(record, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return record


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=Path("research-results/abi-cli.json"))
    args = p.parse_args()
    summary = run(args.out)
    print(json.dumps({
        "status": summary["status"],
        "observations": [{k:v for k,v in x.items() if k in ("version","max_required_glibcxx","wheel_sha256")}
                         for x in summary["observations"]],
        "study": summary["study"],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
