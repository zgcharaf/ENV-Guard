# EnvGuard CI — Research and Benchmark Protocol

**Status:** preregistered controlled experiments + real hosted CI evidence. Not an independent benchmark of root-cause accuracy.

**Version:** v1.0.0rc2. **Study date:** 2026-11-09.

## 1. Evidence registry and interpretation

| Evidence | Category | Location | What it establishes |
|---|---|---|---|
| 11-case offline injected-fault lab | Controlled fault injection | [Recorded JSON](../examples/controlled-benchmark.json) | 8/8 injected failure labels matched; 2 benign and 1 non-environment failing controls had no environmental attribution |
| Public GitHub Actions release gate | Hosted CI run | [Successful CI run](https://github.com/zgcharaf/ENV-Guard/actions/runs/42652589626) | Actual cross-platform package tests, release build/smoke and lab job passed; inspect job artifacts/logs for details |
| Wrong-interpreter lab in GitHub Actions | Hosted synthetic incident | [Earlier run](https://github.com/zgcharaf/ENV-Guard/actions/runs/42619255881) | Real runner executed a deliberately wrong interpreter and reported it; an assertion in the demo script also failed; this run is not a clean validation |
| GitLab wrong-interpreter pilot | Hosted synthetic incident (prior user evidence) | [Pilot repository](https://gitlab.com/envguardci-group/envguard-gitlab-pilot) | CI invoked a Python without a package, EnvGuard emitted a supported wrong-interpreter hypothesis, and artifacts were uploaded; verify specific pipeline artifact links before quoting quantitative outcomes |
| Independent historical CI incidents | Not yet evaluated | [Dataset template](dataset-template.csv) | Corpus design only. No external incident accuracy measured |

**Critical distinction:** “root_cause_accuracy_at_1” in the generated lab JSON is a backward-compatible **legacy field**. Its value equals accuracy against **developer-authored injected labels**, not held-out causal accuracy. Report that value as 8/8 on 8 injected failures, not as 100% production accuracy.

## 2. Reproducible controlled experiment

Run from the repository root on Linux with Python >=3.11 and a C++ compiler for native cases:

\`\`\`sh
python -m pip install -e .
python lab/run_lab.py --out research-results/lab
python -m json.tool research-results/lab/benchmark.json
\`\`\`

The lab creates disposable environments and builds fake package wheels offline, then runs real subprocesses. It covers a healthy environment, two other controls, missing dependencies, wrong interpreter, \`-S\`, incompatible API, offline installation failures, and native library/symbol errors. On Windows, native cases may be skipped. Read \`skipped_cases\` in JSON and never silently count skipped cases as passed.

The committed sample result is a single observed run with 11 evaluated cases, 8 intentionally injected environmental failures, 2 benign controls, 1 unrelated failing control, 8 exact label matches and zero false environmental attributions among the 3 controls. Total sample lab wall-clock is 19.7 seconds **in that sample environment** and must not be interpreted as a comparative speed measurement.

## 3. Comparator study: pip, uv, EnvGuard

A dependency consistency checker and an incident attribution tool have different purposes. This study does **not** score pip or uv as wrong for failing to identify wrong interpreters or native loader issues, which are outside their specific \`pip check\` scope.

Run the paired audit after the lab:

\`\`\`sh
python -m pip install uv
python research/compare_tools.py --lab-output research-results/lab \\
  --out research-results/comparison.json --require-uv
\`\`\`

The script invokes \`<case-venv-python> -m pip check\` and \`uv pip check --python <case-venv-python>\` on the same generated environments, with registry lookups disabled. It records tool versions, platform, exit codes, durations and SHA-256 digests of output. It deliberately **does not store raw command outputs**, to avoid accidental log leakage. Compare counts of nonzero metadata-check exits only for the predefined metadata-related subset (\`missing_dependency\` and \`old_dependency_api\`). These are not exact root-cause predictions. The benchmark's script is observational, and does not change the virtualenvs it examines.

For \`uv pip check\`, verify the installed uv version supports \`--python\`; the published version and help output should be kept with the evidence. If a command fails because of unsupported options, classify it as *execution/compatibility failure*, not as a finding.

**Important:** No cross-tool comparator scores have been independently reported on the website. The repository must retain the resulting JSON with the commit and full runner environment before measured claims are published.

## 4. Independent holdout protocol

Target at least 50 independent Python CI incidents from multiple projects/maintainers. For each:

1. Collect a failing commit, a relevant last-known-good baseline, logs redacted for secrets, the environment configuration, and the externally verified fixing commit or precise root-cause statement.
2. Label independently by at least two reviewers who did not construct the diagnostic hypotheses; reconcile disagreements. Preserve \`UNKNOWN\` when the evidence does not support a unique cause.
3. Define whether each incident is in scope for EnvGuard, pip check, uv pip check or a generic CI-log viewer. Report scope-stratified results and overall coverage separately.
4. Run the same frozen inputs through tools at pinned versions in the same OS/Python container or runner. Reset the workspace between attempts. Do not permit access to historical fixes during diagnosis.
5. Record unassisted correct-attribution-at-1, abstention, unsupported false attributions on negative controls, diagnosis time, runtime and missing evidence. Human-assisted time measurements must use randomized order and repeated operators.
6. Publish a predeclared analysis and itemized anonymized results, including failures. Confidence intervals must reflect the small sample and clustered project structure.

## 5. Primary metrics

Let \(N_\mathrm{eligible}\) be the independently labelled incidents that a tool is documented to diagnose, and \(N_\mathrm{correct}\) be the exact, independently adjudicated predictions among those incidents. Let \(N_\mathrm{negative}\) be non-environment failures and \(N_\mathrm{false}\) be those wrongly attributed to environmental causes.

- **In-scope attribution-at-1:** \`N_correct / N_eligible\` (with confidence interval).
- **Coverage:** \`N_eligible / N_total\`; report unknowns and excluded cases.
- **Unsupported attribution rate:** \`N_false / N_negative\`.
- **Abstention rate:** fraction of evaluated incidents where a tool declines specific attribution.
- **Evidence fidelity:** proportion of claims pointing to reproducible observed data fields (independent auditor).
- **Investigation-time savings:** median paired change measured across engineers, not script execution duration.

For metadata-only tools, report *dependency metadata inconsistency detection* on the appropriate subset rather than causal diagnosis.

## 6. Reproducibility, ethics, and threats to validity

The injected faults are known to the authors, and classification rules may be implicitly tailored to them. Individual cases share the same synthetic project, so they are not statistically independent incidents. Public GitHub issues can be ambiguous even if marked closed. A CI workflow passing only shows that its own test harness passed, not the validity of an external root-cause accuracy claim. Missing/expired historical artifacts are a real constraint. Repositories and logs can contain credentials; obtain permission and redact before public use.

Raw logs, employer projects, and proprietary dependency inventories **must not** enter the public benchmark without permission. The default comparison script stores hashes instead of raw output. For private validations use protected artifacts and an approved environment.

## 7. Submission

Use [dataset-template.csv](dataset-template.csv) to contribute anonymized candidates. Open a GitHub issue with reproduction steps and permissions for redistribution; do not post unredacted logs or secrets. Validate labels before admitting cases into the held-out evaluation.

## References

- [EnvGuard lab implementation](../lab/run_lab.py)
- [Controlled sample](../examples/controlled-benchmark.json)
- [GitHub quality-gate workflow](../.github/workflows/ci.yml)
- [pip check documentation](https://pip.pypa.io/en/stable/cli/pip_check/)
- [uv pip check documentation](https://docs.astral.sh/uv/pip/compatibility/)
- [EnvGuard validation notes](../docs/v1-validation.md)
