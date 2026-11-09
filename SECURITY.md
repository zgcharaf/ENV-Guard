# EnvGuard CI v1.0.0rc1 security policy

EnvGuard is **not a secure sandbox** or a general purpose automated repair engine. Use only with explicitly approved source trees, Python interpreters, wheels and container images.

- `investigate` and `ci-run` execute provided commands with the **existing runner privileges**. Python startup hooks can execute code even during environment collection. Never provide production secrets to an untrusted pull request job.
- `verify-interpreter --allow-local-execution` executes the same selected program **twice on the host/runner**. Use disposable CI infrastructure and no privileged credentials. The command may write files or access the network; EnvGuard does not constrain it.
- `certify-wheel` invokes Docker with no network, read-only root, no-new-privileges, a non-root user and limits, but Docker is **not sufficient isolation for truly malicious code**. Untrusted packages need more stringent isolation, controlled builders and security review. Docker daemon should never be accessible in the launched container.
- Baseline retrieval explicitly contacts configured GitLab/GitHub API only when requested. Prefer least-privileged ephemeral tokens. Cross-origin redirects drop token headers. Do not upload sensitive reports publicly.
- Diagnostic JSON can reveal private package names, versions, build fingerprints and CI infrastructure metadata. EnvGuard redacts some paths/URLs but does not provide a full sanitization guarantee. Raw command output remains in CI logs and may include secrets emitted by upstream tools.
- `inspect-wheel` validates bytes, checks RECORD hashes and filenames offline. A matching SHA-256 is not proof of safe or trusted provenance. Approved artifact hashes must be obtained from trusted sources out of band.
- No automatic patching or deployment is performed by v1.0.0rc1.

For security concerns, use a private repository security advisory; maintainers should enable private reporting before public publication. No security SLA is currently offered.
