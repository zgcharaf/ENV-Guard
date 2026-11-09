# Contributing

Thanks for helping make Python CI failures easier to understand.

## Development setup

Requires Python 3.11 or later and the `packaging` dependency. From the repository root:

```bash
python -m pip install -e .
python -m unittest discover -s tests -v
python lab/run_lab.py
```

On Windows, two native C++ cases skip unless you use Docker or WSL2. CI cases are controlled fault injection, not blind incident benchmarks.

## Adding a detector

1. Start with a real (sanitized) error signature. Write a regression test that shows when it *should* match and when it should **not**.
2. Separate observed error text from hypotheses about causes. Require additional runtime evidence before claiming a specific cause.
3. Add a minimal, read-only troubleshooting playbook to `src/envguard_ci/incident.py`.
4. Never execute log content. Do not put raw stdout, passwords, full `argv`, or private repository URLs into reports.
5. Preserve nonzero process exit codes in `ci-run`.

PR descriptions should state how the failure was reproduced and what was actually verified. Please do not submit unsupported accuracy claims or silently remove security qualifiers.

## Coding guidelines

Use Python standard library by default; `packaging` is required for PEP 508 and version constraint semantics. Favor small, deterministic functions and explicit JSON schema keys. Add a negative control for every new category where possible.
