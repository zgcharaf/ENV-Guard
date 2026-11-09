# EnvGuard CI 0.1 controlled real-execution failure laboratory

The lab builds two valid Python wheels offline, creates disposable actual Python virtual environments, runs a small risk-batch application and tests **why** a command fails. On Linux with a C++ compiler it also compiles and calls genuine shared libraries.

This is **controlled fault injection**, not an independent corpus of enterprise CI incidents. Tests confirm diagnosis on specific known failure classes only.

## Run

```powershell
# Windows, from repository root
python lab/run_lab.py
python lab/run_lab.py --case wrong_interpreter
```

```bash
# Linux/WSL
python lab/run_lab.py
# Or Docker on Windows (Linux-container mode):
docker build -f lab/Dockerfile -t envguard-ci-lab:0.1 .
docker run --rm envguard-ci-lab:0.1
```

| Scenario | Real injection | Expected diagnosis |
| --- | --- | --- |
| healthy | Installed correct wheels | No failure |
| missing_dependency | Omits `scorecodec` from venv | `MISSING_DISTRIBUTION_AT_RUNTIME` |
| wrong_interpreter | Calls another, empty venv instead of explicitly selected installed one | `WRONG_PYTHON_INTERPRETER` |
| site_disabled | Runs installed project using `python -S -m riskbatch` | `PYTHON_SITE_DISABLED` |
| old_dependency_api | Installs old `scorecodec` API | `PACKAGE_API_VERSION_INCOMPATIBILITY` |
| compatible_upgrade | Installs compatible `scorecodec` version | No failure |
| business_assertion_failure | Raises an intentional business-rule assertion with a healthy environment | No environment diagnosis |
| installer_unavailable | Offline `pip install` requests nonexistent wheel version | `PACKAGE_RESOLUTION_UNAVAILABLE` |
| installer_conflict | pip must solve incompatible package constraints | `DEPENDENCY_RESOLUTION_CONFLICT` |
| native_library_missing | `ctypes` loads nonexistent `.so` on Linux | `NATIVE_LIBRARY_LOAD_FAILURE` |
| native_symbol_mismatch | `ctypes` loads old C++ `.so` without expected export | `NATIVE_SYMBOL_LOAD_FAILURE` |

Native scenarios skip on Windows without Docker/WSL2 and on Linux if a C++ compiler isn't present. All wheel installs use the wheel files supplied in this repository with `--no-index`; no registry access is necessary.

## Read a diagnosis with execution evidence

```bash
PYTHONPATH=src python -m envguard_ci diagnose-failure \
  --baseline lab/.envguard-runs/baseline.json \
  --current lab/.envguard-runs/cases/wrong_interpreter/current.json \
  --execution lab/.envguard-runs/cases/wrong_interpreter/execution.json \
  --log lab/.envguard-runs/cases/wrong_interpreter/execution.log \
  --exit-code 1 --format json
```

Each scenario writes `current.json`, `execution.json`, `diagnosis.json`, `execution.log`. The lab root writes `benchmark.json` and `baseline.json`. **Do not upload `execution.log` from real enterprise projects:** raw stdout may contain customer data or secrets. The diagnostic report stores only constrained signatures and sanitized environment evidence.

## Result interpretation

`injected_label_accuracy_at_1` counts exact matches to our predeclared fault labels; the legacy metric `root_cause_accuracy_at_1` is retained for older scripts but is **not** an independently validated causal-accuracy estimate. `benign_false_alarms` counts environmental hypotheses on the two healthy controls and `unrelated_failure_false_alarms` counts incorrect attribution of a failing business assertion. These metrics are not real-world precision/recall. We still need an independently labeled corpus of historical GitLab/GitHub CI failures, with reviewers blinded to injected fault labels.

No Kubernetes, Artifactory, private CI token or cloud service is needed for this lab. Docker is optional and useful mainly for a reproducible Linux/C++ runtime on Windows.
