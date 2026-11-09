# v0.2.0 local release validation record

**Date:** 2026-10-21  
**Validated environment:** Linux x86-64, CPython 3.13.5.  
**Status:** release candidate — public hosted runner and package-registry tests outstanding.

## Checks completed

| Check | Result | Evidence/method |
| --- | --- | --- |
| Automated unit and integration tests | 97 passed | `python -m unittest discover -s tests -v` |
| Actual controlled Python/C++ failure lab | 11 / 11 cases passed | `python lab/run_lab.py --out lab-results` |
| Build wheel and source distribution | Success | `uv build --no-build-isolation --out-dir dist` |
| Archive metadata and hygiene checks | Pass | `python scripts/verify_release.py --dist dist` |
| Wheel installed outside checkout | Pass | `python scripts/smoke_release.py --dist dist --offline` |
| Original wrapped-command status and incident report | Pass | Smoke test triggers an intentional missing-module error |
| GitHub/GitLab YAML syntax | Pass | YAML parser syntax check (does **not** execute pipelines) |

## Scope and limitations

The controlled lab consists of eight injected dependency/environment failures, two successful controls, and one unrelated failing control. It does **not** establish accuracy on independent historical CI incidents.

The local wheel smoke run used `--offline`, inheriting installed site packages so the required `packaging` distribution was available. A **strictly isolated** wheel-install smoke test is configured in hosted CI but has **not** been run here.

No hosted GitHub Actions / GitLab runners, PyPI trusted publication, Windows/macOS platform matrix, third-party supply-chain/security review, auto-repair system, or blind diagnosis benchmark have been verified. Build checksums do not by themselves attest the builder.
