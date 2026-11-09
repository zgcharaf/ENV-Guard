"""Cross-platform, offline, disposable two-interpreter verification demonstration.

Runs only controlled synthetic riskbatch from the bundled lab. Requires Python
3.11+ and pip/venv. The final report states test success, not global causality.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / 'lab'))
from lab.run_lab import python_in, run  # noqa: E402


def main() -> int:
    out = ROOT / 'lab' / '.envguard-runs'
    benchmark = run(out, names=['wrong_interpreter'])
    if not benchmark['cases'][0]['passed']:
        return 1
    env = os.environ.copy()
    env['PYTHONPATH'] = str(ROOT / 'src') + os.pathsep + env.get('PYTHONPATH', '')
    proof = out / 'v1-repair-proof.json'
    command = [sys.executable, '-m', 'envguard_ci', 'verify-interpreter',
               '--project', str(ROOT / 'lab' / 'project'),
               '--original-python', str(python_in(out / 'venvs' / 'wrong_interpreter')),
               '--candidate-python', str(python_in(out / 'venvs' / 'baseline')),
               '--allow-local-execution', '--out', str(proof), '--', '-m', 'riskbatch']
    result = subprocess.run(command, cwd=ROOT, env=env, timeout=120, check=False)
    if result.returncode != 0:
        return result.returncode
    report = json.loads(proof.read_text(encoding='utf-8'))
    if (report['original']['exit_code'], report['candidate']['exit_code']) != (1, 0):
        return 1
    print('V1 DEMO PASS — observed original exit 1, candidate exit 0, report:', proof)
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
