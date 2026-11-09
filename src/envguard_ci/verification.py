"""Constrained, user-authorized interpreter-selection repair experiment.

Runs the same Python program twice under two explicitly named interpreters.
No patch is generated, no files are changed by EnvGuard itself, and this is
NOT A SANDBOX: application code may have side effects. Use disposable runners.
"""
from __future__ import annotations

import hashlib
import subprocess
from pathlib import Path
from typing import Any

from .collection import CollectionError, snapshot
from .comparability import assess_targets
from .model import write_json
from .provenance import interpreter_identity


class VerificationError(ValueError):
    pass


def _execute(executable: str, arguments: list[str], project: Path, timeout: int) -> tuple[int | None, str, str]:
    try:
        proc = subprocess.run([executable, *arguments], cwd=project, capture_output=True,
                              timeout=timeout, encoding='utf-8', errors='replace', check=False)
        # Private logs are never persisted, use hashes for run identity.
        fingerprint = hashlib.sha256((proc.stdout + '\n' + proc.stderr).encode('utf-8')).hexdigest()
        return proc.returncode, f'sha256:{fingerprint}', 'completed'
    except subprocess.TimeoutExpired:
        return None, '', 'timeout'
    except OSError:
        return None, '', 'launch_error'


def verify_interpreter_selection(*, project: str, original_python: str, candidate_python: str,
                                 arguments: list[str], output: str, allow_local_execution: bool = False,
                                 timeout: int = 60) -> dict[str, Any]:
    if not allow_local_execution:
        raise VerificationError('Explicitly pass --allow-local-execution; the application is executed twice without a sandbox')
    root = Path(project).expanduser().resolve()
    if not root.is_dir():
        raise VerificationError('Project directory does not exist')
    if not arguments or arguments[0] not in ('-m', '-c'):
        raise VerificationError('Only explicit Python -m or -c invocation is supported')
    if len(arguments) < 2 or not 1 <= timeout <= 300:
        raise VerificationError('Require a module/script and timeout between 1 and 300 seconds')
    # Preserve executable *invocation* paths.  On Linux, two different venvs
    # commonly have bin/python symlinks resolving to the SAME base executable.
    # The venv identity comes from invocation path / sys.prefix, not realpath.
    original = Path(original_python).expanduser().absolute()
    candidate = Path(candidate_python).expanduser().absolute()
    if not original.is_file() or not candidate.is_file() or original == candidate:
        raise VerificationError('Require two distinct existing Python executable paths')
    try:
        before = snapshot(root, python=str(original))
        after = snapshot(root, python=str(candidate))
    except CollectionError as exc:
        raise VerificationError('Both Python runtimes must be inspectable before executing the experiment') from exc
    original_prefix = (before.get('runtime', {}).get('provenance', {}).get('prefix') or {}).get('id')
    candidate_prefix = (after.get('runtime', {}).get('provenance', {}).get('prefix') or {}).get('id')
    if not original_prefix or not candidate_prefix or original_prefix == candidate_prefix:
        raise VerificationError('Interpreters must belong to distinct observable Python environments')
    base_code, base_hash, base_status = _execute(str(original), arguments, root, timeout)
    # Do not execute candidate when baseline failed to launch or timed out.
    if base_status == 'completed' and base_code != 0:
        fix_code, fix_hash, fix_status = _execute(str(candidate), arguments, root, timeout)
    else:
        fix_code, fix_hash, fix_status = None, '', 'not_executed'
    comparable = assess_targets(before, after)
    supported = base_status == 'completed' and base_code not in (None, 0) and fix_status == 'completed' and fix_code == 0
    report = {
        'schema_version': '1.0', 'experiment': 'interpreter_selection',
        'status': 'observed_candidate_succeeds' if supported else 'not_verified',
        'project_runtime_comparability': comparable,
        'original_interpreter': interpreter_identity(str(original), root),
        'candidate_interpreter': interpreter_identity(str(candidate), root),
        'original_runtime_fingerprint': before['fingerprints']['runtime'],
        'candidate_runtime_fingerprint': after['fingerprints']['runtime'],
        'original': {'exit_code': base_code, 'status': base_status, 'combined_output_sha256': base_hash},
        'candidate': {'exit_code': fix_code, 'status': fix_status, 'combined_output_sha256': fix_hash},
        'automatic_changes_made': False,
        'limitations': [
            'This is a local process experiment, NOT an isolated sandbox. The tested code may produce side effects.',
            'Passing this specific command does not prove general environment or production compatibility.',
            'Interpreter choice and installed packages may both differ; this experiment does not isolate one underlying causal factor.',
            'No source patch or dependency mutation was applied by EnvGuard.'
        ],
    }
    write_json(report, output)
    return report
