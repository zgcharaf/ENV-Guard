# EnvGuard CI — Python CI diagnostics

**Documentation:** [Academic website](https://zgcharaf.github.io/ENV-Guard/) · [Complete reference manual](https://zgcharaf.github.io/ENV-Guard/docs/) · [Seven tutorials](https://zgcharaf.github.io/ENV-Guard/tutorials/) · [Research & benchmarks](https://zgcharaf.github.io/ENV-Guard/research/)

**Current source release:** `1.0.0rc2` (experimental; no production guarantees). The historical sections below document older releases and should be interpreted accordingly.

---

## Public incident discovery corpus

Our research now includes a [public candidate register](https://zgcharaf.github.io/ENV-Guard/research/corpus/) and [review protocol](research/CORPUS.md). Initial public issues are **leads only**; there are no independent incident labels or field accuracy estimates. Run `python research/validate_candidates.py` to audit the candidate registry without network access.

**Diagnose Python CI environment drift, verify wheel bytes, and run constrained recovery experiments.**

This is an experimental, not production-certified release candidate. [v1 operator guide](docs/v1-quickstart.md) · [v1 architecture and trust boundaries](docs/v1-architecture.md) · [security policy](SECURITY.md).

```bash
# Existing stable command path (works offline)
envguard-ci investigate --project . --python "$(command -v python)" \
  --snapshot-out current.json --report-out report.json -- python -m pytest

# With GitLab last-successful baseline (requires authorized runner)
envguard-ci investigate --last-green gitlab --baseline-ref "$CI_DEFAULT_BRANCH" \
  --baseline-job envguard-ci:tests -- python -m pytest

# Verify a downloaded wheel's SHA-256 and internal RECORD metadata
envguard-ci inspect-wheel --wheel dist/your_project-1.0-py3-none-any.whl
```

Current limits: last-successful baseline may not precede the failing commit; evidence does not prove causality; `verify-interpreter` requires explicit authorization for unsandboxed commands; Docker wheel import smoke tests are not a complete security boundary; hosted CI and live Docker testing of v1's new features remain pending.

---

## Previous v0.2 functionality (retained)

# EnvGuard CI

**Explain why a Python job failed in one environment when it worked in another.**

[![Status: release candidate](https://img.shields.io/badge/status-release%20candidate-blue)](#release-status)
[![Python: 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)](#installation)

EnvGuard CI is a **local-first, read-only Python CLI** for environment diagnostics in GitLab CI, GitHub Actions and developers' terminals. Instead of replacing `pip`, `uv`, Poetry or virtualenv, it gathers runtime evidence, compares a failing run with a known-good snapshot, and generates an **evidence-linked incident dossier**.

> **Not an auto-fixer.** No dependency changes, lockfile updates, automatic PRs, remote telemetry, or claims of guaranteed root-cause certainty. It executes the command **you explicitly ask it to run**; this is not a sandbox.

## Why this exists

The same `ModuleNotFoundError` can mean (a) a dependency was never installed, (b) CI invoked the wrong Python executable, or (c) imports were disabled with `-S`. A package inventory alone cannot tell these cases apart. EnvGuard records *directly invoked* Python identity and other evidence, and says **undetermined** when that evidence is missing.

For normal collection, it produces three files even when the wrapped job fails:

```text
ci-snapshot.json   # Python runtime and installed dependency inventory
ci-report.json     # machine-readable environment findings and error signature
ci-report.md       # evidence ledger, confidence, limitations, read-only next checks
```

If environment collection itself fails, EnvGuard preserves the wrapped command's exit code and writes a minimal report and incident dossier **when the destination is writable**. Snapshot collection may remain unavailable and no root cause will be asserted.

### Example incident excerpt

```text
Execution: supported_hypothesis
Observed failure: module_missing
Root-cause hypothesis: WRONG_PYTHON_INTERPRETER
Confidence: high

Evidence:
  * Wrapped command failed
  * Directly executed Python differs from the explicitly intended Python
  * The expected runtime contains a possible provider for the missing import

Next checks:
  * Inspect interpreter and prefix for both CI steps
  * Check packages using the same interpreter as the failed command

Limitations:
  * No fix has been executed or validated
```

The actual `.md` contains pointers to the relevant fields in the accompanying diagnostic JSON, so a developer can audit each statement. This excerpt is illustrative; the repository includes a real-execution lab.

## Installation

**This repository is a locally verified v0.2.0 release candidate, not yet published on PyPI.**

The existing PyPI distribution `envguard` belongs to an unrelated project; this repository deliberately uses the distinct distribution **`envguard-ci`**, console script **`envguard-ci`**, and import package **`envguard_ci`**. PyPI availability of `envguard-ci` is not guaranteed until an owner actually registers and publishes it.

From the extracted repository or a checkout:

```powershell
# Windows PowerShell / Python 3.11+
py -m pip install -e .
envguard-ci --version
```

```bash
# Linux / macOS / WSL2
python -m pip install -e .
envguard-ci --version
```

If you previously installed an internal `envguard==2.1.0` prototype, it is a **different distribution**. `envguard-ci` can be installed separately; use the new CLI name. Clear a lingering `PYTHONPATH=.../envguard-v2.1.0/src` override before testing. For reproducible use outside this repository, build and install the wheel from the [release checklist](docs/release.md).

## 60-second quick start

```bash
# Check your current interpreter and project. Inspecting Python may execute
# interpreter startup hooks (e.g. sitecustomize); use trusted interpreters.
envguard-ci snapshot --project . --out local.json
envguard-ci doctor --snapshot local.json

# Wrap a real command and retain its original failure exit code.
# `--python` is the EXPLICITLY INTENDED interpreter, not an auto-detected one.
envguard-ci ci-run --project . --python python \
  --snapshot-out ci-snapshot.json --report-out ci-report.json \
  -- python -m unittest discover -s tests -v

# Evidence-led report is written automatically to ci-report.md.
# Re-render the dossier as machine-readable JSON when needed:
envguard-ci triage --report ci-report.json --format json --out ci-incident.json
```

PowerShell single-line version:

```powershell
$expected = (Get-Command python).Source
envguard-ci ci-run --project . --python $expected --snapshot-out ci-snapshot.json --report-out ci-report.json -- python -m unittest discover -s tests -v
Get-Content ci-report.md
```

**Important:** The wrapped command's exit code is propagated; an intentionally failing example returns nonzero. `--python` should point to the interpreter you intended to run in the pipeline (and it should exist). The command after `--` is executed without a shell.

### Compare a known-good environment

Capture a snapshot from a successful job on a **comparable platform**, retain it as a CI artifact, and provide it to a failing run:

```bash
envguard-ci ci-run --project . --python python \
  --baseline good-snapshot.json \
  --snapshot-out ci-snapshot.json --report-out ci-report.json \
  -- python -m unittest discover -s tests -v
```

The report distinguishes observed signatures, drift correlations and inferred causes. v0.2.0 also flags **different target environments** (OS, architecture, Python implementation/minor version, or ABI) and reduces confidence in package-only comparisons where the baseline may be inapplicable. A changed version is **not** automatically considered the cause of a failure.

### Standalone diagnostics

```bash
envguard-ci diff --baseline good-snapshot.json --current ci-snapshot.json
envguard-ci graph --snapshot ci-snapshot.json --focus pandas
envguard-ci graph --snapshot ci-snapshot.json --scope environment
envguard-ci triage --report ci-report.json --out incident.md
```

`graph` evaluates dependency environment markers and selected extras rather than reporting every optional extra as broken.

## Reproduce an actual failure without downloading a Python package

Run the bundled experiment from the repository root:

```bash
python examples/run_failure_demo.py
```

It builds tiny offline Python wheels, creates separate temporary virtual environments, *runs the wrong interpreter*, and checks that EnvGuard emits `WRONG_PYTHON_INTERPRETER` backed by interpreter evidence. It writes reports under `lab/.envguard-runs` and exits **0 if the experiment passes**.

To run the entire controlled fault-injection suite:

```bash
python lab/run_lab.py
```

On Linux (or Windows with Docker Desktop in Linux mode) the C++ shared-library experiments also execute:

```bash
docker build -f lab/Dockerfile -t envguard-ci-lab:0.1 .
docker run --rm envguard-ci-lab:0.1
```

**Kubernetes is not needed.** Docker is optional for basic Python cases.

## CI integration

- **GitHub Actions:** use [`.github/workflows/ci.yml`](.github/workflows/ci.yml) for this repository. For another repo, adapt [`examples/github-actions-snippet.yml`](examples/github-actions-snippet.yml).
- **GitLab CI/CD:** use [`.gitlab-ci.yml`](.gitlab-ci.yml) for this repository, or adapt [`examples/gitlab-ci-snippet.yml`](examples/gitlab-ci-snippet.yml).

The workflows preserve logs in the CI platform as usual. EnvGuard reports omit raw logs and explicit command arguments, but **dependency names and metadata can still be confidential**. Restrict access to CI artifacts.

## Main commands

| Command | What it does |
| --- | --- |
| `snapshot` | Inspects selected Python, platform, installed distributions and selected project files |
| `doctor` | Checks local supported inconsistencies |
| `diff` | Compares snapshots from comparable environments |
| `graph` | Evaluates required, conditional and selected-extra dependency edges |
| `ci-run` | Runs the supplied command, streams output, preserves its exit code, and writes JSON + incident Markdown |
| `triage` | Turns a CI JSON report into an evidence-led Markdown or JSON incident dossier |
| `diagnose-failure` | Correlates bounded error logs with two snapshots and optional execution provenance |
| `render-report` | Emits Markdown, GitHub annotations or GitLab Code Quality JSON |
| `gitlab-baseline` | Explicitly fetches a baseline artifact from GitLab when authorized |

Run `envguard-ci COMMAND --help` for options.

## What is validated and what is not

- Core graph, collector, signatures and basic GitLab/GitHub adapters were inherited from the earlier engineering prototype and retested for this release candidate.
- The new evidence-led incident dossier has unit and CLI integration tests, including deliberately malformed/ambiguous cases.
- The included fault-injection lab is **controlled**, with known labels. It does **not** measure blind accuracy or performance against actual commercial CI tools.
- Shell wrappers (`uv run`, `poetry run`, `sh -c`), arbitrary launchers and Python subprocesses are **not traced**. Without an explicitly observed direct Python invocation, interpreter root cause must remain uncertain.
- Fingerprints identify declared/runtime **metadata**, not cryptographic attestation of installed bytes. Native library inspection supports only selected Linux paths.
- GitHub and GitLab pipeline YAML are prepared but have not been verified on hosted runners in this build environment. There is no cloud backend or auto-healing feature.

## Package release validation

The repository includes build and verification gates for wheel, source distribution, and an isolated CLI smoke test. For a local build with the standard PyPA tools:

```bash
python -m pip install 'build>=1.2,<3' 'twine>=6,<8'
python -m build
python -m twine check dist/*
python scripts/verify_release.py --dist dist
python scripts/smoke_release.py --dist dist
```

The smoke test deliberately executes a failing Python module and checks that the original status and an evidence dossier are preserved. `scripts/smoke_release.py --offline` is only a convenient **non-isolated** verification mode if `packaging` already exists in your environment.

The GitHub release workflow creates a **draft** release on a matching version tag. Publishing to PyPI requires a *manual* release-tag dispatch plus a configured, protected `pypi` environment and PyPI Trusted Publisher. See [the release checklist](docs/release.md).

## Release status

**v0.2.0 · release candidate.** Locally validated on Linux/Python 3.13 with 97 unit and integration tests and 11 controlled failure-lab cases. The wheel and sdist passed archive checks; the wheel was installed and exercised from outside the checkout. **GitHub/GitLab hosted CI matrix and publication are still unverified.** No public PyPI upload or repository publication has occurred.

## Open-source development

- [Architecture](docs/architecture.md)
- [GitLab usage](docs/gitlab.md)
- [Security and disclosure policy](SECURITY.md)
- [Contributing and running tests](CONTRIBUTING.md)
- [Release checklist](docs/release.md)
- [License: MIT](LICENSE)

All diagnostics are local unless you **explicitly invoke** the GitLab artifact-fetching command. No automated collection or uploading of your application logs is performed.
