from __future__ import annotations

import copy
import sys
import unittest
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.graph import graph
from envguard_ci.model import read_snapshot, sanitize_requirement

class GraphTest(unittest.TestCase):
    def test_project_and_installed_dependencies(self):
        sample = read_snapshot(Path(__file__).parent / "fixtures" / "baseline.json")
        result = graph(sample)
        self.assertIn(("$project", "requests"), [(e["from"], e["to"]) for e in result["edges"]])
        self.assertIn(("requests", "urllib3"), [(e["from"], e["to"]) for e in result["edges"]])
        self.assertEqual(result["stats"]["referenced_but_not_installed"], 0)

    def test_uninstalled_conditional_is_not_hard_failure(self):
        sample = read_snapshot(Path(__file__).parent / "fixtures" / "baseline.json")
        sample["packages"][0]["requires"] = ["optional-lib; python_version < '3.0'"]
        result = graph(sample)
        self.assertTrue(any(e["conditional_or_unresolved"] for e in result["edges"]))

    def test_direct_reference_redacts_credentials(self):
        text = "mypackage @ https://me:private-token@internal.example.com/wheel.whl#secret=1"
        safe = sanitize_requirement(text)
        self.assertEqual(safe, "mypackage @ [redacted-url]")
        self.assertNotIn("private-token", safe)
