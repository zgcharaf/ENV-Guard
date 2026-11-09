"""Read-only Python interpreter and package introspection."""

from __future__ import annotations

import datetime as dt
import json
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any

from .model import SCHEMA_VERSION, canonical_name, fingerprint, validate_snapshot
from .native import inspect_native
from .project import inspect_project

# Run using the selected Python, not this CLI's Python. No pip invocation,
# imports from the user's project, environment variable dumps, or installations.
_PROBE = r'''
import importlib.metadata as md
import json
import os
import platform
import re
import sys
import sysconfig

packages = []
libs = []
seen = set()
for dist in md.distributions():
    try:
        name = str(dist.metadata.get('Name', '')).strip()
        version = str(dist.version).strip()
        if not name or not version:
            continue
        normal = __import__('re').sub(r'[-_.]+', '-', name).lower()
        if normal in seen:
            continue
        seen.add(normal)
        whl = dist.read_text('WHEEL') or ''
        tags = sorted(set(line.split(':', 1)[1].strip() for line in whl.splitlines()
                          if line.lower().startswith('tag:')))
        packages.append({'name': normal, 'version': version,
                         'requires': sorted(re.sub(r'\s+@\s+\S+', ' @ [redacted-url]', v) for v in (dist.requires or [])), 'wheel_tags': tags,
                         'origin_hash': None})
        if os.environ.get('ENVGUARD_NATIVE_PROBE') == '1':
            for f in dist.files or ():
                path = str(f)
                if path.endswith(('.so', '.pyd', '.dylib')):
                    try:
                        located = str(dist.locate_file(f))
                        libs.append({'name': os.path.basename(path), 'path': located,
                                     'package': normal})
                    except (OSError, ValueError):
                        pass
    except Exception:
        continue

# Distribution-to-import-root mapping (metadata only: no module import performed).
# It is incomplete for some namespace packages and editable installs.
try:
    owners = {root: sorted(set(re.sub(r'[-_.]+', '-', d).lower() for d in dists))
              for root, dists in md.packages_distributions().items()
              if isinstance(root, str) and len(root) < 200 and isinstance(dists, list)}
except Exception:
    owners = {}

info = {
  'provenance_raw': {
    'executable': sys.executable,
    'prefix': sys.prefix,
    'base_prefix': sys.base_prefix,
    'sys_path': sys.path,
    'import_owners': owners,
  },
  'runtime': {
    'marker_environment': {
      'implementation_name': sys.implementation.name,
      'implementation_version': (lambda v: f'{v.major}.{v.minor}.{v.micro}' +
          ({'alpha': 'a', 'beta': 'b', 'candidate': 'rc', 'final': ''}.get(v.releaselevel, '') +
           str(v.serial) if v.releaselevel != 'final' else ''))(sys.implementation.version),
      'os_name': os.name,
      'platform_machine': platform.machine(),
      'platform_python_implementation': platform.python_implementation(),
      'platform_release': platform.release(),
      'platform_system': platform.system(),
      'platform_version': platform.version(),
      'python_full_version': platform.python_version(),
      'python_version': '.'.join(platform.python_version_tuple()[:2]),
      'sys_platform': sys.platform,
    },
    'version': platform.python_version(),
    'implementation': platform.python_implementation(),
    'soabi': sysconfig.get_config_var('SOABI'),
    'environment_kind': 'venv' if sys.prefix != sys.base_prefix else 'system',
    'executable_name': os.path.basename(sys.executable)
  },
  'platform': {
    'os': platform.system().lower(),
    'arch': platform.machine().lower(),
    'libc': '-'.join(v for v in platform.libc_ver() if v) or None
  },
  'packages': sorted(packages, key=lambda x: x['name']),
  'native_paths': libs
}
print(json.dumps(info, sort_keys=True))
'''


class CollectionError(RuntimeError):
    """Failed to inspect interpreter without modifying it."""


def snapshot(project: str | Path, python: str = sys.executable, native: bool = False) -> dict[str, Any]:
    root = Path(project).expanduser().resolve()
    config = inspect_project(root)
    executable = shutil.which(python) if not Path(python).is_file() else python
    if not executable:
        raise CollectionError(f"Python interpreter not found: {python}")
    # A child process isolates `importlib.metadata` from this CLI's interpreter.
    import os
    env = os.environ.copy()
    env["ENVGUARD_NATIVE_PROBE"] = "1" if native else "0"
    try:
        result = subprocess.run([executable, "-c", _PROBE], capture_output=True,
                                text=True, timeout=45, env=env, cwd=str(root),
                                encoding="utf-8", errors="replace")
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise CollectionError(f"Could not inspect {python}: {exc}") from exc
    if result.returncode != 0:
        # Startup hooks and wrapper failures may print credentials or private
        # paths to stderr. Never echo that untrusted stderr from a probe.
        raise CollectionError(f"Python probe failed (exit {result.returncode}); "
                              "stderr withheld to protect potentially sensitive data")
    try:
        data = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise CollectionError("Python probe produced invalid JSON") from exc
    data["packages"] = sorted(data["packages"], key=lambda x: canonical_name(x["name"]))
    native_paths = data.pop("native_paths")
    # Raw interpreter paths are used only for local correlation. Do not copy
    # them into the persisted manifest: usernames and registry mount paths can
    # be sensitive. Hash or redact them before storing.
    raw = data.pop("provenance_raw", {})
    from .provenance import interpreter_identity
    imports: dict[str, list[str]] = {}
    installed = {canonical_name(p["name"]) for p in data["packages"]}
    for import_name, owners in raw.get("import_owners", {}).items():
        if import_name.isidentifier():
            mapped = sorted({canonical_name(owner) for owner in owners if canonical_name(owner) in installed})
            if mapped:
                imports[import_name] = mapped
    sys_path_origins = []
    import os
    for raw_path in (raw.get("sys_path") or [])[:100]:
        if not isinstance(raw_path, str):
            continue
        if not raw_path:
            kind = "working-directory"
        elif "site-packages" in raw_path or "dist-packages" in raw_path:
            kind = "site-packages"
        elif "python" in raw_path.lower():
            kind = "python-runtime"
        else:
            kind = "other"
        sys_path_origins.append(kind)
    data["runtime"]["provenance"] = {
        "executable": interpreter_identity(raw.get("executable", executable), root),
        "prefix": interpreter_identity(raw.get("prefix", ""), root) if raw.get("prefix") else None,
        "base_prefix": interpreter_identity(raw.get("base_prefix", ""), root) if raw.get("base_prefix") else None,
        "sys_path_kinds": sys_path_origins,
        "import_owners": dict(sorted(imports.items())),
        "coverage": "metadata-only; not proof of import resolution or editable install validity",
    }
    native_paths.sort(key=lambda v: (v["package"], v["name"]))
    native_result = inspect_native(native_paths) if native else {
        "scan_status": "disabled", "libraries": [], "requirements": [],
        "provided_symbols": {}, "notes": ["Pass --native to inspect ELF requirements on Linux"]}
    snap: dict[str, Any] = {
        "schema_version": SCHEMA_VERSION,
        "captured_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "project": config,
        "runtime": data["runtime"],
        "platform": data["platform"],
        "packages": data["packages"],
        "native": native_result,
    }
    snap["fingerprints"] = fingerprint(snap)
    return validate_snapshot(snap)
