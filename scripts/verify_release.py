#!/usr/bin/env python3
"""Verify local EnvGuard CI wheel and sdist contain expected, publishable files.

Only stdlib. This is an archive-integrity/packaging gate, NOT a malware scan,
software provenance attestation or reproducible-build certification.
"""
from __future__ import annotations

import argparse
import email
import json
import re
import tarfile
import tomllib
import zipfile
from pathlib import Path, PurePosixPath

BAD_PARTS = {"__pycache__", ".venv", ".git", ".envguard-runs", "lab-results", "build", "dist"}
BAD_SUFFIXES = (".pyc", ".pyo", ".log", ".pem", ".key", ".env")


def _safe_path(path: str) -> bool:
    parts = PurePosixPath(path).parts
    if not path or path.startswith("/") or "\\" in path or ".." in parts:
        return False
    return not (BAD_PARTS.intersection(parts) or path.endswith(BAD_SUFFIXES))


def verify(root: Path, dist: Path) -> dict[str, object]:
    project = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))["project"]
    version = project["version"]
    distribution = project["name"]
    wheels = list(dist.glob("*.whl"))
    sdists = list(dist.glob("*.tar.gz"))
    if len(wheels) != 1 or len(sdists) != 1:
        raise ValueError("Expected exactly one wheel and one .tar.gz source distribution")
    wheel, sdist = wheels[0], sdists[0]
    if wheel.name != f"envguard_ci-{version}-py3-none-any.whl":
        raise ValueError(f"Unexpected wheel filename: {wheel.name}")
    if sdist.name != f"envguard_ci-{version}.tar.gz":
        raise ValueError(f"Unexpected source distribution filename: {sdist.name}")
    wheel_names_count = 0
    with zipfile.ZipFile(wheel) as z:
        names = z.namelist()
        wheel_names_count = len(names)
        if any(not _safe_path(n) for n in names):
            raise ValueError("Wheel contains generated or unsafe path")
        for required in (f"envguard_ci/__init__.py", "envguard_ci/cli.py",
                         f"envguard_ci-{version}.dist-info/METADATA",
                         f"envguard_ci-{version}.dist-info/entry_points.txt"):
            if required not in names:
                raise ValueError(f"Missing wheel member {required}")
        metadata = email.message_from_bytes(z.read(f"envguard_ci-{version}.dist-info/METADATA"))
        entry = z.read(f"envguard_ci-{version}.dist-info/entry_points.txt").decode()
        if metadata.get("Name") != distribution or metadata.get("Version") != version:
            raise ValueError("Wheel package metadata does not match pyproject.toml")
        if "envguard-ci = envguard_ci.cli:main" not in entry:
            raise ValueError("Wheel does not expose the expected console script")
        if not (metadata.get("Requires-Python") or "").startswith(">=3.11"):
            raise ValueError("Wheel does not advertise the supported Python range")
        if any(x.endswith((".so", ".pyd", ".dll")) for x in names):
            raise ValueError("Pure-Python wheel unexpectedly contains native binaries")
    with tarfile.open(sdist, "r:gz") as archive:
        members = archive.getmembers()
        names = [m.name for m in members]
        prefix = f"envguard_ci-{version}/"
        if any(not n.startswith(prefix) for n in names if n != prefix[:-1]):
            raise ValueError("Unexpected source distribution directory prefix")
        for m in members:
            if not _safe_path(m.name) or (not m.isfile() and not m.isdir()):
                raise ValueError(f"Unexpected file type or generated path: {m.name}")
        required = {"README.md", "LICENSE", "SECURITY.md", "CONTRIBUTING.md",
                    "pyproject.toml", "src/envguard_ci/cli.py",
                    "src/envguard_ci/comparability.py", "tests/test_release_reliability.py",
                    ".github/workflows/ci.yml", ".gitlab-ci.yml", "lab/run_lab.py"}
        # setuptools' sdist includes explicit MANIFEST.in additions.
        missing = [name for name in sorted(required) if prefix + name not in names]
        if missing:
            raise ValueError("Source distribution missing: " + ", ".join(missing))
    return {"status": "pass", "distribution": distribution, "version": version,
            "wheel": wheel.name, "sdist": sdist.name,
            "wheel_members": wheel_names_count, "checks": ["metadata", "console-script", "source-files", "archive-hygiene"]}


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--dist", type=Path, default=Path("dist"))
    args = parser.parse_args()
    result = verify(args.root.resolve(), args.dist.resolve())
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
