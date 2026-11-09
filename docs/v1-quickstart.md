# EnvGuard CI v1.0rc1 — operator guide

## Installation

```bash
python -m pip install ./dist/envguard_ci-1.0.0rc1-py3-none-any.whl
envguard-ci --version
```

## Local failure analysis

```bash
envguard-ci investigate --project . --python "$(command -v python)" \
  --snapshot-out evidence/current.json --report-out evidence/incident.json \
  -- python -m pytest
```

## Automatic GitLab last-green comparison

On a properly authorized GitLab runner, with a successful `envguard-ci:tests` job on its default branch that uploaded `envguard-ci.json`:

```bash
envguard-ci investigate --project . --python "$(command -v python)" \
  --last-green gitlab --baseline-ref "$CI_DEFAULT_BRANCH" \
  --baseline-job envguard-ci:tests --baseline-artifact envguard-ci.json \
  --snapshot-out envguard-ci.json --report-out envguard-report.json \
  -- python -m pytest
```

The latest-successful artifact is **not guaranteed** to be the previous ancestor of this change. The first run may have no baseline. Add `--require-baseline` to halt *before* the wrapped command when it is missing. `CI_JOB_TOKEN` access to historical artifacts is subject to GitLab permissions; a limited `ENVGUARD_GITLAB_READ_TOKEN` can be provided through protected CI variables.

## Automatic GitHub baseline comparison

Use `--last-green github --github-workflow ci.yml --baseline-ref main` with `GITHUB_TOKEN` granted Actions read permission. Ensure the successful workflow saved an artifact named `envguard-baseline` containing `envguard-ci.json`. The example `.github/workflows/ci.yml` does this. Do not supply privileged tokens on untrusted fork PRs.

## Wheel provenance, no execution

```bash
envguard-ci inspect-wheel --wheel dist/example-1.0-py3-none-any.whl \
  --approved-sha256 YOUR_APPROVED_64_CHARACTER_SHA256 --out integrity.json
```

This validates byte identity and RECORD checks, not publisher trust or full runtime compatibility.

## Explicit interpreter repair experiment (trusted/disposable project only)

```bash
envguard-ci verify-interpreter --project . \
  --original-python .venv-bad/bin/python \
  --candidate-python .venv-good/bin/python \
  --allow-local-execution --out experiment.json -- -m bankrisk_demo
```

The application runs **twice** with runner permissions and may have side effects. It does not modify dependencies. Use dedicated test runners, not production.

## Optional target Docker wheel import smoke

```bash
envguard-ci certify-wheel --wheel dist/example-1.0-py3-none-any.whl \
  --image 'registry.example/runtime@sha256:ACTUAL_64_DIGIT_DIGEST' \
  --module example --wheelhouse ./approved-wheels \
  --out deployment-proof.json
```

Docker is required for this command only. Wheel imports/installations execute code in a restricted container, **not** a full untrusted-code sandbox. Uses `--network none`, a read-only root filesystem, non-root UID and limited resources. All wheel dependencies must be in the approved local wheelhouse or already in the selected image. No LLM or network needed.

## Interpreting reports

`supported_hypothesis` means the observed evidence supports an explanation; it does **not** mean causality is proven. `observed_candidate_succeeds` means only that the identified candidate invocation passed while the baseline invocation failed. `passed` from the container command means only that offline installation and the specified import succeeded in that image.

## Try the full offline experiment on Windows or Linux

From the extracted source repository:

```powershell
python examples/run_v1_repair_demo.py
```

This constructs synthetic local wheels and disposable virtual environments, then verifies that the alternate interpreter succeeds. Windows does not need Docker for this demonstration. The optional Linux C++ failure lab still requires Linux/Docker for its native scenarios.
