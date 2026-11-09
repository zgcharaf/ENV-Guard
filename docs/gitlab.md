# GitLab integration — EnvGuard CI v0.2.0 release candidate

The repo's `.gitlab-ci.yml` contains a self-test job and a controlled failure lab. To instrument an existing Python project, use `examples/gitlab-ci-snippet.yml` as a starting point.

EnvGuard wraps commands with `ci-run` and saves an environment snapshot (`*-ci.json`), an evidence report (`*-report.json`) and an incident dossier (`*-report.md`) even when the wrapped command exits with an error and evidence collection succeeds. Use `artifacts: when: always` to retain all files. **Two instrumented steps should use separate filenames**, because a second step can overwrite the first report.

When the target virtualenv is not yet present, execute its creation **before** `ci-run`; EnvGuard cannot probe a nonexistent interpreter and might only write a collection failure report. Installer errors can be wrapped separately from test execution errors.

## Baseline comparison

If your instance permits reading a successful default-branch job artifact, run explicitly:

```bash
envguard-ci gitlab-baseline --job 'envguard-ci:tests' \
  --artifact envguard-ci.json --out good.json
```

Then add `--baseline good.json` to the `ci-run` invocation in the failing job. Keep baseline comparison to compatible OS/architecture/Python configurations. Default-branch history isn't automatically causal evidence.

The baseline fetcher accepts GitLab's `CI_API_V4_URL`, `CI_PROJECT_ID` and `CI_DEFAULT_BRANCH`. It uses a dedicated `ENVGUARD_GITLAB_READ_TOKEN` when provided or `CI_JOB_TOKEN` subject to GitLab permissions. No token is stored in the diagnostic report, but protect runner logs and ensure forks/untrusted PRs have no privileged credentials. HTTPS is required by default; the client strips credentials on cross-host redirects.

## Code Quality annotations

Optionally run:

```bash
envguard-ci render-report --input tests-report.json \
  --format gitlab-codequality --out tests-codequality.json
```

GitLab Code Quality needs a repository file location. For environment-level issues the tool uses an explicitly synthetic `pyproject.toml:1` anchor. Don't interpret this as identifying a source-code line defect. You may omit Code Quality entirely and retain JSON/Markdown files instead.

**Live GitLab-runner execution remains to be verified.** The shipped YAML represents an integration starting point, not a guarantee across GitLab tiers, private registries, or runner configurations.
