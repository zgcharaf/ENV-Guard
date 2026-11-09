"""Scoped, PEP 508-aware installed-distribution graph (not a resolver).

Graph traversal starts at a project's declared dependencies, at a named
installed distribution, or all installed distributions. Requested extras
propagate transitively. Skipped optional/marker edges are retained as evidence
but hidden by default by the CLI. No package is imported or installed.
"""
from __future__ import annotations

from collections import defaultdict, deque
import re
from typing import Any, Iterable

from .model import canonical_name, sanitize_requirement, validate_snapshot
from .requirements import (
    marker_state, safe_requirement, target_marker_environment, version_satisfies,
)

_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9][A-Za-z0-9._-]*)")
_ACTIVE = frozenset({"required_satisfied", "required_missing", "required_incompatible", "required_unverifiable"})


def graph(snapshot: dict[str, Any], *, scope: str = "project", focus: str | None = None,
          extras: Iterable[str] = ()) -> dict[str, Any]:
    validate_snapshot(snapshot)
    if scope not in {"project", "environment"}:
        raise ValueError("Graph scope must be 'project' or 'environment'")
    installed = {canonical_name(p["name"]): p for p in snapshot["packages"]}
    project = snapshot["project"]
    target = target_marker_environment(snapshot)
    selected = {canonical_name(s) for s in extras}
    optional_groups = {canonical_name(k): v for k, v in
                       (project.get("optional_dependencies") or {}).items()}
    if not focus and selected - set(optional_groups):
        raise ValueError("Unknown project extra(s): " + ", ".join(sorted(selected - set(optional_groups))))

    active_extras: dict[str, set[str]] = defaultdict(set)
    if focus:
        entry = "$project" if focus in {"$project", "project"} else canonical_name(focus)
        if entry != "$project" and entry not in installed:
            raise ValueError(f"Focused distribution not installed: {focus}")
        if entry != "$project":
            active_extras[entry].update(selected)
        roots = [entry]
        effective_scope = "focus"
    elif scope == "environment":
        roots = ["$project", *sorted(installed)]
        effective_scope = "environment"
    else:
        roots = ["$project"]
        effective_scope = "project"

    queue = deque(roots)
    last_processed: dict[str, frozenset[str]] = {}
    traversed: set[str] = set()
    result_edges: dict[tuple[str, str, str, str | None], dict[str, Any]] = {}

    while queue:
        parent = queue.popleft()
        current_extras = frozenset(active_extras[parent])
        if parent in last_processed and last_processed[parent] == current_extras:
            continue
        last_processed[parent] = current_extras
        traversed.add(parent)
        dependencies: list[tuple[str, str | None]]
        if parent == "$project":
            dependencies = [(r, None) for r in project.get("dependencies") or []]
            for group in sorted(optional_groups):
                dependencies.extend((r, group) for r in optional_groups[group])
        else:
            dependencies = [(r, None) for r in installed[parent].get("requires") or []]
        for raw, group in dependencies:
            if not isinstance(raw, str):
                continue
            req, safe = safe_requirement(raw)
            name_match = _REQ_NAME.match(safe)
            child = canonical_name(req.name if req is not None else name_match.group(1)) if (req or name_match) else None
            if not child:
                continue
            requested = sorted(canonical_name(x) for x in req.extras) if req else []
            # An optional [project] dependency becomes active only if selected.
            state = ("optional_unselected" if parent == "$project" and group and group not in selected
                     else marker_state(req.marker, target, current_extras) if req
                     else "unknown")
            installed_pkg = installed.get(child)
            satisfiable = version_satisfies(req, installed_pkg["version"]) if req and installed_pkg else None
            if state == "active":
                if not installed_pkg:
                    state = "required_missing"
                elif satisfiable is False:
                    state = "required_incompatible"
                elif satisfiable is None:
                    state = "required_unverifiable"
                else:
                    state = "required_satisfied"
            key = (parent, child, safe, group)
            result_edges[key] = {
                "from": parent,
                "to": child,
                "requirement": safe,
                "source_extra": group,
                "requested_extras": requested,
                "status": state,
                "conditional_or_unresolved": state not in _ACTIVE,
                "installed": child in installed,
                "installed_version": installed_pkg["version"] if installed_pkg else None,
            }
            if state in _ACTIVE and child in installed:
                additional = set(requested) - active_extras[child]
                if additional:
                    active_extras[child].update(additional)
                if child not in last_processed or additional:
                    queue.append(child)

    edges = sorted(result_edges.values(), key=lambda v: (v["from"], v["to"], v["requirement"], v["source_extra"] or ""))
    missing = {edge["to"] for edge in edges if edge["status"] == "required_missing"}
    incompatible = {edge["to"] for edge in edges if edge["status"] == "required_incompatible"}
    included = {p for p in traversed if p in installed}
    nodes = [{"name": key, "version": installed[key]["version"], "installed": True}
             for key in sorted(included)]
    if "$project" in traversed:
        nodes.insert(0, {"name": "$project", "version": None, "installed": True})
    nodes.extend({"name": name, "version": None, "installed": False} for name in sorted(missing))
    stats = {
        "installed_packages": len(installed),
        "included_packages": len(included),
        "outside_scope_installed": len(installed) - len(included),
        "edges": len(edges),
        "required_satisfied": sum(e["status"] == "required_satisfied" for e in edges),
        "required_missing": len(missing),
        "required_incompatible": len(incompatible),
        "optional_unselected": sum(e["status"] == "optional_unselected" for e in edges),
        "marker_excluded": sum(e["status"] == "marker_excluded" for e in edges),
        "unresolved": sum(e["status"] in {"unknown", "required_unverifiable"} for e in edges),
        "referenced_but_not_installed": len(missing),
    }
    return {
        "schema_version": "2.0", "scope": effective_scope,
        "focus": focus, "selected_extras": sorted(selected),
        "marker_environment_coverage": sorted(target),
        "nodes": nodes, "edges": edges, "stats": stats,
        "disclaimer": (
            "PEP 508/440 evaluation uses the inspected interpreter's captured metadata. "
            "An optional extra is active only when explicitly selected or required transitively. "
            "Unknown conditions are not counted as broken requirements. "
            "This installed-metadata graph is not a lockfile resolver or proof of importability."
        ),
    }
