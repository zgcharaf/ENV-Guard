from __future__ import annotations
import base64
import contextlib
import hashlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'src'))
from envguard_ci.artifacts import inspect_wheel, ArtifactError
from envguard_ci.certify import certify_wheel, CertificationError
from envguard_ci.verification import verify_interpreter_selection, VerificationError
from envguard_ci.github import fetch_github_baseline, GitHubError
from envguard_ci.cli import main
from envguard_ci.model import read_snapshot

ROOT = Path(__file__).resolve().parents[1]


def wheel_fixture(path: Path, tamper=False):
    entries = {'demo/__init__.py': b'OK=True\n', 'demo-1.0.dist-info/METADATA': b'Metadata-Version: 2.3\nName: demo\nVersion: 1.0\n'}
    rows = []
    for name, blob in entries.items():
        digest = base64.urlsafe_b64encode(hashlib.sha256(blob).digest()).rstrip(b'=').decode()
        rows.append(f'{name},sha256={digest},{len(blob)}')
    rows.append('demo-1.0.dist-info/RECORD,,')
    with zipfile.ZipFile(path, 'w') as z:
        for name, blob in entries.items():
            z.writestr(name, b'bad' if tamper and name.endswith('__init__.py') else blob)
        z.writestr('demo-1.0.dist-info/RECORD', '\n'.join(rows) + '\n')


class _FakeResponse:
    def __init__(self, value): self.value = value
    def read(self, size=-1): return self.value[:size]
    def __enter__(self): return self
    def __exit__(self, *args): return False


class _FakeGithub:
    def __init__(self, snapshot):
        self.requests=[]
        stream=io.BytesIO()
        with zipfile.ZipFile(stream, 'w') as z:
            z.writestr('envguard-ci.json', json.dumps(snapshot))
        self.zipblob=stream.getvalue()
    def open(self, req, timeout=0):
        url=req.full_url
        self.requests.append(url)
        if '/workflows/' in url and '/runs?' in url:
            return _FakeResponse(json.dumps({'workflow_runs':[{'id':42,'conclusion':'success'}]}).encode())
        if '/runs/42/artifacts' in url:
            return _FakeResponse(json.dumps({'artifacts':[{'id':53,'name':'envguard-baseline','expired':False,'size_in_bytes':len(self.zipblob)}]}).encode())
        if '/artifacts/53/zip' in url:
            return _FakeResponse(self.zipblob)
        raise AssertionError(url)


class V1Tests(unittest.TestCase):
    def test_wheel_digest_and_record(self):
        with tempfile.TemporaryDirectory() as t:
            wh=Path(t)/'demo-1.0-py3-none-any.whl'; wheel_fixture(wh)
            r=inspect_wheel(str(wh))
            self.assertEqual(r['status'], 'verified_integrity')
            self.assertTrue(r['host_interpreter_wheel_tag_compatible'])
            self.assertEqual(r['record_sha256_verified'], 2)
            self.assertEqual(r['record_unverified'], 1)
            self.assertEqual(inspect_wheel(str(wh), approved_sha256='0'*64)['status'],'integrity_failure')

    def test_corrupted_record_detected(self):
        with tempfile.TemporaryDirectory() as t:
            wh=Path(t)/'demo-1.0-py3-none-any.whl'; wheel_fixture(wh,True)
            r=inspect_wheel(str(wh))
            self.assertEqual(r['status'],'integrity_failure')
            self.assertIn('RECORD sha256 mismatch',r['record_errors'])

    def test_unsafe_archive_path_rejected(self):
        with tempfile.TemporaryDirectory() as t:
            wh=Path(t)/'demo-1.0-py3-none-any.whl'
            with zipfile.ZipFile(wh,'w') as z:
                z.writestr('../oops',b'abc')
                z.writestr('demo-1.0.dist-info/RECORD','../oops,,\n')
            with self.assertRaises(ArtifactError): inspect_wheel(str(wh))

    def test_github_baseline_with_mock_api(self):
        snap=read_snapshot(ROOT/'tests/fixtures/baseline.json')
        fake=_FakeGithub(snap)
        with tempfile.TemporaryDirectory() as t, patch.dict(os.environ, {'GITHUB_TOKEN':'TEST_TOKEN'}):
            out=Path(t)/'baseline.json'
            got=fetch_github_baseline(str(out),repo='acme/eng',branch='main',workflow='ci.yml',opener=fake)
            self.assertEqual(got['runtime']['version'], snap['runtime']['version'])
            self.assertEqual(read_snapshot(out)['project'], snap['project'])
            self.assertEqual(len(fake.requests),3)
            self.assertFalse(any('TEST_TOKEN' in url for url in fake.requests))

    def test_github_without_token_is_safe_error(self):
        with patch.dict(os.environ,{'GITHUB_TOKEN':'','ENVGUARD_GITHUB_READ_TOKEN':''}):
            with self.assertRaises(GitHubError):
                fetch_github_baseline('-', repo='acme/eng',branch='main',workflow='ci.yml')

    def test_repair_refuses_unapproved_local_execution(self):
        with tempfile.TemporaryDirectory() as t:
            with self.assertRaises(VerificationError):
                verify_interpreter_selection(project=t,original_python=sys.executable,
                    candidate_python=sys.executable, arguments=['-m','hello'],output=str(Path(t)/'x.json'))

    def test_certify_requires_digest(self):
        with tempfile.TemporaryDirectory() as t:
            wh=Path(t)/'demo-1.0-py3-none-any.whl'; wheel_fixture(wh)
            with self.assertRaises(CertificationError):
                certify_wheel(wheel=str(wh), image='python:3.12', module='demo',output=str(Path(t)/'proof.json'))

    def test_certify_mocks_docker_without_network(self):
        with tempfile.TemporaryDirectory() as t:
            wh=Path(t)/'demo-1.0-py3-none-any.whl'; wheel_fixture(wh)
            from subprocess import CompletedProcess
            with patch('envguard_ci.certify.subprocess.run',return_value=CompletedProcess([],0,'ENVGUARD_IMPORT_SMOKE_SUCCEEDED','')) as run:
                report=certify_wheel(wheel=str(wh),image='python@sha256:'+'0'*64,
                  module='demo',output=str(Path(t)/'proof.json'))
                self.assertEqual(report['status'],'passed')
                args=run.call_args.args[0]
                self.assertIn('--network',args)
                self.assertIn('none',args)
                self.assertIn('--read-only',args)

    def test_investigate_offline_preserves_failed_command_and_report(self):
        with tempfile.TemporaryDirectory() as t, contextlib.redirect_stdout(io.StringIO()):
            dst=Path(t)/'diag.json'
            rc=main(['investigate','--project',str(ROOT),'--python',sys.executable,
                '--report-out',str(dst),'--snapshot-out',str(Path(t)/'env.json'),
                '--',sys.executable,'-m','package_thats_missing_in_ci_v1_test'])
            self.assertEqual(rc,1)
            report=json.loads(dst.read_text())
            self.assertEqual(report['ci']['command_exit_code'],1)
            self.assertEqual(report['ci']['baseline_source'],'not_requested')
            self.assertFalse(report['ci']['baseline_is_historical_predecessor_verified'])

    def test_investigate_last_green_unavailable_can_fail_open(self):
        from envguard_ci.github import GitHubError
        with tempfile.TemporaryDirectory() as t, patch('envguard_ci.ci.fetch_github_baseline',side_effect=GitHubError('token redacted')):
            with contextlib.redirect_stdout(io.StringIO()):
                report=Path(t)/'r.json'
                rc=main(['investigate','--project',str(ROOT),'--last-green','github',
                    '--report-out',str(report),'--snapshot-out',str(Path(t)/'s.json'),
                    '--',sys.executable,'-c','print("ok")'])
            self.assertEqual(rc,0)
            data=json.loads(report.read_text())
            self.assertEqual(data['ci']['baseline_source'],'unavailable')
            self.assertFalse(data['ci']['baseline_provided'])
            self.assertNotIn('token redacted',str(data))

    def test_investigate_successful_gitlab_baseline_is_used(self):
        fixture = read_snapshot(ROOT/'tests/fixtures/baseline.json')
        with tempfile.TemporaryDirectory() as t, patch('envguard_ci.ci.fetch_baseline', return_value=fixture) as fetch:
            with contextlib.redirect_stdout(io.StringIO()):
                report = Path(t)/'r.json'
                rc = main(['investigate', '--project', str(ROOT), '--last-green', 'gitlab',
                    '--baseline-ref', 'main', '--baseline-job', 'envguard-ci:tests',
                    '--report-out', str(report), '--snapshot-out', str(Path(t)/'s.json'),
                    '--', sys.executable, '-c', 'print("ok")'])
            self.assertEqual(rc, 0)
            data = json.loads(report.read_text())
            self.assertTrue(data['ci']['baseline_provided'])
            self.assertEqual(data['ci']['baseline_source'], 'retrieved')
            self.assertEqual(data['ci']['diagnostic_mode'], 'diff')
            self.assertIn('baseline_comparability', data['ci'])
            self.assertEqual(fetch.call_args.kwargs['ref'], 'main')

    def test_inspect_real_build_wheel(self):
        wheels = list((ROOT/'dist').glob('envguard_ci-*.whl'))
        if not wheels:
            self.skipTest('Release wheel not built')
        r = inspect_wheel(str(wheels[0]))
        self.assertEqual(r['status'], 'verified_integrity')
        self.assertGreater(r['record_sha256_verified'], 0)

    def test_require_baseline_refuses_execution(self):
        from envguard_ci.github import GitHubError
        with tempfile.TemporaryDirectory() as t, patch('envguard_ci.ci.fetch_github_baseline',side_effect=GitHubError('private')):
            flag=Path(t)/'must-not-exist'
            rc=main(['investigate','--project',str(ROOT),'--last-green','github','--require-baseline',
                     '--',sys.executable,'-c',f'open({str(flag)!r},"w").write("oops")'])
            self.assertEqual(rc,2)
            self.assertFalse(flag.exists())

if __name__ == '__main__': unittest.main()
