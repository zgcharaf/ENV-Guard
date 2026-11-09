"""Conservative target-platform assessment for comparing CI snapshots.

A comparable target is a necessary condition for direct runtime comparisons,
not a claim of equivalent packages or identical build artifacts.
"""
from __future__ import annotations

from typing import Any

from .model import validate_snapshot


def _minor(snapshot: dict[str, Any]) -> str | None:
    version = snapshot["runtime"].get("version")
    if not isinstance(version, str):
        return None
    parts = version.split(".")
    if len(parts) < 2 or not all(part.isdigit() for part in parts[:2]):
        return None
    return ".".join(parts[:2])


def assess_targets(baseline: dict[str, Any], current: dict[str, Any]) -> dict[str, Any]:
    validate_snapshot(baseline)
    validate_snapshot(current)
    dimensions = {
        "os": (baseline["platform"].get("os"), current["platform"].get("os")),
        "arch": (baseline["platform"].get("arch"), current["platform"].get("arch")),
        "python_implementation": (baseline["runtime"].get("implementation"),
                                  current["runtime"].get("implementation")),
        "python_minor": (_minor(baseline), _minor(current)),
        "soabi": (baseline["runtime"].get("soabi"), current["runtime"].get("soabi")),
    }
    differences = [key for key, (old, new) in dimensions.items()
                   if isinstance(old, str) and isinstance(new, str) and old and new and old != new]
    unknown = [key for key, (old, new) in dimensions.items()
               if not (isinstance(old, str) and old and isinstance(new, str) and new)]
    # SOABI can legitimately be null for alternative implementations; do not
    # require it for basic platform comparability, but disclose the gap.
    critical_unknown = [x for x in unknown if x != "soabi"]
    status = ("different_target" if differences else
              "insufficient_metadata" if critical_unknown else "comparable")
    return {
        "status": status,
        "dimensions_differing": differences,
        "dimensions_unknown": unknown,
        "note": "Target match is not proof of environmental equivalence; "
                "cross-target dependency drift may be expected.",
    }
