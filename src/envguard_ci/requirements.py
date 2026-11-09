"""Snapshot-aware PEP 508 / PEP 440 requirement evaluation.

Uses the well-tested PyPA `packaging` implementation. All environment marker
values come from the *inspected interpreter's* snapshot, never the CLI host.
Missing target metadata yields `unknown`, not a guessed boolean result.
"""
from __future__ import annotations

import re
from typing import Any, Iterable

from packaging.markers import Marker, InvalidMarker
from packaging.requirements import Requirement, InvalidRequirement
from packaging.specifiers import SpecifierSet, InvalidSpecifier
from packaging.version import InvalidVersion, Version

from .model import canonical_name, sanitize_requirement

_MARKER_KEYS = frozenset({
    "implementation_name", "implementation_version", "os_name", "platform_machine",
    "platform_python_implementation", "platform_release", "platform_system",
    "platform_version", "python_full_version", "python_version", "sys_platform", "extra",
})
_QUOTED = re.compile(r'''("[^"\\]*(?:\\.[^"\\]*)*"|'[^'\\]*(?:\\.[^'\\]*)*')''')
_NAMED_EXTRA = re.compile(r"\bextra\s*==\s*['\"]([\w.\-]+)['\"]|['\"]([\w.\-]+)['\"]\s*==\s*extra", re.I)
_UNSUPPORTED_EXTRA = re.compile(r"\bextra\s*(?:!=|<|>|in|not)|(?:!=|<|>)\s*extra\b", re.I)


def safe_requirement(raw: str) -> tuple[Requirement | None, str]:
    """Never echo credentials or attempt to parse a redacted direct URL."""
    text = sanitize_requirement(raw)
    if " @ [redacted-url]" in text:
        return None, text
    try:
        return Requirement(text), text
    except InvalidRequirement:
        return None, text


def target_marker_environment(snapshot: dict[str, Any]) -> dict[str, str]:
    """Use exact target values when present; conservative partial legacy fallback."""
    runtime = snapshot.get("runtime") or {}
    platform = snapshot.get("platform") or {}
    data = {key: value for key, value in (runtime.get("marker_environment") or {}).items()
            if key in _MARKER_KEYS and isinstance(value, str) and key != "extra"}
    version = runtime.get("version")
    if isinstance(version, str) and re.fullmatch(r"\d+\.\d+(?:\.\d+)?(?:[a-zA-Z0-9.]+)?", version):
        data.setdefault("python_full_version", version)
        data.setdefault("python_version", ".".join(version.split(".")[:2]))
    implementation = runtime.get("implementation")
    if isinstance(implementation, str):
        data.setdefault("platform_python_implementation", implementation)
        data.setdefault("implementation_name", implementation.lower())
    arch = platform.get("arch")
    if isinstance(arch, str):
        data.setdefault("platform_machine", arch)
    os_type = platform.get("os")
    if isinstance(os_type, str):
        if os_type in {"windows", "linux", "darwin"}:
            data.setdefault("sys_platform", "win32" if os_type == "windows" else os_type)
            data.setdefault("os_name", "nt" if os_type == "windows" else "posix")
            data.setdefault("platform_system", {"windows": "Windows", "linux": "Linux", "darwin": "Darwin"}[os_type])
    return data


def _marker_names(marker: Marker) -> set[str]:
    # Strip string literals first, so an arbitrary quoted value doesn't look
    # like a marker field. This is for conservative information availability,
    # not PEP 508 parsing (packaging handles the parsing).
    unquoted = _QUOTED.sub("''", str(marker))
    return {word for word in re.findall(r"\b[a-z_]+\b", unquoted) if word in _MARKER_KEYS}


def marker_state(marker: Marker | None, environment: dict[str, str], extras: Iterable[str] = ()) -> str:
    """Return active | marker_excluded | optional_unselected | unknown.

    `extra` is evaluated for each explicitly requested extra and the base
    dependency set. Unselected extras cannot silently become required.
    """
    if marker is None:
        return "active"
    used = _marker_names(marker)
    if used - {"extra"} - environment.keys():
        return "unknown"
    text = str(marker)
    if "extra" in used and _UNSUPPORTED_EXTRA.search(text):
        return "unknown"  # Unclear set semantics; never treat as required.
    selected = sorted({canonical_name(x) for x in extras})
    try:
        for extra in ["", *selected]:
            if marker.evaluate(environment={**environment, "extra": extra}):
                return "active"
        if "extra" in used:
            candidates = {canonical_name(a or b) for a, b in _NAMED_EXTRA.findall(text)}
            for candidate in candidates - set(selected):
                if marker.evaluate(environment={**environment, "extra": candidate}):
                    return "optional_unselected"
        return "marker_excluded"
    except (InvalidMarker, ValueError, KeyError, TypeError):
        return "unknown"


def version_satisfies(requirement: Requirement, installed_version: str) -> bool | None:
    try:
        return requirement.specifier.contains(Version(installed_version), prereleases=True)
    except InvalidVersion:
        return None


def python_satisfies(spec: str | None, version: str | None) -> bool | None:
    if not spec or not version:
        return None
    try:
        return SpecifierSet(spec).contains(Version(version), prereleases=True)
    except (InvalidSpecifier, InvalidVersion):
        return None
