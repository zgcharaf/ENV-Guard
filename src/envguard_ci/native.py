"""Read-only ELF inspection. No `ldd` and no executing inspected binaries."""

from __future__ import annotations

import re
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

_NEEDED = re.compile(r"\(NEEDED\).*?\[([^\]]+)\]")
_SYM = re.compile(r"\b(?:GLIBCXX|GLIBC|CXXABI)_[0-9][0-9.]*\b")
_LDCONFIG = re.compile(r"^\s*(\S+)\s+\(.+?\)\s+=>\s+(\S+)")


def _run(*args: str, timeout: float = 3) -> str:
    try:
        proc = subprocess.run(args, capture_output=True, text=True, timeout=timeout,
                              check=False, encoding="utf-8", errors="replace")
        return proc.stdout if proc.returncode == 0 else ""
    except (OSError, subprocess.TimeoutExpired):
        return ""


def _readelf_versions(path: str, section: str) -> list[str]:
    text = _run("readelf", "--version-info", "--wide", path)
    if not text:
        return []
    # A version in the needs section means *required*. A version in the
    # definitions section means *provided*. Do not confuse the two.
    section_name = "Version needs section" if section == "needs" else "Version definition section"
    in_section = False
    found: set[str] = set()
    for line in text.splitlines():
        if "Version needs section" in line or "Version definition section" in line or "Version symbols section" in line:
            in_section = section_name in line
        elif in_section and "Name:" in line:
            found.update(_SYM.findall(line))
    return sorted(found)


def inspect_native(paths: list[dict[str, str]], max_extensions: int = 160) -> dict[str, Any]:
    if sys.platform != "linux":
        return {"scan_status": "unsupported", "libraries": [], "requirements": [],
                "provided_symbols": {}, "notes": ["ELF native scanning supported on Linux only"]}
    if not shutil.which("readelf") or not shutil.which("ldconfig"):
        return {"scan_status": "unsupported", "libraries": [], "requirements": [],
                "provided_symbols": {}, "notes": ["readelf or ldconfig unavailable"]}
    libpaths: dict[str, str] = {}
    for line in _run("ldconfig", "-p").splitlines():
        match = _LDCONFIG.match(line)
        if match:
            libpaths.setdefault(match.group(1), match.group(2))
    requirements: list[dict[str, Any]] = []
    truncated = len(paths) > max_extensions
    for item in paths[:max_extensions]:
        file = Path(item["path"])
        if not file.is_file() or file.suffix != ".so":
            # e.g. extension.cpython-313-x86_64-linux-gnu.so is still .so
            continue
        dynamic = _run("readelf", "-d", "--wide", str(file))
        if not dynamic:
            continue
        needs = sorted(set(_NEEDED.findall(dynamic)))
        symbols = _readelf_versions(str(file), "needs")
        requirements.append({"extension": item["name"], "package": item["package"],
                             "needed": needs, "symbol_versions": symbols})
    # Checking a provider's exported/defined versions is costly. Inspect only
    # providers actually referenced by scanned extensions.
    needed_names = {lib for req in requirements for lib in req["needed"]}
    provided: dict[str, list[str]] = {}
    for name in sorted(needed_names):
        path = libpaths.get(name)
        if path:
            provided[name] = _readelf_versions(path, "provides")
    return {"scan_status": "partial" if truncated else "complete",
            "libraries": sorted(libpaths),
            "requirements": requirements, "provided_symbols": provided,
            "notes": [f"Only first {max_extensions} native extensions inspected"] if truncated else []}
