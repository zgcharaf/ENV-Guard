"""Bounded, static ELF ABI evidence for Python wheels (experimental).

Never installs, imports, dlopens or invokes a wheel binary. GNU readelf parses
ELF bytes, so use an unprivileged/disposable inspection runner for untrusted
artifacts: readelf is NOT a security sandbox.

The target provider manifest is collected explicitly from the selected system
ldconfig cache; it may differ from the loader search path of a specific process.
We therefore report *candidate* provider shortfalls, not production proof.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
import platform
import re
import shutil
import subprocess
import sys
import tempfile
from typing import Any
import zipfile

from .artifacts import inspect_wheel, MAX_FILES, MAX_UNCOMPRESSED

MAX_ELF_MEMBER = 155_000_000
MAX_EXTRACTED = 250_000_000
MAX_ELF_COUNT = 32
MAX_TARGET_MANIFEST = 2_000_000
VERSION_PATTERN = re.compile(r"^(GLIBC|GLIBCXX|CXXABI)_[0-9]+(?:\.[0-9]+){1,3}$")
NEEDED_PATTERN = re.compile(r"\(NEEDED\)\s+Shared library:\s+\[([^\]]+)\]")
PROVIDER_PATTERN = re.compile(r"\bFile:\s+(\S+)")
NAME_PATTERN = re.compile(r"\bName:\s+((?:GLIBC|GLIBCXX|CXXABI)_[0-9]+(?:\.[0-9]+){1,3})\b")
LDCONFIG_PATTERN = re.compile(r"^\s*(\S+)\s+\([^)]+\)\s+=>\s+(\S+)")
HOST_ARCH = {"amd64": "x86_64", "x86_64": "x86_64", "aarch64": "aarch64",
             "arm64": "aarch64", "armv7l": "arm", "i386": "x86", "i686": "x86"}
MACHINE_ARCH = {"AArch64": "aarch64", "Advanced Micro Devices X86-64": "x86_64",
                "Intel 80386": "x86", "ARM": "arm"}


class WheelABIError(ValueError):
    pass


def _normalized_host_arch() -> str:
    value = platform.machine().lower()
    return HOST_ARCH.get(value, value)


def _tool(tool: str = "readelf") -> str:
    path = shutil.which(tool)
    if not path:
        raise WheelABIError(f"{tool} executable not available; install binutils on an isolated inspection runner")
    return path


def _run_tool(command: list[str], timeout: int = 25) -> str:
    try:
        result = subprocess.run(command, capture_output=True, timeout=timeout,
                                check=False, text=True, encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise WheelABIError(f"Static ELF inspection tool failed: {type(exc).__name__}") from None
    if result.returncode != 0:
        raise WheelABIError(f"Static ELF inspection tool returned exit code {result.returncode}")
    if len(result.stdout) > 6_000_000:
        raise WheelABIError("readelf textual output exceeds 6 MB bound")
    return result.stdout


def _elf_arch(header: str) -> str | None:
    for line in header.splitlines():
        if "Machine:" in line:
            name = line.split("Machine:", 1)[1].strip()
            return MACHINE_ARCH.get(name)
    return None


def _version_needs(output: str) -> dict[str, list[str]]:
    """Version requirements, grouped by exact DT_NEEDED provider soname."""
    active = False
    provider: str | None = None
    found: dict[str, set[str]] = {}
    for line in output.splitlines():
        if "Version needs section" in line:
            active = True
            provider = None
            continue
        if "Version definition section" in line or "Version symbols section" in line:
            active = False
            provider = None
        if not active:
            continue
        file_match = PROVIDER_PATTERN.search(line)
        if file_match:
            provider = file_match.group(1)
        name_match = NAME_PATTERN.search(line)
        if provider and name_match:
            found.setdefault(provider, set()).add(name_match.group(1))
    return {name: sorted(labels) for name, labels in sorted(found.items())}


def _version_definitions(output: str) -> list[str]:
    """Only version definitions are exports; NEVER parse a needs section as exports."""
    active = False
    found: set[str] = set()
    for line in output.splitlines():
        if "Version definition section" in line:
            active = True
            continue
        if "Version needs section" in line or "Version symbols section" in line:
            active = False
        if active:
            match = NAME_PATTERN.search(line)
            if match:
                found.add(match.group(1))
    return sorted(found)


def _native_members(wheel: Path, member_name: str | None = None) -> tuple[list[zipfile.ZipInfo], list[str]]:
    with zipfile.ZipFile(wheel) as archive:
        members = archive.infolist()
    if len(members) > MAX_FILES or sum(x.file_size for x in members) > MAX_UNCOMPRESSED:
        raise WheelABIError("Wheel exceeds archive limits")
    selected: list[zipfile.ZipInfo] = []
    unsupported: list[str] = []
    total = 0
    for member in members:
        name = member.filename
        if name.startswith("/") or "\\" in name or any(p in ("", ".", "..") for p in name.split("/")):
            raise WheelABIError("Unsafe ZIP member path")
        if member.is_dir() or (member_name is not None and name != member_name):
            continue
        if re.search(r"\.so(?:\.\d+)*$", name):
            if member.file_size > MAX_ELF_MEMBER:
                raise WheelABIError("An ELF member exceeds 155 MB")
            total += member.file_size
            if total > MAX_EXTRACTED:
                raise WheelABIError("Total ELF extraction exceeds 250 MB")
            selected.append(member)
        elif name.lower().endswith((".pyd", ".dll", ".dylib")):
            unsupported.append(name)
    if member_name is not None and len(selected) != 1:
        raise WheelABIError("The selected ELF member was not found or is not a .so file")
    if len(selected) > MAX_ELF_COUNT:
        raise WheelABIError("More than 32 ELF members; specify --member for a narrower scan")
    return selected, unsupported[:100]


def _analyze_member(archive: zipfile.ZipFile, member: zipfile.ZipInfo, directory: Path, index: int) -> dict[str, Any]:
    local = directory / f"object-{index:03d}.so"
    digest = hashlib.sha256()
    length = 0
    with archive.open(member, "r") as source, local.open("wb") as target:
        while block := source.read(1024 * 1024):
            length += len(block)
            if length > MAX_ELF_MEMBER or length > member.file_size:
                raise WheelABIError("Extracted ELF exceeded declared size or safety bound")
            digest.update(block)
            target.write(block)
    if length != member.file_size:
        raise WheelABIError("ELF extracted byte count mismatch")
    with local.open("rb") as source:
        magic = source.read(4)
    if magic != b"\x7fELF":
        raise WheelABIError(f"Native .so ZIP member is not an ELF file ({member.filename})")
    readelf = _tool()
    header = _run_tool([readelf, "--file-header", str(local)])
    dynamic = _run_tool([readelf, "--dynamic", "--wide", str(local)])
    versions = _run_tool([readelf, "--version-info", "--wide", str(local)])
    needs = sorted(set(NEEDED_PATTERN.findall(dynamic)))
    result = {
        "member": member.filename,
        "sha256": digest.hexdigest(),
        "elf_architecture": _elf_arch(header),
        "elf_bytes": length,
        "needed_libraries": needs,
        "required_versions_by_provider": _version_needs(versions),
        "executed_or_loaded": False,
    }
    local.unlink()
    return result


def _read_target_manifest(path: str) -> dict[str, Any]:
    target_path = Path(path)
    if target_path.stat().st_size > MAX_TARGET_MANIFEST:
        raise WheelABIError("Target manifest exceeds 2 MB")
    try:
        source = json.loads(target_path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, ValueError) as exc:
        raise WheelABIError(f"Unreadable target manifest ({type(exc).__name__})") from None
    if not isinstance(source, dict) or source.get("kind") != "native_symbol_provider_manifest" or source.get("schema_version") != "1.0":
        raise WheelABIError("Expected EnvGuard native_symbol_provider_manifest v1.0")
    arch = source.get("architecture")
    providers = source.get("providers")
    if arch not in ("x86_64", "aarch64", "x86", "arm") or not isinstance(providers, dict) or len(providers) > 100:
        raise WheelABIError("Target manifest must supply a supported architecture and bounded providers")
    for name, info in providers.items():
        if not isinstance(name, str) or not re.fullmatch(r"[A-Za-z0-9_+.-]{1,100}", name):
            raise WheelABIError("Invalid provider soname in target manifest")
        if not isinstance(info, dict) or not isinstance(info.get("provided_versions"), list):
            raise WheelABIError("Missing provider version definitions")
        versions = info["provided_versions"]
        if (len(versions) > 3000 or any(not isinstance(x, str) or not VERSION_PATTERN.fullmatch(x) for x in versions)
                or len(set(versions)) != len(versions)):
            raise WheelABIError("Invalid exact symbol versions in target manifest")
        digest = info.get("sha256")
        if digest is not None and (not isinstance(digest, str) or not re.fullmatch("[a-f0-9]{64}", digest)):
            raise WheelABIError("Invalid provider file hash")
    return source


def _compare_abi(observations: list[dict[str, Any]], target: dict[str, Any] | None) -> dict[str, Any]:
    if target is None:
        return {"status": "target_not_provided", "shortfalls": [], "unknowns": [],
                "meaning": "Static requirements only; target exports not examined"}
    arch = target["architecture"]
    if not observations:
        return {"status": "no_elf_requirements_to_compare", "shortfalls": [], "unknowns": [],
                "meaning": "No ELF members were available to compare"}
    gaps: list[dict[str, Any]] = []
    unknown: list[dict[str, Any]] = []
    checked = 0
    for obj in observations:
        obj_arch = obj["elf_architecture"]
        if obj_arch is None or obj_arch != arch:
            unknown.append({"member": obj["member"], "reason": "ELF architecture differs from or is unknown for target"})
            continue
        for provider, needed in obj["required_versions_by_provider"].items():
            info = target["providers"].get(provider)
            if not info:
                unknown.append({"member": obj["member"], "provider": provider,
                                "reason": "Provider was not observed in target manifest"})
                continue
            checked += 1
            provided = set(info["provided_versions"])
            missing = sorted(set(needed) - provided)
            if missing:
                gaps.append({"member": obj["member"], "provider": provider,
                             "required_but_not_observed": missing})
    return {
        "status": "potential_provider_symbol_gap" if gaps else "no_observed_gap_with_unknowns" if unknown
                  else "no_observed_requirements" if checked == 0
                  else "no_observed_gap_for_checked_symbols",
        "checked_provider_requirements": checked,
        "shortfalls": gaps,
        "unknowns": unknown,
        "target_architecture": arch,
        "meaning": "Only exact symbol definitions reported in selected provider files were compared. "
                   "No runtime linker selection, dynamic imports, system policy or functional compatibility was verified.",
    }


def inspect_wheel_abi(wheel: str, *, approved_sha256: str | None = None,
                      target_manifest: str | None = None, member: str | None = None) -> dict[str, Any]:
    integrity = inspect_wheel(wheel, approved_sha256=approved_sha256, check_host_tags=False)
    if integrity["status"] != "verified_integrity":
        raise WheelABIError("Wheel hash or RECORD integrity verification failed; scan refused")
    path = Path(wheel)
    members, ignored = _native_members(path, member_name=member)
    if members:
        _tool()
    observations: list[dict[str, Any]] = []
    with tempfile.TemporaryDirectory(prefix="envguard-static-elf-") as temp:
        with zipfile.ZipFile(path) as archive:
            for index, member in enumerate(members):
                observations.append(_analyze_member(archive, member, Path(temp), index))
    target = _read_target_manifest(target_manifest) if target_manifest else None
    comparison = _compare_abi(observations, target)
    return {
        "schema_version": "1.0",
        "kind": "static_wheel_abi_evidence",
        "status": "no_elf_members" if not members else "partial_non_elf_native_members" if ignored else "static_elf_scanned",
        "wheel": {"name":path.name,"sha256":integrity["sha256"],
                  "record_sha256_verified": integrity["record_sha256_verified"],
                  "integrity":integrity["status"]},
        "target": {"provided": target is not None,
                   "source": (target.get("source") if target else None),
                   "architecture": (target.get("architecture") if target else None)},
        "objects": observations,
        "scan_scope": {"selected_member": member, "only_selected_member": member is not None,
                       "inspected_elf_count": len(observations)},
        "unsupported_non_elf_members": ignored,
        "comparison": comparison,
        "limitations": [
            "No wheel code was installed, imported, or executed; GNU readelf parses untrusted ELF bytes, not a secure sandbox.",
            "When --member is used, other native wheel members are excluded and cannot be considered compatible.",
            "DT_NEEDED and symbol version records do not reveal all dlopen/dynamic loading requirements.",
            "Runtime loader paths, library overrides, host policies and platform tag compliance are not certified.",
            "The target manifest is explicit static evidence, not proof of which providers a process would load.",
            "Exact version names (not highest version numbers) are compared; absent provider evidence stays unknown.",
            "Passing static checks is not a guarantee of successful import or application behavior.",
        ],
    }


def capture_native_target() -> dict[str, Any]:
    """Capture explicit local ldconfig candidate providers; never execute the libraries."""
    if sys.platform != "linux":
        raise WheelABIError("Target capture currently requires Linux with ldconfig and GNU readelf")
    readelf, ldconfig = _tool("readelf"), _tool("ldconfig")
    known = {"libstdc++.so.6", "libc.so.6", "libgcc_s.so.1"}
    registry: dict[str, list[str]] = {}
    for line in _run_tool([ldconfig, "-p"]).splitlines():
        m = LDCONFIG_PATTERN.match(line)
        if m and m.group(1) in known:
            registry.setdefault(m.group(1), []).append(m.group(2))
    providers: dict[str, Any] = {}
    arch = _normalized_host_arch()
    for name in sorted(known):
        for location in registry.get(name, []):
            candidate = Path(location)
            if not candidate.is_file():
                continue
            header = _run_tool([readelf, "--file-header", str(candidate)])
            if _elf_arch(header) != arch:
                continue
            definitions = _version_definitions(_run_tool([readelf, "--version-info", "--wide", str(candidate)]))
            if definitions:
                sha = hashlib.sha256()
                with candidate.open("rb") as source:
                    while block := source.read(1024 * 1024):
                        sha.update(block)
                providers[name] = {"sha256": sha.hexdigest(),
                                   "provided_versions": definitions,
                                   "source": "ldconfig_cache_candidate"}
            break
    return {
        "schema_version": "1.0", "kind": "native_symbol_provider_manifest",
        "architecture": arch, "source": "local_linux_ldconfig_and_readelf",
        "providers": providers,
        "limitations": [
            "These are ldconfig cache candidates; a specific process may load other libraries via rpath, runpath, LD_LIBRARY_PATH, or dlopen.",
            "Symbol definitions do not establish availability of every native symbol in all library objects.",
            "Capture does not import or execute provider libraries; readelf is a parser and should run with least privileges.",
            "No claim that a wheel will import or that source versions are safe or trusted.",
        ],
    }
