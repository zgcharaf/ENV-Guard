#!/usr/bin/env python3
"""Static native ABI investigation on two public CasADi AArch64 wheels.

No third-party package is imported, installed or executed. Pip *downloads*
wheels only. A disposable CI runner uses readelf -V on a selected ELF object.
The versions and suspected defect were known beforehand: not blind evaluation.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
from urllib.request import Request, urlopen
import zipfile

from typing import Any

BASE = "https://pypi.org/pypi/casadi/{version}/json"
PLATFORM = "manylinux_2_28_aarch64"
ARCH = "aarch64"
WHEEL_TEMPLATE = "casadi-{version}-cp310-none-manylinux_2_28_aarch64.whl"
VERSIONS = ("3.8.0", "3.8.2")
USER_AGENT = "EnvGuard-CI-native-abi-study/1.0"
LIMIT_ARCHIVE = 120_000_000
LIMIT_ELF = 300_000_000


def request_release_metadata(version: str) -> dict[str, Any]:
    if version not in VERSIONS:
        raise ValueError("This experiment only supports its preregistered versions")
    req = Request(BASE.format(version=version), headers={"User-Agent": USER_AGENT})
    with urlopen(req, timeout=25) as response:
        payload = response.read(2_000_001)
    if len(payload) > 2_000_000:
        raise ValueError("Unexpectedly large PyPI metadata response")
    meta = json.loads(payload.decode("utf-8"))
    name = WHEEL_TEMPLATE.format(version=version)
    items = [f for f in meta.get("urls", []) if f.get("filename") == name]
    if len(items) != 1:
        raise ValueError("Exact published AArch64 wheel not found")
    item = items[0]
    if item.get("packagetype") != "bdist_wheel":
        raise ValueError("Expected a published binary wheel")
    expected_sha256 = item.get("digests", {}).get("sha256")
    if not isinstance(expected_sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", expected_sha256):
        raise ValueError("PyPI must provide SHA-256 for the exact wheel")
    size = item.get("size")
    if type(size) is not int or not 0 < size <= LIMIT_ARCHIVE:
        raise ValueError("Wheel size exceeds experiment limit")
    return {"name": name, "size": size, "sha256": expected_sha256}


def download_wheel(version: str, directory: Path, meta: dict[str, Any]) -> Path:
    cmd = [
        sys.executable, "-m", "pip", "--isolated", "download",
        "--only-binary=:all:", "--no-deps", "--no-input",
        "--disable-pip-version-check", "--index-url", "https://pypi.org/simple",
        "--platform", PLATFORM, "--implementation", "cp",
        "--python-version", "310", "--abi", "none",
        "--dest", str(directory), f"casadi=={version}",
    ]
    env = dict(os.environ)
    for key in ("PIP_INDEX_URL", "PIP_EXTRA_INDEX_URL", "PYTHONPATH", "PYTHONHOME"):
        env.pop(key, None)
    result = subprocess.run(cmd, text=True, stdout=subprocess.PIPE,
                            stderr=subprocess.STDOUT, cwd=directory,
                            env=env, timeout=180, check=False)
    if result.returncode:
        raise RuntimeError(f"Wheel-only download failed for {version} (exit {result.returncode}); raw pip output intentionally withheld")
    files = list(directory.glob("*.whl"))
    if len(files) != 1 or files[0].name != meta["name"]:
        raise RuntimeError("Downloaded wheel does not match expected filename")
    wheel = files[0]
    if wheel.stat().st_size != meta["size"]:
        raise ValueError("Wheel byte size differs from PyPI metadata")
    h = hashlib.sha256()
    with wheel.open("rb") as stream:
        for chunk in iter(lambda: stream.read(2 ** 20), b""):
            h.update(chunk)
    if h.hexdigest() != meta["sha256"]:
        raise ValueError("Wheel SHA-256 differs from official PyPI metadata")
    return wheel


def versions_in_readelf(stdout: str) -> list[tuple[int, int, int]]:
    """readelf -V 'Name: GLIBCXX_x.y.z' entries represent required versions."""
    return sorted({
        tuple(int(p) for p in match.split("."))
        for match in re.findall(r"\bName:\s*GLIBCXX_(\d+\.\d+\.\d+)\b", stdout)
    })


def inspect_elf(wheel: Path, directory: Path) -> dict[str, Any]:
    with zipfile.ZipFile(wheel) as archive:
        matches = [e for e in archive.infolist() if
                   e.filename.endswith("/_casadi.so") and not e.is_dir()]
        if len(matches) != 1:
            raise ValueError("Wheel must contain exactly one casadi/_casadi.so extension")
        member = matches[0]
        if member.file_size > LIMIT_ELF or member.file_size < 1_000:
            raise ValueError("ELF size outside permitted bounds")
        extracted = directory / "_casadi.so"
        with archive.open(member) as r, extracted.open("wb") as w:
            size = 0
            while data := r.read(2 ** 20):
                size += len(data)
                if size > LIMIT_ELF:
                    raise ValueError("Native payload too large")
                w.write(data)
    # readelf parses bytes; this does NOT load or execute the foreign ARM64 object.
    if extracted.read_bytes()[:4] != b"\x7fELF":
        raise ValueError("Selected wheel member is not ELF")
    result = subprocess.run(["readelf", "--version-info", str(extracted)],
                            text=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            timeout=35, check=False)
    if result.returncode:
        raise RuntimeError("Static readelf version inspection failed")
    versions = versions_in_readelf(result.stdout)
    if not versions:
        raise ValueError("No required GLIBCXX versions found; cannot draw conclusion")
    max_v = versions[-1]
    return {
        "elf_member": member.filename,
        "elf_bytes": member.file_size,
        "max_required_glibcxx": "GLIBCXX_" + ".".join(map(str, max_v)),
        "all_required_glibcxx_versions": ["GLIBCXX_" + ".".join(map(str, x)) for x in versions],
        "elf_loaded_or_executed": False,
    }


def run(output: Path) -> dict[str, Any]:
    observations: list[dict[str, Any]] = []
    for version in VERSIONS:
        with tempfile.TemporaryDirectory(prefix="envguard-abi-public-") as td:
            root = Path(td)
            m = request_release_metadata(version)
            wheel = download_wheel(version, root, m)
            abi = inspect_elf(wheel, root)
            observations.append({
                "version": version,
                "filename": m["name"],
                "wheel_sha256": m["sha256"],
                "wheel_bytes": m["size"],
                **abi,
            })
    broken, fixed = observations
    def number(s: str) -> tuple[int, int, int]:
        return tuple(int(x) for x in s.removeprefix("GLIBCXX_").split("."))
    old = number(broken["max_required_glibcxx"])
    new = number(fixed["max_required_glibcxx"])
    result = {
        "schema_version": "1.0",
        "experiment": "public_aarch64_wheel_static_symbol_audit",
        "status": "abi_requirement_reduced" if old > new else "not_confirmed",
        "study_role": "known_issue_static_development_exemplar",
        "independent_blind_test": False,
        "holdout_eligible": False,
        "source_issue": "https://github.com/casadi/casadi/issues/4402",
        "source_release": "https://pypi.org/project/casadi/3.8.0/",
        "source_repaired_release": "https://pypi.org/project/casadi/3.8.2/",
        "platform_tag": PLATFORM,
        "observations": observations,
        "limits": [
            "Only casadi/_casadi.so is examined, not all native wheel members.",
            "Version needs come from readelf on archive bytes; wheel code is never loaded or executed.",
            "No deployment runtime / C++ runtime provider is actually inspected.",
            "A reduction of a required GLIBCXX version is not an end-to-end runtime compatibility proof.",
            "A public known issue and publicly disclosed fixes were available before this experiment.",
            "Wheel hash is checked against PyPI JSON response; no signature or provenance attestation.",
            "This is a developmental, nonblind case; not eligible for independent field accuracy."
        ]
    }
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(result, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--out", type=Path, default=Path("research-results/native-abi.json"))
    args = p.parse_args()
    data = run(args.out)
    print(json.dumps({"status": data["status"], "observations": [
        {"version": x["version"], "max_required_glibcxx": x["max_required_glibcxx"],
         "wheel_sha256": x["wheel_sha256"]} for x in data["observations"]
    ], "file": str(args.out)}, indent=2))
    return int(data["status"] != "abi_requirement_reduced")


if __name__ == "__main__":
    raise SystemExit(main())
