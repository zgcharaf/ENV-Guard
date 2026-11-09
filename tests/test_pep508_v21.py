"""PEP 508 correctness, optional extras and project-scope regressions."""
from __future__ import annotations

import copy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))
from envguard_ci.graph import graph
from envguard_ci.diagnostics import doctor
from envguard_ci.model import fingerprint, read_snapshot
from envguard_ci.project import inspect_project
from envguard_ci.requirements import target_marker_environment
from envguard_ci.cli import main

BASE = Path(__file__).parent / "fixtures" / "baseline.json"


def example():
    s = copy.deepcopy(read_snapshot(BASE))
    s["project"]["name"] = "sample"
    s["project"]["dependencies"] = ["requests[socks]>=2", "numpy>=2"]
    s["project"]["optional_dependencies"] = {"dashboard": ["bokeh>=3"], "docs": ["furo"]}
    s["packages"][1]["requires"] = ["urllib3>=1.21", "pysocks; extra == 'socks'", "speedups; extra == 'speed'"]
    s["packages"].append({"name": "pysocks", "version": "1.7.1", "requires": [], "wheel_tags": []})
    s["packages"] = sorted(s["packages"], key=lambda x: x["name"])
    s["runtime"]["marker_environment"] = {
        "implementation_name": "cpython", "implementation_version": "3.12.7",
        "os_name": "posix", "platform_machine": "x86_64",
        "platform_python_implementation": "CPython", "platform_release": "6.1.0",
        "platform_system": "Linux", "platform_version": "linux-kernel",
        "python_full_version": "3.12.7", "python_version": "3.12", "sys_platform": "linux"
    }
    s["fingerprints"] = fingerprint(s)
    return s


class PEP508Test(unittest.TestCase):
    def test_selected_transitive_extra_activates_requirements(self):
        s = example()
        result = graph(s)
        targets = {(e["from"], e["to"]): e for e in result["edges"]}
        self.assertEqual(targets[("requests", "pysocks")]["status"], "required_satisfied")
        self.assertEqual(targets[("requests", "speedups")]["status"], "optional_unselected")
        self.assertNotIn("speedups", [f["code"] for f in doctor(s)["findings"]])

    def test_extra_not_selected_does_not_invent_missing_package(self):
        s = example()
        result = graph(s)
        self.assertEqual(next(e for e in result["edges"] if e["to"] == "bokeh")["status"], "optional_unselected")
        self.assertEqual(result["stats"]["required_missing"], 0)
        self.assertEqual(doctor(s)["findings"], [])

    def test_select_project_extra_reports_real_missing_dependency(self):
        s = example()
        result = graph(s, extras=["dashboard"])
        self.assertEqual(next(e for e in result["edges"] if e["to"] == "bokeh")["status"], "required_missing")
        self.assertIn("UNSATISFIED_RUNTIME_DEPENDENCY", [f["code"] for f in doctor(s, extras=["dashboard"])["findings"]])

    def test_missing_transitively_selected_extra_is_real(self):
        s = example()
        s["packages"] = [p for p in s["packages"] if p["name"] != "pysocks"]
        s["fingerprints"] = fingerprint(s)
        self.assertEqual(graph(s)["stats"]["required_missing"], 1)
        self.assertIn("UNSATISFIED_RUNTIME_DEPENDENCY", [f["code"] for f in doctor(s)["findings"]])

    def test_target_marker_not_current_host(self):
        s = example()
        s["packages"][0]["requires"] = ["winonly; sys_platform == 'win32'"]
        s["fingerprints"] = fingerprint(s)
        linux_result = graph(s)
        self.assertEqual(next(e for e in linux_result["edges"] if e["to"] == "winonly")["status"], "marker_excluded")
        s["runtime"]["marker_environment"].update(sys_platform="win32", os_name="nt", platform_system="Windows")
        s["platform"]["os"] = "windows"
        s["fingerprints"] = fingerprint(s)
        windows_result = graph(s)
        self.assertEqual(next(e for e in windows_result["edges"] if e["to"] == "winonly")["status"], "required_missing")

    def test_python_marker_is_evaluated(self):
        s = example()
        s["packages"][0]["requires"] = ["need312; python_version >= '3.12'", "oldonly; python_version < '3.10'"]
        s["fingerprints"] = fingerprint(s)
        g = graph(s)
        self.assertEqual(next(e for e in g["edges"] if e["to"] == "need312")["status"], "required_missing")
        self.assertEqual(next(e for e in g["edges"] if e["to"] == "oldonly")["status"], "marker_excluded")

    def test_pep440_complex_specifiers(self):
        s = example()
        s["project"]["dependencies"] = ["numpy~=1.20", "requests!=2.32.3"]
        s["fingerprints"] = fingerprint(s)
        result = graph(s)
        self.assertEqual(result["stats"]["required_incompatible"], 2)

    def test_partial_legacy_marker_unknown_not_broken(self):
        s = example()
        s["runtime"].pop("marker_environment")
        s["packages"][0]["requires"] = ["special; platform_release >= '6.0'"]
        s["fingerprints"] = fingerprint(s)
        edge = next(e for e in graph(s)["edges"] if e["to"] == "special")
        self.assertEqual(edge["status"], "unknown")
        self.assertEqual(graph(s)["stats"]["required_missing"], 0)

    def test_unknown_direct_reference_is_redacted(self):
        s = example()
        s["project"]["dependencies"] = ["privatepkg @ https://username:secret@example.com/pkg.whl"]
        s["fingerprints"] = fingerprint(s)
        g = graph(s)
        self.assertNotIn("username", json.dumps(g))
        self.assertNotIn("secret", json.dumps(g))
        self.assertEqual(next(e for e in g["edges"] if e["to"] == "privatepkg")["status"], "unknown")

    def test_scope_project_excludes_unrelated_installed_packages(self):
        s = example()
        s["packages"].append({"name": "jupyter", "version": "1.0", "requires": ["absent"], "wheel_tags": []})
        s["fingerprints"] = fingerprint(s)
        project = graph(s)
        environment = graph(s, scope="environment")
        self.assertNotIn("jupyter", {e["from"] for e in project["edges"]})
        self.assertIn("jupyter", {e["from"] for e in environment["edges"]})
        self.assertEqual(project["stats"]["required_missing"], 0)
        self.assertEqual(environment["stats"]["required_missing"], 1)

    def test_focus_one_package(self):
        s = example()
        result = graph(s, focus="requests")
        self.assertEqual(result["scope"], "focus")
        self.assertEqual({e["from"] for e in result["edges"]}, {"requests"})
        focused = graph(s, focus="requests", extras=["speed"])
        self.assertEqual(next(e for e in focused["edges"] if e["to"] == "speedups")["status"], "required_missing")

    def test_unselected_project_extra_is_not_required_in_environment_scope(self):
        self.assertEqual(graph(example(), scope="environment")["stats"]["required_missing"], 0)

    def test_deep_extra_propagation_with_cycle(self):
        s = example()
        s["project"]["dependencies"] = ["first[test]"]
        s["packages"].append({"name": "first", "version": "1.0", "requires": ["second[dev]; extra == 'test'"], "wheel_tags": []})
        s["packages"].append({"name": "second", "version": "1.0", "requires": ["first[docs]", "third; extra == 'dev'"], "wheel_tags": []})
        s["packages"] = sorted(s["packages"], key=lambda x: x["name"])
        s["fingerprints"] = fingerprint(s)
        g = graph(s)
        self.assertEqual(next(e for e in g["edges"] if e["to"] == "third")["status"], "required_missing")
        self.assertLess(len(g["edges"]), 100)

    def test_project_metadata_optional_groups(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text('''[project]\nname = "my-lab"\nversion = "0.1"\ndependencies = ["requests>=2"]\n[project.optional-dependencies]\ntest = ["pytest>=8"]\n''')
            result = inspect_project(root)
            self.assertEqual(result["optional_dependencies"]["test"], ["pytest>=8"])
            self.assertEqual(result["name"], "my-lab")

    def test_graph_cli_scope_and_focus(self):
        s = example()
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "snap.json"
            path.write_text(json.dumps(s))
            out = Path(tmp) / "graph.json"
            self.assertEqual(main(["graph", "--snapshot", str(path), "--scope", "environment", "--format", "json", "--out", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text())["scope"], "environment")
            self.assertEqual(main(["graph", "--snapshot", str(path), "--focus", "requests", "--format", "json", "--out", str(out)]), 0)
            self.assertEqual(json.loads(out.read_text())["scope"], "focus")

    def test_unsupported_extra_explains_error(self):
        with self.assertRaisesRegex(ValueError, "Unknown project extra"):
            graph(example(), extras=["made-up"])


if __name__ == "__main__":
    unittest.main()
