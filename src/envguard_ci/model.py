"""Stable schemas, canonical hashing and low-trust manifest validation."""

from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

SCHEMA_VERSION = "1.0"
_NAME_SEPARATORS = re.compile(r"[-_.]+")


class SnapshotError(ValueError):
    """A manifest is invalid, unrecognized or unsafe to process."""


def canonical_name(name: str) -> str:
    return _NAME_SEPARATORS.sub("-", name).lower()


def sanitize_requirement(value: str) -> str:
    """Remove direct-reference URLs, which may contain embedded credentials."""
    # Examples: `my-package @ https://user:password@example.org/wheel.whl`
    # and PEP 508 direct references with fragments or query tokens.
    return re.sub(r"\s+@\s+\S+", " @ [redacted-url]", value)


def canonical_json(data: Any) -> bytes:
    """Stable across key ordering, whitespace and local paths."""
    return json.dumps(data, sort_keys=True, separators=(",", ":"), ensure_ascii=False,
                      allow_nan=False).encode("utf-8")


def digest(data: Any) -> str:
    return "sha256:" + hashlib.sha256(canonical_json(data)).hexdigest()


def fingerprint(snapshot: dict[str, Any]) -> dict[str, str | None]:
    """Spec and runtime are separate: matching locks never imply identical runtimes."""
    project = snapshot.get("project") or {}
    runtime = snapshot.get("runtime") or {}
    platform = snapshot.get("platform") or {}
    packages = snapshot.get("packages") or []
    native = snapshot.get("native") or {}
    project_spec = {
        "files": sorted(project.get("files") or [], key=lambda p: p["name"]),
        "requires_python": project.get("requires_python"),
        "dependencies": sorted(project.get("dependencies") or []),
    }
    if project.get("optional_dependencies"):
        project_spec["optional_dependencies"] = project["optional_dependencies"]
    if project.get("name"):
        project_spec["name"] = project["name"]
    # Keep compatibility with v2.0 snapshots which lack the new fields.
    # Target marker metadata is fingerprinted when present, not guessed.
    runtime_state = {
        "python": {k: runtime.get(k) for k in ("version", "implementation", "soabi", "environment_kind")},
        "platform": {k: platform.get(k) for k in ("os", "arch", "libc")},
        "packages": sorted(
            [{"name": canonical_name(p["name"]), "version": p["version"],
              "wheel_tags": sorted(p.get("wheel_tags") or []),
              "requires": sorted(p.get("requires") or []),
              "origin_hash": p.get("origin_hash")}
             for p in packages],
            key=lambda p: (p["name"], p["version"]),
        ),
        "native": {
            "scan_status": native.get("scan_status", "disabled"),
            "libraries": sorted(native.get("libraries") or []),
            "requirements": sorted(native.get("requirements") or [],
                                   key=lambda v: v.get("extension", "")),
            "provided_symbols": {key: sorted(vals) for key, vals in
                                 sorted((native.get("provided_symbols") or {}).items())},
        },
    }
    if runtime.get("marker_environment"):
        runtime_state["marker_environment"] = runtime["marker_environment"]
    return {"spec": digest(project_spec), "runtime": digest(runtime_state),
            "artifact": None}  # Unknown: installed packages cannot attest wheel/container bytes.


def validate_snapshot(snapshot: Any) -> dict[str, Any]:
    if not isinstance(snapshot, dict):
        raise SnapshotError("Snapshot must be a JSON object")
    if snapshot.get("schema_version") != SCHEMA_VERSION:
        raise SnapshotError(f"Unsupported schema_version {snapshot.get('schema_version')!r}; expected {SCHEMA_VERSION}")
    for key in ("runtime", "platform", "project"):
        if not isinstance(snapshot.get(key), dict):
            raise SnapshotError(f"Invalid '{key}': expected object")
    if not isinstance(snapshot.get("packages"), list):
        raise SnapshotError("Invalid 'packages': expected array")
    if len(snapshot["packages"]) > 50000:
        raise SnapshotError("Too many packages in snapshot")
    seen: set[str] = set()
    for p in snapshot["packages"]:
        if not isinstance(p, dict) or not isinstance(p.get("name"), str) or not isinstance(p.get("version"), str):
            raise SnapshotError("Each package needs name and version strings")
        name = canonical_name(p["name"])
        if name in seen:
            raise SnapshotError(f"Duplicate package name {name!r}")
        seen.add(name)
    return snapshot


def read_snapshot(path: str | Path) -> dict[str, Any]:
    try:
        path = Path(path)
        if path.stat().st_size > 40_000_000:
            raise SnapshotError("Snapshot exceeds 40 MB")
        return validate_snapshot(json.loads(path.read_text(encoding="utf-8")))
    except (OSError, json.JSONDecodeError, UnicodeError) as exc:
        raise SnapshotError(f"Could not read snapshot {path}: {exc}") from exc


def write_json(data: Any, output: str | Path) -> None:
    """Write diagnostics atomically so interrupted jobs don't leave partial JSON.

    Create the temporary file in the destination directory (same filesystem),
    with private permissions. stdout remains unchanged. Caller controls which
    artifact paths are exposed to other processes or CI upload steps.
    """
    encoded = json.dumps(data, ensure_ascii=False, sort_keys=True, indent=2,
                         allow_nan=False) + "\n"
    if str(output) == "-":
        print(encoded, end="")
        return
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp: Path | None = None
    try:
        with tempfile.NamedTemporaryFile(
            mode="w", encoding="utf-8", newline="\n", dir=path.parent,
            prefix=".envguard-", suffix=".tmp", delete=False
        ) as fp:
            tmp = Path(fp.name)
            fp.write(encoded)
            fp.flush()
            os.fsync(fp.fileno())
        os.replace(tmp, path)
    finally:
        if tmp is not None:
            tmp.unlink(missing_ok=True)
