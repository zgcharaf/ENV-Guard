# Public release checklist — EnvGuard CI v0.2.0

**Status:** build-ready and locally tested release candidate. **Not published** to a remote GitHub or PyPI registry.

## A. Verify code and packaging before tagging

From the checked-out repository on a trusted machine:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python lab/run_lab.py
python -m pip install 'build>=1.2,<3' 'twine>=6,<8'
python -m build
python -m twine check dist/*
python scripts/verify_release.py --dist dist
python scripts/smoke_release.py --dist dist
```

Windows: execute the unit and Python-only lab tests natively, and the native C++ failure cases via WSL2/Docker. Verify `envguard-ci --version` returns `envguard-ci 0.2.0`. The offline smoke option inherits site packages and is **not** as strict as the normal isolated smoke.

Only synthetic public examples and fixtures belong in the public repository; review dependency inventory outputs for proprietary names/paths. Snapshot fingerprints do not attest to installed wheel bytes.

## B. Create repository and validate hosted CI

1. Create a GitHub repository and push this **source** tree. Add the real repository URL and maintainer contact to `pyproject.toml`, `SECURITY.md`, and README once known. Do not add invented URLs or contact details.
2. Enable branch protection, review requirements, secret scanning, dependency alerts, and private vulnerability reporting.
3. Run `.github/workflows/ci.yml` across the Python/OS matrix; inspect results on Linux, Windows and macOS. Do not assert hosted CI is green before it actually runs.
4. If using GitLab, run `.gitlab-ci.yml` on a real runner; confirm Code Quality reports and `when: always` report artifacts survive a failed test job.
5. Pin external GitHub Actions to **verified full commit SHAs** for deployments requiring stronger supply-chain protection; the supplied workflow currently uses upstream major-version tags. Grant write or OIDC permissions only to release/publish jobs.
6. Confirm licensing rights for all contributions and public fixture datasets. This project uses MIT; permissions for third-party contributions still matter.

## C. Make an auditable GitHub draft release

Once all required checks are green, commit the final manifest, change log, and workflow; create and push tag `v0.2.0`. `.github/workflows/release.yml` checks the tag matches package metadata, builds the wheel/sdist, verifies archive contents, installs the wheel for a smoke test, writes SHA-256 checksums, and creates a **draft** GitHub release for review. Publishing that draft is a maintainer action.

## D. Optional PyPI trusted publication (explicitly gated)

**Do not assume the name `envguard-ci` is reserved.** Recheck the package index at publication time. The unrelated name `envguard` is already owned by another distribution.

1. Register a PyPI account with 2FA and create a pending trusted publisher for the chosen repository and workflow `.github/workflows/publish-pypi.yml` (following current PyPI docs).
2. Configure a protected GitHub environment named `pypi`, restricted to release tags and requiring a reviewer.
3. Dispatch **Publish validated release to PyPI** from the *release tag*, not the default branch. The workflow refuses non-tag refs, rebuilds and verifies the package, and uses OIDC `id-token: write` only for its publish job.
4. Check that the package installs with `python -m pip install envguard-ci==0.2.0` and `envguard-ci --version`, from a clean supported interpreter, after publication.

Trusted publishing guide: https://docs.pypi.org/trusted-publishers/using-a-publisher/

## Explicit non-claims

- Real hosted GitLab/GitHub execution has **not** been validated in the local build environment.
- There has been **no** third-party security review, blind incident-accuracy benchmark, supply-chain attestation, or verified automatic repair.
- SHA-256 checksums validate downloaded artifact identity; they do not independently verify a builder's trustworthiness.
