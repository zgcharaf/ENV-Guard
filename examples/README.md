# Examples

- `run_failure_demo.py`: self-contained actual wrong-interpreter case using offline wheels and isolated environments. Writes a report and incident dossier.
- `github-actions-snippet.yml`: instrumentation for another Python app on GitHub Actions.
- `gitlab-ci-snippet.yml`: instrumentation for another Python app on GitLab.
- `demo.ps1` and `demo.sh`: inspect fixture snapshots without running CI.

Adapt the YAML paths and install commands to your own project. Don't share raw logs or private dependency snapshots publicly.
