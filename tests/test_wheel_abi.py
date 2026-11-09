"""Static wheel ABI inspection tests: no downloaded wheels or third-party execution."""
from __future__ import annotations

import base64
import hashlib
import io
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch
import zipfile

from envguard_ci.cli import main
from envguard_ci.wheel_abi import (
    WheelABIError, _version_needs, _version_definitions, _compare_abi,
    inspect_wheel_abi, capture_native_target,
)

HEADER = """ELF Header:
  Class: ELF64
  Machine: Advanced Micro Devices X86-64
"""
DYNAMIC = """Dynamic section:
 0x0000000000000001 (NEEDED) Shared library: [libstdc++.so.6]
 0x0000000000000001 (NEEDED) Shared library: [libc.so.6]
"""
VERSIONS = """Version symbols section '.gnu.version' contains 10 entries:
 0x000: 0 (*local*)   2 (GLIBCXX_3.4.32)  3 (GLIBC_2.2.5)
Version needs section '.gnu.version_r' contains 2 entries:
 0x0010: Version: 1  File: libstdc++.so.6  Cnt: 2
 0x0020:   Name: GLIBCXX_3.4.32  Flags: none
 0x0030:   Name: CXXABI_1.3.9  Flags: none
 0x0040: Version: 1  File: libc.so.6  Cnt: 1
 0x0050:   Name: GLIBC_2.2.5  Flags: none
Version definition section '.gnu.version_d' contains 1 entry:
 0x0050: Name: GLIBCXX_9.9.9
"""
DEFINITIONS = """Version symbols section '.gnu.version' contains 17 entries:
Version definition section '.gnu.version_d' contains 2 entries:
 0x01: Name: libstdc++.so.6
 0x02: Name: GLIBCXX_3.4.30
 0x03: Name: CXXABI_1.3.9
Version needs section '.gnu.version_r' contains 1 entry:
 0x04: Version: 1 File: libc.so.6 Cnt: 1
 0x05: Name: GLIBC_2.34
"""


def make_wheel(folder: Path, *, data: bytes = b"\x7fELF" + b"0" * 128,
               member: str = "abimock/libdummy.so") -> Path:
    path = folder / "abimock-1.0.0-py3-none-manylinux_2_28_x86_64.whl"
    entries = {
        member: data,
        "abimock/__init__.py": b"",
        "abimock-1.0.0.dist-info/METADATA": b"Metadata-Version: 2.1\nName: abimock\nVersion: 1.0.0\n",
        "abimock-1.0.0.dist-info/WHEEL": b"Wheel-Version: 1.0\nGenerator: unittest\nRoot-Is-Purelib: false\nTag: py3-none-manylinux_2_28_x86_64\n",
    }
    lines = []
    for name, contents in entries.items():
        encoded = base64.urlsafe_b64encode(hashlib.sha256(contents).digest()).rstrip(b"=").decode()
        lines.append(f"{name},sha256={encoded},{len(contents)}")
    record = "abimock-1.0.0.dist-info/RECORD"
    lines.append(f"{record},,")
    entries[record] = ("\n".join(lines) + "\n").encode("utf-8")
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
        for name, contents in entries.items():
            z.writestr(name, contents)
    return path


def manifest(folder: Path, *, arch: str = "x86_64", versions: list[str] | None = None) -> Path:
    path = folder / "target.json"
    data = {
        "schema_version": "1.0", "kind": "native_symbol_provider_manifest",
        "architecture": arch, "source": "synthetic_unittest_fixture",
        "providers": {
            "libstdc++.so.6": {"provided_versions": versions or ["GLIBCXX_3.4.30", "CXXABI_1.3.9"]},
            "libc.so.6": {"provided_versions": ["GLIBC_2.2.5"]},
        },
    }
    path.write_text(json.dumps(data), encoding="utf-8")
    return path


def fake_readelf(arguments: list[str], timeout: int = 25) -> str:
    if "--file-header" in arguments:
        return HEADER
    if "--dynamic" in arguments:
        return DYNAMIC
    if "--version-info" in arguments:
        return VERSIONS
    raise AssertionError(arguments)


class ABIParserTests(unittest.TestCase):
    def test_separates_needs_from_definitions(self):
        observed = _version_needs(VERSIONS)
        self.assertEqual(observed["libstdc++.so.6"], ["CXXABI_1.3.9", "GLIBCXX_3.4.32"])
        self.assertEqual(observed["libc.so.6"], ["GLIBC_2.2.5"])
        self.assertNotIn("GLIBCXX_9.9.9", str(observed))

    def test_definition_parser_does_not_count_dependencies_as_exports(self):
        self.assertEqual(_version_definitions(DEFINITIONS), ["CXXABI_1.3.9", "GLIBCXX_3.4.30"])

    def test_unobserved_provider_not_declared_good(self):
        observed = [{"member": "x.so", "elf_architecture": "x86_64",
                     "required_versions_by_provider": {"libnonexistent.so": ["GLIBCXX_3.4.32"]}}]
        target = {"architecture": "x86_64", "providers": {}}
        comparison = _compare_abi(observed, target)
        self.assertEqual(comparison["status"], "no_observed_gap_with_unknowns")
        self.assertEqual(len(comparison["unknowns"]), 1)

    def test_architecture_mismatch_is_unknown(self):
        observed = [{"member": "x.so", "elf_architecture": "aarch64",
                     "required_versions_by_provider": {"libstdc++.so.6": ["GLIBCXX_3.4.32"]}}]
        target = {"architecture": "x86_64", "providers": {"libstdc++.so.6": {
            "provided_versions": ["GLIBCXX_3.4.30"]}}}
        self.assertEqual(_compare_abi(observed, target)["status"], "no_observed_gap_with_unknowns")


class ABIWheelTests(unittest.TestCase):
    def test_static_scan_and_exact_symbol_shortfall(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wheel = make_wheel(root)
            target = manifest(root)
            with patch("envguard_ci.wheel_abi._tool", return_value="readelf"), \
                 patch("envguard_ci.wheel_abi._run_tool", side_effect=fake_readelf):
                report = inspect_wheel_abi(str(wheel), target_manifest=str(target))
            self.assertEqual(report["status"], "static_elf_scanned")
            self.assertEqual(report["comparison"]["status"], "potential_provider_symbol_gap")
            self.assertEqual(report["comparison"]["shortfalls"][0]["required_but_not_observed"],
                             ["GLIBCXX_3.4.32"])
            self.assertFalse(report["objects"][0]["executed_or_loaded"])
            self.assertIn("libstdc++.so.6", report["objects"][0]["needed_libraries"])

    def test_exact_match_does_not_claim_compatibility(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wheel = make_wheel(root)
            target = manifest(root, versions=["GLIBCXX_3.4.32", "CXXABI_1.3.9"])
            with patch("envguard_ci.wheel_abi._tool", return_value="readelf"), \
                 patch("envguard_ci.wheel_abi._run_tool", side_effect=fake_readelf):
                report = inspect_wheel_abi(str(wheel), target_manifest=str(target))
            self.assertEqual(report["comparison"]["status"], "no_observed_gap_for_checked_symbols")
            self.assertIn("not a guarantee", " ".join(report["limitations"]))

    def test_no_target_does_not_infer_compatibility(self):
        with tempfile.TemporaryDirectory() as temp:
            with patch("envguard_ci.wheel_abi._tool", return_value="readelf"), \
                 patch("envguard_ci.wheel_abi._run_tool", side_effect=fake_readelf):
                r = inspect_wheel_abi(str(make_wheel(Path(temp))))
            self.assertEqual(r["comparison"]["status"], "target_not_provided")

    def test_invalid_elf_magic_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            wheel = make_wheel(Path(temp), data=b"not-elf" + b"1" * 20)
            with patch("envguard_ci.wheel_abi._tool", return_value="readelf"):
                with self.assertRaises(WheelABIError):
                    inspect_wheel_abi(str(wheel))

    def test_rejects_mismatching_approved_wheel_hash(self):
        with tempfile.TemporaryDirectory() as temp:
            wheel = make_wheel(Path(temp))
            with self.assertRaises(WheelABIError):
                inspect_wheel_abi(str(wheel), approved_sha256="0" * 64)

    def test_bad_manifest_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wheel = make_wheel(root)
            target = manifest(root)
            data = json.loads(target.read_text(encoding="utf-8"))
            data["providers"]["libstdc++.so.6"]["provided_versions"] = ["NOT_A_REAL_VERSION"]
            target.write_text(json.dumps(data), encoding="utf-8")
            with patch("envguard_ci.wheel_abi._tool", return_value="readelf"), \
                 patch("envguard_ci.wheel_abi._run_tool", side_effect=fake_readelf):
                with self.assertRaises(WheelABIError):
                    inspect_wheel_abi(str(wheel), target_manifest=str(target))

    def test_pure_python_has_no_elf(self):
        with tempfile.TemporaryDirectory() as temp:
            wheel = make_wheel(Path(temp), member="abimock/not-native.txt")
            report = inspect_wheel_abi(str(wheel))
            self.assertEqual(report["status"], "no_elf_members")
            self.assertEqual(report["objects"], [])

    def test_cli_shortfall_exit_policy(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            wheel = make_wheel(root)
            target = manifest(root)
            output = root / "report.json"
            with patch("envguard_ci.wheel_abi._tool", return_value="readelf"), \
                 patch("envguard_ci.wheel_abi._run_tool", side_effect=fake_readelf):
                rc = main(["inspect-wheel-abi", "--wheel", str(wheel),
                           "--target-manifest", str(target),
                           "--fail-on-shortfall", "--out", str(output)])
            self.assertEqual(rc, 1)
            self.assertEqual(json.loads(output.read_text(encoding="utf-8"))
                             ["comparison"]["status"], "potential_provider_symbol_gap")

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("readelf") and shutil.which("gcc"),
                         "Linux binutils and compiler required")
    def test_live_compiled_local_elf(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            c = root / "native.c"
            c.write_text("int answer(void) { return 42; }\n", encoding="utf-8")
            lib = root / "native.so"
            subprocess.run(["gcc", "-fPIC", "-shared", str(c), "-o", str(lib)],
                           timeout=30, check=True)
            wheel = make_wheel(root, data=lib.read_bytes())
            report = inspect_wheel_abi(str(wheel))
            self.assertEqual(report["status"], "static_elf_scanned")
            self.assertEqual(report["objects"][0]["elf_architecture"], "x86_64")
            self.assertFalse(report["objects"][0]["executed_or_loaded"])

    @unittest.skipUnless(sys.platform == "linux" and shutil.which("readelf") and shutil.which("ldconfig"),
                         "Linux binutils and ldconfig required")
    def test_target_capture_nonempty_and_version_bounded(self):
        data = capture_native_target()
        self.assertEqual(data["kind"], "native_symbol_provider_manifest")
        self.assertIn("libc.so.6", data["providers"])
        self.assertTrue(data["providers"]["libc.so.6"]["provided_versions"])
        self.assertIn("architecture", data)


if __name__ == "__main__":
    unittest.main()
