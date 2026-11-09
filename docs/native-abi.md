# Experimental static wheel ABI inspection (main branch)

**Status:** experimental developer feature under [issue #2](https://github.com/zgcharaf/ENV-Guard/issues/2).
Not part of any previously published v1.0.0rc2 wheel release. The checked-out
`main` branch is the authoritative installation source for this command.

## What this does

The opt-in `inspect-wheel-abi` CLI:

1. Validates a wheel's SHA-256 (optional approved hash) and all supported wheel RECORD digests using EnvGuard's existing offline wheel inspector.
2. Finds bounded ELF `.so` members in its archive (no extraction to their own paths).
3. Reads each member's ELF architecture, `DT_NEEDED` providers and exact
   `GLIBC`, `GLIBCXX` and `CXXABI` requirements via GNU `readelf`.
4. Optionally compares those **exact required version labels** against a
   separately captured target Linux provider manifest.
5. Emits structured JSON with observations, provider gaps and unknowns.

It does not import a Python package, load the wheel, install dependencies, execute
a target binary, contact registries or rewrite the wheel.

This is a *static* examination. GNU readelf itself parses binary bytes and can
contain vulnerabilities; run it as a non-privileged process on a disposable
host when artifacts are not fully trusted. This is NOT a security sandbox.

## Prerequisites

- Python 3.11+, a checkout of EnvGuard `main` installed with
  `python -m pip install -e .`.
- `readelf` on your PATH (normally from GNU binutils).
- To capture a target provider manifest: Linux with `ldconfig` and `readelf`.
- Wheel inputs must be local. This feature **does not download wheels**.

## Step 1 — Collect target-provider evidence on the intended Linux runtime

```sh
envguard-ci capture-native-target --out target-native.json
```

The JSON contains versions defined by candidate system provider files discovered
through the local `ldconfig` cache, including `libc.so.6`,
`libstdc++.so.6` and `libgcc_s.so.1` when present. It includes each provider
file's SHA-256 digest and a normalized machine architecture.

Do **not** assume these are exactly the libraries chosen by every Python
process. `RPATH`, `RUNPATH`, `LD_LIBRARY_PATH`, private libraries or `dlopen`
may select other providers. Record that uncertainty when interpreting a gap.

## Step 2 — Inspect a wheel

```sh
envguard-ci inspect-wheel-abi \
    --wheel dist/your_binary_package-1.0-cp312-cp312-manylinux_2_28_x86_64.whl \
    --out abi.json
```

The command scans ELF files without executing them and reports their requested
library names and version labels. The fake filename is illustrative; supply
your own existing wheel.

For large native wheels, scan a single exact ELF object:

```sh
envguard-ci inspect-wheel-abi --wheel path/to/large.whl \
  --member casadi/_casadi.so --out selected-elf.json
```

The exact member path must be present in the wheel. Other native members are **not** examined in this narrow scan.

### Optional target comparison

```sh
envguard-ci inspect-wheel-abi --wheel path/to/your.whl \
    --target-manifest target-native.json \
    --out abi-target.json --fail-on-shortfall
```

`--fail-on-shortfall` returns exit code 1 if a required version label from a
matching architecture object is absent from the corresponding explicitly
captured provider. Without this flag, **a gap is a report finding and the
command returns zero on a completed inspection.** Invalid inputs return 2.

The system cannot infer target compatibility without a target manifest:
`target_not_provided` is correct. If an object architecture does not match
the target or an exact provider was not observed, the comparison records an
**unknown**, not a proof that the wheel is compatible.

## Output semantics

- `static_elf_scanned` means ELF members were scanned successfully.
- `no_elf_members` means no `.so` members were identified.
- `partial_non_elf_native_members` means ELF files were inspected but
  other native formats such as `.pyd` / `.dll` / `.dylib` were not analyzed.
- `potential_provider_symbol_gap` means a required *exact* symbol-version
  label is not among the given provider's recorded definitions.
- `no_observed_gap_for_checked_symbols` means no gap was found for the
  providers and objects actually inspected; it does **not** guarantee import.
- `no_observed_gap_with_unknowns` means at least one provider or architecture
  could not be evaluated.
- `target_not_provided` means no actual target symbol evidence was supplied.

The report includes wheel/member SHA-256 identities, required version labels,
per-provider comparison evidence and explicit limitations. A ZIP `RECORD`
verification is *not* a publisher signature or software security audit.

## CasADi public test case

The research example [ABI-0001](../research/public-exemplars/ABI-0001-observed-2026-11-09.json)
found that the selected `casadi/_casadi.so` in two published
`manylinux_2_28_aarch64` wheels required different `GLIBCXX` versions:

- CasADi 3.8.0: `GLIBCXX_3.4.32`
- CasADi 3.8.2: `GLIBCXX_3.4.21`

The new CLI can inspect such wheels as *static artifacts*. To claim an
actual target library shortfall, collect provider evidence from an ARM64
Linux machine. A target manifest from an x86_64 CI runner is **incomparable**.

## Known limitations

- Linux ELF only. On Windows/macOS, GNU readelf must be available to inspect
  Linux wheels; non-ELF native formats are not supported in this command.
- Max 32 ELF members, 155 MB per member, 250 MB aggregate extracted ELF,
  and bounded total archive size. Larger inputs are rejected, not silently
  truncated. No arbitrary recursive dependency resolution.
- Exact version definitions from candidate libraries are not proof of the
  active runtime loader's library selection.
- Static analysis omits dynamic imports, provider symbol-name conflicts
  not encoded as versions, and external native dependencies not in the wheel.
- No manylinux policy certification; this command observes ELF requirements
  but does not independently verify every auditwheel allowlist rule.
- The tool does not offer automatic system-library upgrades or repair.

## Regression tests

```sh
python -m unittest discover -s tests -p 'test_wheel_abi.py' -v
```

The cross-platform tests use fake readelf outputs and an integrity-checked
synthetic wheel; Linux additionally builds a tiny local `.so` and inspects
its ELF headers. See [issue #2](https://github.com/zgcharaf/ENV-Guard/issues/2)
for future hardening work.
