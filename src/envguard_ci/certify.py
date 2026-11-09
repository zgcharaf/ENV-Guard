"""Offline wheel import smoke test in a hardened disposable Docker container.

A Docker container is NOT a complete hostile-code sandbox. It depends on the
security of the host Docker daemon, kernel, user namespaces and chosen image.
No network, privilege escalation, writes to project, or Docker socket mount.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import Any

from .artifacts import inspect_wheel
from .model import write_json


class CertificationError(ValueError):
    pass


_INSTALL = r'''
import importlib, json, pathlib, subprocess, sys
wheel = pathlib.Path('/wheel') / sys.argv[1]
module = sys.argv[2]
subprocess.check_call([sys.executable, '-m', 'venv', '/tmp/envguard-env'])
py = '/tmp/envguard-env/bin/python'
subprocess.check_call([py, '-m', 'pip', 'install', '--no-index', '--no-cache-dir',
                       '--find-links', '/wheel', '--find-links', '/wheelhouse', str(wheel)])
subprocess.check_call([py, '-c', 'import importlib,sys; importlib.import_module(sys.argv[1])', module])
print('ENVGUARD_IMPORT_SMOKE_SUCCEEDED')
'''


def certify_wheel(*, wheel: str, image: str, module: str, output: str, wheelhouse: str | None = None,
                  require_digest: bool = True, timeout: int = 150, approved_sha256: str | None = None) -> dict[str, Any]:
    """Run a wheel's import in a no-network disposable container.

    The *user* opts in to executing wheel installation and import; the wheel
    can execute Python code. Security review needed for untrusted artifacts.
    """
    if not re.fullmatch(r'[A-Za-z_]\w*(?:\.[A-Za-z_]\w*)*', module):
        raise CertificationError('Module must be a dotted Python import name')
    if not image or any(ord(c) <= 32 for c in image):
        raise CertificationError('Invalid target container image')
    if require_digest and not re.search(r'@sha256:[0-9a-f]{64}$', image):
        raise CertificationError('A pinned --image NAME@sha256:DIGEST is required (or acknowledge --allow-mutable-image)')
    if not 1 <= timeout <= 600:
        raise CertificationError('Timeout must be between 1 and 600 seconds')
    inspected = inspect_wheel(wheel, approved_sha256=approved_sha256, check_host_tags=False)
    if inspected['status'] != 'verified_integrity':
        raise CertificationError('Wheel RECORD or approved hash verification failed')
    path = Path(wheel).resolve()
    wheel_dir = path.parent
    if wheelhouse:
        house = Path(wheelhouse).resolve()
        if not house.is_dir():
            raise CertificationError('Wheelhouse directory not found')
    else:
        house = wheel_dir
    # Use a shell-free command and read-only bind mounts. The image itself is
    # expected to contain Python, pip and ensurepip/venv.
    cmd = ['docker', 'run', '--rm', '--network', 'none', '--read-only',
           '--security-opt', 'no-new-privileges', '--cap-drop', 'ALL',
           '--pids-limit', '128', '--memory', '1g', '--cpus', '2',
           '--user', '65534:65534', '--tmpfs', '/tmp:rw,nosuid,nodev,size=384m',
           '--tmpfs', '/home:rw,nosuid,nodev,size=64m',
           '--mount', f'type=bind,src={wheel_dir},dst=/wheel,readonly',
           '--mount', f'type=bind,src={house},dst=/wheelhouse,readonly',
           '--env', 'HOME=/tmp', '--env', 'PIP_DISABLE_PIP_VERSION_CHECK=1',
           image, 'python', '-c', _INSTALL, path.name, module]
    try:
        run = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout,
                             encoding='utf-8', errors='replace', check=False)
        status = 'passed' if run.returncode == 0 and 'ENVGUARD_IMPORT_SMOKE_SUCCEEDED' in run.stdout else 'failed'
        code = run.returncode
    except subprocess.TimeoutExpired:
        status, code = 'timeout', None
    except OSError:
        status, code = 'docker_unavailable', None
    report = {
        'schema_version': '1.0', 'kind': 'target_image_import_smoke',
        'status': status, 'exit_code': code,
        'wheel': {'sha256': inspected['sha256'], 'name': inspected['wheel_name'],
                  'record_errors': inspected['record_errors']},
        'target': {'image': image, 'digest_pinned': bool(re.search(r'@sha256:[0-9a-f]{64}$', image))},
        'smoke_module': module,
        'security': {'network': 'none', 'root_filesystem': 'read_only', 'privileges': 'dropped',
                     'workspace': 'not_mounted', 'wheelhouse': 'mounted_read_only'},
        'limitations': [
            'A Docker container is not a complete sandbox for untrusted build scripts or wheels.',
            'This import test does not certify business logic, security, or general production compatibility.',
            'Dependencies must be supplied by the approved offline wheelhouse or target image.',
            'Raw logs are not retained in the report; inspect CI job output for installer errors.'
        ]
    }
    write_json(report, output)
    return report
