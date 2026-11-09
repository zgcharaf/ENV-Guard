"""Unit checks for the safe, static public ARM64 ABI experiment."""
from __future__ import annotations

from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from research.validate_native_abi import validate_published_ledger
from research.replay_native_abi import (
    WHEEL_TEMPLATE, VERSIONS, versions_in_readelf, request_release_metadata,
)


class NativeAbiStudyTests(unittest.TestCase):
    def test_parse_required_symbol_versions(self):
        sample = """Version needs section '.gnu.version_r' contains 2 entries:
          File: libstdc++.so.6 Cnt: 3
          Name: GLIBCXX_3.4.22 Flags: none
          Name: CXXABI_1.3.8 Flags: none
          Name: GLIBCXX_3.4.32 Flags: none
        """
        self.assertEqual(versions_in_readelf(sample), [(3, 4, 22), (3, 4, 32)])

    def test_empty_output_means_no_observed_requirements(self):
        self.assertEqual(versions_in_readelf("Version needs section not found"), [])

    def test_versions_strictly_pinned(self):
        self.assertEqual(VERSIONS, ("3.8.0", "3.8.2"))
        self.assertEqual(
            WHEEL_TEMPLATE.format(version="3.8.0"),
            "casadi-3.8.0-cp310-none-manylinux_2_28_aarch64.whl",
        )

    def test_known_issue_evidence_cannot_be_held_out(self):
        record = validate_published_ledger()
        self.assertFalse(record["holdout_eligible"])
        self.assertTrue(record["permanent_evidence_valid"])

    def test_unknown_version_rejected_before_network(self):
        with self.assertRaises(ValueError):
            request_release_metadata("latest")


if __name__ == "__main__":
    unittest.main()
