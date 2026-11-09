"""Build valid small platform-independent wheels using only Python's stdlib.

Avoids a PyPI build backend so the laboratory works without network access.
Files are regular, installable wheel archives with hashes in RECORD.
"""
from __future__ import annotations
import base64
import csv
import hashlib
import io
import pathlib
import zipfile

ROOT = pathlib.Path(__file__).resolve().parents[1]
PACKAGES = ROOT / "packages"


def make_wheel(project: pathlib.Path, output: pathlib.Path) -> pathlib.Path:
    package, version = project.name.rsplit("-", 1)
    dist = f"{package}-{version}"
    metadata = (f"Metadata-Version: 2.1\nName: {package}\nVersion: {version}\n"
                + ("Requires-Dist: scorecodec (>=1.0,<2.0)\n" if package == "riskbatch" else ""))
    wheel = "Wheel-Version: 1.0\nGenerator: envguard-lab\nRoot-Is-Purelib: true\nTag: py3-none-any\n"
    content: dict[str, bytes] = {}
    for file in sorted((project / package).rglob("*.py")):
        content[str(file.relative_to(project)).replace("\\", "/")] = file.read_bytes()
    content[f"{dist}.dist-info/METADATA"] = metadata.encode()
    content[f"{dist}.dist-info/WHEEL"] = wheel.encode()
    record = f"{dist}.dist-info/RECORD"
    rows = []
    for name, data in sorted(content.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
        rows.append([name, f"sha256={digest}", str(len(data))])
    rows.append([record, "", ""])
    buffer = io.StringIO(newline="")
    writer = csv.writer(buffer, lineterminator="\n")
    writer.writerows(rows)
    content[record] = buffer.getvalue().encode()
    output.mkdir(parents=True, exist_ok=True)
    destination = output / f"{dist}-py3-none-any.whl"
    with zipfile.ZipFile(destination, "w", compression=zipfile.ZIP_DEFLATED) as whl:
        for path, data in sorted(content.items()):
            whl.writestr(path, data)
    return destination


def build_all(output: pathlib.Path) -> list[pathlib.Path]:
    return [make_wheel(p, output) for p in sorted(PACKAGES.iterdir()) if p.is_dir()]


if __name__ == "__main__":
    for built in build_all(ROOT / ".envguard-runs" / "wheels"):
        print(built)
