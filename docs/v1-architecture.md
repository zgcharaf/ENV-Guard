# EnvGuard CI v1.0.0rc1: architecture and supported claims

A **release candidate for real-world validation**, not a production-certified or security-audited tool.

**Post-rc2 experimental extension on `main`:** Static ELF inspection is now available through `inspect-wheel-abi`, with an optional explicitly captured `capture-native-target` provider manifest. It reads `DT_NEEDED` and versioned C/C++ symbol requirements without loading wheel code. It does not establish actual dynamic linker selection or production compatibility. See [native ABI guide](native-abi.md).

## Trust boundaries

- **Collector:** a subprocess imports stdlib metadata under the selected interpreter. Python startup hooks can execute application-controlled code. Do not inspect untrusted interpreters with elevated privileges.
- **CI wrapper:** runs the developer's explicitly supplied command, inherits runner permissions, and preserves its exit code. No shell by default. Original logs go to the existing CI output; only a bounded tail is used in-memory for classification.
- **Baseline fetchers:** GitLab latest-successful branch job artifact; GitHub latest successful workflow artifact. Neither proves historical ancestry or causal relevance. Missing baselines fail open unless `--require-baseline` is set. Credentials are not serialized and cross-origin HTTP redirects drop authentication.
- **Evidence engine:** compares Python and native runtime metadata, installed distributions and interpreted failures. It must show `unknown` where observations are insufficient.
- **Wheel inspector:** checks bytes, ZIP member safety and RECORD digests offline; hash identity is not publisher authentication. Cannot certify target runtime compatibility from wheel metadata alone.
- **Repair experiment:** supports only an *explicitly authorized* same-program run through two different Python executables. This is **not a sandbox**. The candidate passing the observed command does not prove a unique causal factor or a safe general repair.
- **Docker import smoke:** creates a disposable, no-network, read-only-root, non-root container running an offline wheel import. A container alone is **not an adequate hostile-code sandbox**. Wheels execute code during installation/import. Run only with approved artifacts and images, a patched Docker host, no privileged secrets, and separate build runners.

## Major modules

- `ci.py` / `cli.py`: execution, latest-green retrieval, reports.
- `github.py` / `gitlab.py`: read-only successful artifact retrieval with bounded downloads.
- `collection.py` / `native.py`: interpreter metadata and optional read-only ELF inspection.
- `diagnostics.py` / `failure.py` / `incident.py`: deterministic findings, evidence ledger, uncertainties.
- `artifacts.py`: wheel digest and RECORD checks (no execution).
- `verification.py`: two-interpreter repair candidate experiment.
- `certify.py`: optional offline container import smoke test.

## Deliberate exclusions

No generic dependency solver, auto-install into user environments, unsupervised source patching, machine-learned cause certainty, cryptographic package signing, full child-process tracing, Kubernetes integration, enterprise secrets management, or remote SaaS. Automatic last-green comparison is **not** a guarantee that the chosen baseline is a causal comparator.

## What to measure next

Collect 50+ independently labeled incidents, sample positives and unrelated failures, compare to uv/pip + auditwheel + native GitLab diagnostics, report root-cause coverage, precision, false attribution, baseline mismatch frequency, repair verification success, and engineering minutes saved.
