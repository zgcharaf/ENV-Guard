"""Safety/consistency tests for the public, unlabelled incident discovery register."""
import copy
import json
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "research"))
from validate_candidates import validate  # noqa: E402


class DiscoveryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.original = json.loads((ROOT / "research" / "candidates.json").read_text(encoding="utf-8"))

    def test_valid_registry_and_no_ground_truth(self):
        result = validate(self.original)
        self.assertGreaterEqual(result["candidates"], 10)
        self.assertEqual(result["ground_truth_labels"], 0)
        self.assertEqual(result["independently_evaluated"], 0)

    def test_duplicate_is_rejected(self):
        copied = copy.deepcopy(self.original)
        copied["candidates"].append(copy.deepcopy(copied["candidates"][0]))
        with self.assertRaisesRegex(ValueError, "Duplicate"):
            validate(copied)

    def test_fabricated_ground_truth_is_rejected(self):
        copied = copy.deepcopy(self.original)
        copied["candidates"][0]["ground_truth"] = "WRONG_PYTHON_INTERPRETER"
        with self.assertRaises(ValueError):
            validate(copied)

    def test_unreviewed_cannot_be_called_adjudicated(self):
        copied = copy.deepcopy(self.original)
        copied["independent_adjudicated_labels"] = 1
        with self.assertRaises(ValueError):
            validate(copied)

    def test_url_and_repo_must_match(self):
        copied = copy.deepcopy(self.original)
        copied["candidates"][0]["repo"] = "not/the-real-repository"
        with self.assertRaises(ValueError):
            validate(copied)

    def test_no_unreviewed_prediction(self):
        copied = copy.deepcopy(self.original)
        copied["candidates"][0]["envguard_prediction"] = "PYTHON_IMPORT_FAILURE"
        with self.assertRaises(ValueError):
            validate(copied)


if __name__ == "__main__":
    unittest.main()
