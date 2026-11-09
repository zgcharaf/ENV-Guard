"""Inspect project metadata without executing project code or dependencies."""

from __future__ import annotations

import hashlib
import re
import tomllib
from pathlib import Path
from typing import Any

from .model import sanitize_requirement

MAX_PROJECT_FILE_BYTES = 40_000_000


def _hash_project_file(path: Path) -> str:
    """Bound project metadata reads and stream hashes without memory spikes."""
    if path.stat().st_size > MAX_PROJECT_FILE_BYTES:
        raise ValueError(f"Project metadata exceeds 40 MB: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


PROJECT_FILES = ("pyproject.toml", "uv.lock", "poetry.lock", "pylock.toml",
                 "requirements.txt", "requirements.lock", "Pipfile.lock")


def inspect_project(root: Path) -> dict[str, Any]:
    if not root.is_dir():
        raise ValueError(f"Not a directory: {root}")
    files: list[dict[str, str]] = []
    detected: list[str] = []
    config: dict[str, Any] = {}
    for name in PROJECT_FILES:
        path = root / name
        if path.is_file():
            files.append({"name": name, "sha256": _hash_project_file(path)})
    # Named PEP 751 lock files; no parsing or installation performed.
    for path in sorted(root.glob("pylock.*.toml")):
        if path.is_file() and re.fullmatch(r"pylock\.[^.]+\.toml", path.name):
            files.append({"name": path.name, "sha256": _hash_project_file(path)})
    names = {x["name"] for x in files}
    if "uv.lock" in names:
        detected.append("uv")
    if "poetry.lock" in names:
        detected.append("poetry")
    if any(n.startswith("pylock") for n in names):
        detected.append("pylock")
    if "Pipfile.lock" in names:
        detected.append("pipenv")
    if "requirements.txt" in names or "requirements.lock" in names:
        detected.append("pip")
    requires_python = None
    dependencies: list[str] = []
    optional_dependencies: dict[str, list[str]] = {}
    project_name: str | None = None
    if "pyproject.toml" in names:
        try:
            with (root / "pyproject.toml").open("rb") as f:
                config = tomllib.load(f)
        except (OSError, tomllib.TOMLDecodeError) as exc:
            raise ValueError(f"Invalid pyproject.toml: {exc}") from exc
        project = config.get("project") or {}
        if isinstance(project, dict):
            if isinstance(project.get("name"), str):
                project_name = project["name"]
            optional = project.get("optional-dependencies") or {}
            if isinstance(optional, dict):
                for extra, items in optional.items():
                    if isinstance(extra, str) and isinstance(items, list):
                        optional_dependencies[extra.lower().replace("_", "-")] = sorted(
                            sanitize_requirement(d) for d in items if isinstance(d, str))
            rp = project.get("requires-python")
            if isinstance(rp, str):
                requires_python = rp
            dependencies = sorted(sanitize_requirement(d) for d in (project.get("dependencies") or []) if isinstance(d, str))
        tool = config.get("tool") or {}
        if isinstance(tool, dict):
            if "poetry" in tool and "poetry" not in detected:
                detected.append("poetry")
            if "uv" in tool and "uv" not in detected:
                detected.append("uv")
    return {"files": sorted(files, key=lambda v: v["name"]),
            "detected_managers": detected, "requires_python": requires_python,
            "dependencies": dependencies, "optional_dependencies": optional_dependencies, "name": project_name}
