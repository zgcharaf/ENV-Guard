# EnvGuard CI v1.0.0rc1 validation ledger — 2026-10-25

## Executed locally

- Existing 97 regression tests: **passed** immediately after v1 CLI and module integration.
- Added v1 tests: **13/13 passed**, including GitLab retrieval simulation, GitHub successful workflow/artifact simulation, wheel RECORD tampering, missing baseline policy and offline container invocation (mocked).
- Full previous codebase plus initial 11 new tests also ran together: **108 passed** before the final two tests were added.
- All 11 controlled real-execution failure-lab scenarios: **passed**, including two Linux native-library failures, wrong interpreter, import/API errors, installer failures and three benign/unrelated controls.
- One actual two-interpreter verification: **failed command exit 1; candidate exit 0**, with persistent fingerprints and explicit experiment limitations.
- Wheel and sdist produced locally; release-archive metadata and hygiene checks passed; wheel installed in a separate environment and a failure-report smoke test passed.
- Workflow YAML parsed on the local environment.

## Not executed / not established

- No Docker daemon is available in this runtime. `certify-wheel` has **mock-invocation tests only**; container installation and isolation behavior still need live Docker validation.
- Neither v1 GitHub Actions nor GitLab latest-successful baseline retrieval was exercised against a live provider in this session. Unit tests mock API responses; previous v0.2 wrong-interpreter diagnosis was run by the user on an actual GitLab runner.
- No independent blind evaluation corpus; lab outcomes cannot substantiate real-world root-cause accuracy claims.
- No security assessment, fuzzing campaign, supply-chain attestation, or production/bank approval.
- No general automatic fix generation, validated patching of code or CI pipelines, private-registry source provenance, or reliable nested process tracing.

## Operational gate before a stable v1.0

1. Run GitLab and GitHub examples on real hosted runners; inspect baseline selection, permissions and artifact retention.
2. Test `certify-wheel` on the supported Docker Desktop/Linux containers and a native-extension wheel.
3. Run on trusted private GitLab with synthetically constructed private packages and intentionally expired tokens, checking redaction.
4. Collect at least 50 held-out historical CI failures to estimate coverage, false attribution and diagnosis time savings.
5. Audit `verify-interpreter` and Docker execution trust boundaries and add explicit policy checks for enterprise contexts.
