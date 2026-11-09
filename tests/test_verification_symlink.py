"""Regression for POSIX venv/bin/python symlink identity (rc1 bug)."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.verification import verify_interpreter_selection, VerificationError

@unittest.skipUnless(os.name == "posix", "POSIX symlinked venv check")
class VenvSymlinkTests(unittest.TestCase):
    def test_distinct_venvs_pointing_to_same_binary_are_valid_candidates(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            good, bad = root / "good", root / "bad"
            for venv in (good, bad):
                subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(venv)], check=True)
            pgood, pbad = good / "bin" / "python", bad / "bin" / "python"
            self.assertEqual(pgood.resolve(), pbad.resolve())
            purelib = subprocess.check_output([str(pgood), "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"], text=True).strip()
            (Path(purelib)/"only_in_candidate_v1.py").write_text("X=1\n")
            proof = verify_interpreter_selection(project=str(root), original_python=str(pbad),
                candidate_python=str(pgood), arguments=["-m", "only_in_candidate_v1"],
                allow_local_execution=True, timeout=20, output=str(root / "proof.json"))
            self.assertEqual(proof["status"], "observed_candidate_succeeds")
            self.assertEqual(proof["original"]["exit_code"], 1)
            self.assertEqual(proof["candidate"]["exit_code"], 0)

    def test_same_env_alias_rejected(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            good = root / "good"
            subprocess.run([sys.executable, "-m", "venv", "--without-pip", str(good)], check=True)
            with self.assertRaises(VerificationError):
                verify_interpreter_selection(project=str(root), original_python=str(good / "bin/python"),
                    candidate_python=str(good / "bin/python3"), arguments=["-m", "no_module"],
                    allow_local_execution=True, output=str(root / "proof.json"))
