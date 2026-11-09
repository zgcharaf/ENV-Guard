"""Offline, read-only Python wheel integrity and provenance inspection.

SHA-256 is identity, not a security attestation. No wheel code is imported or
executed. ZIP RECORD hashes are checked, with explicit unknown outcomes.
"""
from __future__ import annotations

import base64
import csv
import hashlib
import io
import re
import zipfile
from pathlib import Path
from typing import Any

from packaging.tags import sys_tags
from packaging.utils import InvalidWheelFilename, parse_wheel_filename

MAX_WHEEL_BYTES = 350_000_000
MAX_UNCOMPRESSED = 900_000_000
MAX_FILES = 15000


class ArtifactError(ValueError):
    pass


def inspect_wheel(path: str, *, approved_sha256: str | None = None,
                  check_host_tags: bool = True) -> dict[str, Any]:
    wheel = Path(path)
    if not wheel.is_file() or not wheel.name.lower().endswith('.whl'):
        raise ArtifactError("Expected an existing .whl artifact")
    if wheel.stat().st_size > MAX_WHEEL_BYTES:
        raise ArtifactError("Wheel exceeds 350 MB inspection limit")
    try:
        name, version, build, tags = parse_wheel_filename(wheel.name)
    except InvalidWheelFilename:
        raise ArtifactError("Wheel filename does not follow wheel naming convention") from None
    digest = hashlib.sha256()
    with wheel.open('rb') as fp:
        while data := fp.read(1024 * 1024):
            digest.update(data)
    actual = digest.hexdigest()
    if approved_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", approved_sha256):
        raise ArtifactError("--approved-sha256 must contain 64 hexadecimal characters")
    file_errors: list[str] = []
    checked = 0
    unknown = 0
    natives: list[str] = []
    try:
        with zipfile.ZipFile(wheel) as z:
            members = z.infolist()
            if len(members) > MAX_FILES or sum(x.file_size for x in members) > MAX_UNCOMPRESSED:
                raise ArtifactError("Wheel archive exceeds inspection safety limits")
            entries = {item.filename: item for item in members}
            if len(entries) != len(members):
                raise ArtifactError("Wheel contains duplicate ZIP entries")
            for item in members:
                if (item.filename.startswith('/') or '\\' in item.filename or
                    any(x in ('', '.', '..') for x in item.filename.split('/'))):
                    raise ArtifactError("Wheel contains unsafe ZIP member names")
                if item.filename.lower().endswith(('.so', '.pyd', '.dll', '.dylib')):
                    natives.append(item.filename)
            records = [x for x in entries if x.endswith('.dist-info/RECORD')]
            if len(records) != 1:
                raise ArtifactError("Wheel must contain one .dist-info/RECORD")
            record_bytes = z.read(records[0])
            if len(record_bytes) > 12_000_000:
                raise ArtifactError("Wheel RECORD exceeds inspection limit")
            recorded = set()
            for record_path, encoded_hash, size in csv.reader(io.StringIO(record_bytes.decode('utf-8'))):
                if record_path in recorded:
                    file_errors.append('duplicate RECORD entry')
                    continue
                recorded.add(record_path)
                if record_path not in entries:
                    file_errors.append('RECORD references missing file')
                    continue
                if not encoded_hash:
                    unknown += 1
                    continue
                algorithm, sep, expected = encoded_hash.partition('=')
                if not sep or algorithm != 'sha256':
                    unknown += 1
                    continue
                if size and str(entries[record_path].file_size) != size:
                    file_errors.append('RECORD file size mismatch')
                hasher = hashlib.sha256()
                with z.open(record_path) as content:
                    while chunk := content.read(1024 * 1024):
                        hasher.update(chunk)
                computed = base64.urlsafe_b64encode(hasher.digest()).rstrip(b'=').decode()
                if computed != expected:
                    file_errors.append('RECORD sha256 mismatch')
                else:
                    checked += 1
            if set(entries) - recorded:
                file_errors.append('Unlisted members absent from RECORD')
    except (zipfile.BadZipFile, UnicodeError, csv.Error, OSError) as exc:
        raise ArtifactError(f"Could not inspect wheel ({type(exc).__name__})") from None
    host = bool(tags.intersection(set(sys_tags()))) if check_host_tags else None
    passed = not file_errors and (approved_sha256 is None or actual == approved_sha256.lower())
    return {
        "schema_version": "1.0", "kind": "wheel_identity_and_integrity",
        "wheel_name": wheel.name, "distribution": str(name), "version": str(version),
        "sha256": actual, "bytes": wheel.stat().st_size,
        "approved_hash_match": actual == approved_sha256.lower() if approved_sha256 else None,
        "record_sha256_verified": checked, "record_unverified": unknown,
        "record_errors": file_errors[:15], "native_members": natives[:100],
        "host_interpreter_wheel_tag_compatible": host,
        "status": "verified_integrity" if passed else "integrity_failure",
        "limitations": [
            "A hash and RECORD checks prove file identity/integrity, not publisher trust or runtime behavior.",
            "Host wheel tags do not establish compatibility with another CI/deployment interpreter.",
            "Native shared-library resolution and dynamic imports require target-runtime execution."
        ]
    }
