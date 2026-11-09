"""Execution provenance for *direct* Python invocations.

Do not infer the interpreter for shell commands, uv wrappers, arbitrary scripts,
pytest console entry points, or launcher aliases. Unknown is safer than wrong.
No source path, full command or environment variable is persisted in reports.
"""
from __future__ import annotations

import hashlib
import os
import re
import shutil
from pathlib import Path
from typing import Any

_PYTHON = re.compile(r"^python(?:w|\d+(?:\.\d+)*|\d+(?:\.\d+)*-\d+)?(?:\.exe)?$", re.I)


def _absolute(value: str, project: str | Path = ".") -> str:
    if not value:
        raise ValueError("Interpreter path must be nonempty")
    file = shutil.which(value) if not ("/" in value or "\\" in value) else None
    base = str(Path(project).absolute())
    path = file or (value if os.path.isabs(value) else os.path.join(base, value))
    # Deliberately do not resolve symlinks: venv/bin/python frequently points at
    # system Python, but these remain distinct runtime environments.
    return os.path.normcase(os.path.abspath(path))


def _token(path: str) -> str:
    return "sha256:" + hashlib.sha256(os.fsencode(path)).hexdigest()


def _label(path: str, project: str | Path = ".") -> str:
    project_path = os.path.normcase(os.path.abspath(str(project)))
    home = os.path.normcase(os.path.abspath(str(Path.home())))
    # A filesystem root is not a meaningful project privacy boundary:
    # otherwise /opt/private paths become leaked as $PROJECT/opt/private.
    roots = {os.path.normcase(os.path.abspath(os.path.sep))}
    if os.name == "nt":
        roots.add(os.path.splitdrive(project_path)[0] + os.path.sep)
    candidates = [(home, "$HOME")]
    if project_path not in roots:
        candidates.insert(0, (project_path, "$PROJECT"))
    for prefix, name in candidates:
        try:
            rel = os.path.relpath(path, prefix)
            if rel == ".":
                return name
            if rel != ".." and not rel.startswith(".." + os.sep):
                return name + "/" + rel.replace("\\", "/")
        except ValueError:
            continue
    return "<external>/" + os.path.basename(path)


def interpreter_identity(python: str, project: str | Path = ".") -> dict[str, str]:
    normalized = _absolute(python, project)
    identity = _token(normalized)
    label = _label(normalized, project)
    # External interpreters may both be named `python` without exposing their
    # private parent directories. Add a short display-only identity suffix.
    if label.startswith("<external>/"):
        label += "#" + identity.split(":", 1)[1][:10]
    return {"id": identity, "label": label}


def invoked_python(command: list[str], *, project: str | Path = ".") -> str | None:
    """Recognize only argv[0] that is unambiguously a Python executable.

    This does not inspect scripts, subprocesses or uv/poetry run wrappers.
    """
    if not command:
        return None
    cmd = command[0]
    if not _PYTHON.fullmatch(os.path.basename(cmd)):
        return None
    candidate = _absolute(cmd, project)
    return candidate if Path(candidate).is_file() else None


def _python_flags(command: list[str]) -> dict[str, bool]:
    """Recognize flags ahead of -m/-c/script, not application arguments."""
    if not command:
        return {"site_disabled": False, "isolated": False, "no_environment": False}
    flags = {"site_disabled": False, "isolated": False, "no_environment": False}
    for arg in command[1:]:
        if arg in ("-m", "-c", "--") or not arg.startswith("-"):
            break
        if len(arg) >= 2 and arg.startswith("-") and not arg.startswith("--"):
            opts = arg[1:]
            flags["site_disabled"] |= "S" in opts
            flags["isolated"] |= "I" in opts
            flags["no_environment"] |= "E" in opts
    return flags


def execution_context(*, command: list[str] | None = None,
                      project: str | Path = ".", expected_python: str | None = None,
                      invoked_python_path: str | None = None) -> dict[str, Any]:
    """Record provenance, without capturing raw command arguments or home paths.

    `expected_python` must represent a consciously selected target interpreter;
    unknown is not silently treated as sys.executable.
    """
    command = command or []
    detected = invoked_python(command, project=project) if invoked_python_path is None else invoked_python_path
    observed = interpreter_identity(detected, project) if detected else None
    expected = interpreter_identity(expected_python, project) if expected_python else None
    flags = _python_flags(command) if detected else {"site_disabled": False, "isolated": False, "no_environment": False}
    return {
        "schema_version": "1.0",
        "observation": "direct-python-argv" if detected else "unknown-wrapper-or-command",
        "executed_python": observed,
        "expected_python": expected,
        "explicit_expected": bool(expected_python),
        "interpreter_match": (observed["id"] == expected["id"]) if observed and expected else None,
        "flags": flags,
        "limitations": "argv[0] provenance only; shell wrappers, Python child processes and launchers are not traced.",
    }
