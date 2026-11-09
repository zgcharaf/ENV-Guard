from __future__ import annotations

import copy
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.model import (SnapshotError, canonical_name, digest, fingerprint,
                            read_snapshot, validate_snapshot)

ROOT = Path(__file__).parent / "fixtures"


class ModelTest(unittest.TestCase):
    def test_normalize_pep503(self):
        self.assertEqual(canonical_name("My__Package.Name"), "my-package-name")

    def test_stable_digest(self):
        self.assertEqual(digest({"a": 1, "b": [3, 2]}), digest({"b": [3, 2], "a": 1}))
        self.assertNotEqual(digest({"b": [3, 2]}), digest({"b": [2, 3]}))

    def test_nondeterministic_capture_time_excluded(self):
        baseline = read_snapshot(ROOT / "baseline.json")
        changed = copy.deepcopy(baseline)
        changed["captured_at"] = "2028-09-01T00:00:00Z"
        changed["packages"].reverse()
        changed["project"]["files"].reverse()
        self.assertEqual(fingerprint(baseline), fingerprint(changed))

    def test_spec_and_runtime_hashes_are_independent(self):
        baseline = read_snapshot(ROOT / "baseline.json")
        changed = copy.deepcopy(baseline)
        changed["runtime"]["version"] = "3.13.2"
        self.assertEqual(fingerprint(baseline)["spec"], fingerprint(changed)["spec"])
        self.assertNotEqual(fingerprint(baseline)["runtime"], fingerprint(changed)["runtime"])

    def test_artifact_hash_unknown(self):
        self.assertIsNone(fingerprint(read_snapshot(ROOT / "baseline.json"))["artifact"])

    def test_reject_invalid_manifest(self):
        baseline = read_snapshot(ROOT / "baseline.json")
        bad = copy.deepcopy(baseline)
        bad["packages"].append(copy.deepcopy(bad["packages"][0]))
        with self.assertRaises(SnapshotError):
            validate_snapshot(bad)
        bad["schema_version"] = "5.0"
        with self.assertRaises(SnapshotError):
            validate_snapshot(bad)

    def test_json_io(self):
        sample = read_snapshot(ROOT / "baseline.json")
        with tempfile.TemporaryDirectory() as tmp:
            file = Path(tmp) / "fixture.json"
            file.write_text(json.dumps(sample), encoding="utf-8")
            self.assertEqual(read_snapshot(file), sample)
