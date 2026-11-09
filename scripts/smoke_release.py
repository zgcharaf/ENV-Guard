#!/usr/bin/env python3
"""Install the built wheel into a temporary environment outside the checkout.

By default the temporary venv has isolated site-packages, and pip may fetch
runtime dependencies. --offline inherits already-installed site-packages and
uses --no-deps; only appropriate for local artifact smoke verification.
"""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import venv


def run(command: list[str], cwd: Path, env: dict[str, str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, cwd=cwd, env=env, text=True, stdout=subprocess.PIPE,
                          stderr=subprocess.STDOUT, timeout=90)


def smoke(dist: Path, version: str, offline: bool) -> dict[str, object]:
    wheels = list(dist.resolve().glob("envguard_ci-*.whl"))
    if len(wheels) != 1:
        raise ValueError("Expected exactly one envguard-ci wheel")
    with tempfile.TemporaryDirectory(prefix="envguard-public-smoke-") as tmp:
        root = Path(tmp)
        venv.create(root / "venv", with_pip=True, system_site_packages=offline)
        python = root / "venv" / ("Scripts/python.exe" if os.name == "nt" else "bin/python")
        env = {k: v for k, v in os.environ.items() if k not in {"PYTHONPATH", "PYTHONHOME"}}
        extra = ["--no-deps", "--no-index"] if offline else []
        installed = run([str(python), "-m", "pip", "install", *extra, str(wheels[0])], root, env)
        if installed.returncode:
            raise RuntimeError("Install from wheel failed:\n" + installed.stdout[-1500:])
        checks = [
            ([str(python), "-m", "envguard_ci", "--version"], 0, version),
            ([str(python), "-c", "from envguard_ci.comparability import assess_targets; print('IMPORT_OK')"], 0, "IMPORT_OK"),
        ]
        for cmd, expected_code, expected_text in checks:
            result = run(cmd, root, env)
            if result.returncode != expected_code or expected_text not in result.stdout:
                raise AssertionError("Wheel smoke failed: " + repr(cmd) + "\n" + result.stdout[-1500:])
        snapshot = root / "current.json"
        report = root / "report.json"
        missing = run([str(python), "-m", "envguard_ci", "ci-run", "--project", str(root),
                       "--python", str(python), "--snapshot-out", str(snapshot),
                       "--report-out", str(report), "--", str(python), "-m",
                       "__envguard_missing_demo__"], root, env)
        if missing.returncode != 1 or not snapshot.is_file() or not report.is_file():
            raise AssertionError("Failed command not faithfully preserved: " + missing.stdout[-2000:])
        data = json.loads(report.read_text())
        if data["failure_analysis"]["root_cause_hypothesis"]["code"] != "PYTHON_IMPORT_FAILURE":
            raise AssertionError("Wrong diagnosis in isolated wheel smoke")
        dossier = report.with_suffix(".md")
        if not dossier.is_file() or "unresolved" not in dossier.read_text():
            raise AssertionError("Evidence dossier missing/incorrect")
        return {"status": "pass", "version": version, "offline_inherit_site_packages": offline,
                "checks": ["wheel-install", "import-outside-checkout", "module-cli", "failed-command-status", "incident-dossier"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    parser.add_argument("--version", default="1.0.0rc1")
    parser.add_argument("--offline", action="store_true")
    args = parser.parse_args()
    print(json.dumps(smoke(args.dist, args.version, args.offline), indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
