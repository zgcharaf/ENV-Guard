## Unreleased — native wheel ABI evidence (main branch)

- Added experimental `inspect-wheel-abi` and `capture-native-target` commands; not present in previously built v1.0.0rc2 artifacts.
- Added integrity-gated, bounded static ELF inspection with exact provider version requirements and explicit unknown states.
- Added a target-provider manifest from Linux `ldconfig` and `readelf` with clear runtime-loader limitations.
- Added adversarial regression tests and real public ARM64 wheel integration tests.
- No versioned public release or guaranteed runtime compatibility claimed.

## 1.0.0rc2 (GitLab pilot compatibility)

- Fix Linux venv interpreter verification: preserve invocation paths of symlinked
  `bin/python` executables rather than collapsing all environments to the same
  underlying CPython binary via `Path.resolve()`.
- Refuse candidate verification if original and candidate have the same observed
  `sys.prefix` environment identity; no false fix verification for two aliases
  to one environment.
- Include hosted-GitLab pilot regression coverage.

# Changelog

## 1.0.0rc1 — integrated evidence and verification release candidate

- New `investigate` command: retains `ci-run`'s failure-preserving behavior, with optional GitLab or GitHub latest-successful baseline retrieval, comparator warnings and fail-open/fail-closed baseline policy.
- New bounded GitHub Actions artifact retrieval, with redirect token stripping and snapshot validation.
- New `inspect-wheel` SHA-256, wheel ZIP member and RECORD integrity checks. Reports uncertainty about runtime compatibility and publisher authenticity.
- New explicit `verify-interpreter` two-run verification of one constrained candidate: run the exact `-m` or `-c` workload through two named Python interpreters. Outputs measured results; no patching.
- New optional `certify-wheel` offline import smoke in a read-only/no-network, resource-limited Docker container. This is **not** a full security sandbox.
- GitLab/GitHub CI recipes, new tests and v1 architecture/security guidance.

This rc1 is **not** independently benchmarked, does not have general-purpose safe self-healing, and has not been validated on live hosted GitHub/GitLab runners in this release.

## Prior releases

v0.2.0 provided snapshot capture, interpreter provenance, marker-aware dependency checks, native ELF inspection, failure classification, incident dossiers and a controlled GitLab diagnosis demonstration.
