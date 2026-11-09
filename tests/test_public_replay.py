"""Regression tests for the known-public-issue replay and its claim boundary."""
from __future__ import annotations

import copy
import hashlib
import sys
from pathlib import Path
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from research.replay_public_conflict import command, observed_outcome  # noqa: E402
from research.validate_public_replay import validate  # noqa: E402


def fixture():
    empty_hash = hashlib.sha256(b"").hexdigest()
    return {
        "schema_version": "1.0",
        "experiment": "public_pypi_minimal_pair_resolution",
        "study_role": "public_development_exemplar",
        "is_independent_blind_test": False,
        "may_be_counted_in_holdout_accuracy": False,
        "source": {"issue": "https://github.com/cvsz/zbase/issues/19"},
        "input_versions": {"pytest": "9.0.3",
                           "conflicting_pytest_asyncio": "1.2.0",
                           "corrected_pytest_asyncio": "1.4.0"},
        "status": "minimal_pair_reproduced",
        "outcomes": {
            "conflict": {"case": "conflict", "exit_code": 1,
                         "has_resolution_impossible": True, "has_conflict_explanation": True,
                         "combined_output_sha256": empty_hash},
            "corrected": {"case": "corrected", "exit_code": 0,
                          "has_resolution_impossible": False, "has_conflict_explanation": False,
                          "combined_output_sha256": empty_hash},
        },
    }


class PublicReplayTests(unittest.TestCase):
    def test_pip_only_public_wheels_and_no_install(self):
        args = command("1.2.0")
        self.assertIn("--dry-run", args)
        self.assertIn("--ignore-installed", args)
        self.assertIn("--isolated", args)
        self.assertIn("--only-binary=:all:", args)
        self.assertIn("https://pypi.org/simple", args)
        self.assertNotIn("--no-deps", args)
        self.assertIn("pytest==9.0.3", args)

    def test_only_preregistered_versions(self):
        with self.assertRaises(ValueError):
            command("0.0.0")

    def test_output_stores_hash_not_raw_lines(self):
        result = observed_outcome(
            returncode=1, stdout="ERROR: ResolutionImpossible; conflicting dependencies",
            case="conflict", report=None,
        )
        self.assertTrue(result["has_resolution_impossible"])
        self.assertTrue(result["has_conflict_explanation"])
        self.assertNotIn("stdout", result)
        self.assertEqual(len(result["combined_output_sha256"]), 64)

    def test_clean_validation(self):
        self.assertFalse(validate(fixture())["holdout_accuracy_eligible"])

    def test_cannot_falsely_promote_to_blind(self):
        data = copy.deepcopy(fixture())
        data["may_be_counted_in_holdout_accuracy"] = True
        with self.assertRaises(ValueError):
            validate(data)

    def test_broken_pair_must_fail(self):
        data = copy.deepcopy(fixture())
        data["outcomes"]["conflict"]["exit_code"] = 0
        with self.assertRaises(ValueError):
            validate(data)

    def test_fixed_pair_must_succeed(self):
        data = copy.deepcopy(fixture())
        data["outcomes"]["corrected"]["exit_code"] = 1
        with self.assertRaises(ValueError):
            validate(data)


if __name__ == "__main__":
    unittest.main()
