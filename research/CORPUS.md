# Candidate incident corpus: curation and blinded evaluation

**Status:** discovery queue, not benchmark ground truth. **Discovery date:** November 9, 2026.

The public candidate register, [candidates.json](candidates.json), contains twelve GitHub issue URLs. Some issue bodies and comments were inspected, whereas others were sourced only from public issue-search summaries. **Zero cases have been independently adjudicated.** No field accuracy can be derived from this register.

## 1. Definitions

A *discovery lead* is a public GitHub issue with an observed packaging, interpreter, wheel, runtime or CI failure. An *inspected issue* has been reviewed for its original report, but remains unverified. *CI-eligible* means the failure happened in a hosted CI runner or comparable automated build/test/release job. An *adjudicated incident* has been checked by two independent reviewers, with a third reviewer resolving disagreements. A *holdout* is a unique incident frozen before any EnvGuard predictions or new classifier rules are developed from it.

## 2. Review procedure

1. Verify that the issue exists. Record the failing job URL and exact failed commit SHA; do not infer these from issue titles.
2. Establish eligibility: automated CI versus local support case, source-code defect versus environment problem, and whether the incident falls within the preregistered evaluation scope.
3. Examine evidence: original error, interpreter/OS, dependency manifest, previous successful state, fixing PR and green run. Closed status is insufficient.
4. Deduplicate: multiple failing jobs caused by the same broken dependency change are **one underlying incident**, not independent samples.
5. Freeze the blinded input bundle: expose failing logs and appropriate baseline, but **withhold the fixing commit, resolution discussion and true label** from EnvGuard and human investigators.
6. Ask two reviewers to complete separate private adjudication forms (blank [template](review-template.csv)). An unresolved case remains UNKNOWN. A third reviewer adjudicates disagreements without erasing their original notes.
7. Freeze the test set, selection rules and bundle checksums before scoring. Keep gold labels inaccessible to the investigator until predictions are locked.
8. Evaluate in-scope attribution, coverage, unsupported attribution, abstentions and human investigation time. Score package metadata checkers only on their stated metadata-consistency objectives.
9. Publish per-case anonymized findings with provenance, denominators, exclusions and confidence intervals. Report failures and not just successes.

## 3. Evidence examples, not gold labels

| Public issue | Initial observation | Remaining gate |
|---|---|---|
| [fractal-web #1293](https://github.com/fractal-analytics-platform/fractal-web/issues/1293) | CI runner-image transition and missing Python SSL functionality; comments discuss aligning the container image | Verify fixing commit and exact green/failing runs |
| [zbase #19](https://github.com/cvsz/zbase/issues/19) | CI pip ResolutionImpossible on conflicting test dependency versions; a corresponding [merged PR #24](https://github.com/cvsz/zbase/pull/24) exists | Independently verify both CI states and conduct blind review |
| [gf180-pll #810](https://github.com/2AMLogic/gf180-pll/issues/810) | Floating Python version in CI coincided with source-build and linker failures | Verify the actual fix and passing CI |
| [fbuild #1781](https://github.com/FastLED/fbuild/issues/1781) | CI workflow invoked a test module missing from the checked-out project | Determine whether this is a workflow/source defect, not environment drift |
| [mcp_coder #1243](https://github.com/MarcusJellinghaus/mcp_coder/issues/1243) | Jenkins dependency environment changed after a subsequent uv sync command | Confirm exact fixing change, installation evidence and runnable baseline |

These five are research leads. A closed issue, a proposed patch, and a plausible explanation **must not be treated as independently verified causality**.

## 4. Data governance and leakage controls

- The candidate JSON has deliberately **no ground-truth label, fixed commit, gold patch or EnvGuard prediction**. Offline CI validation rejects such fields.
- Independent reviews and sensitive artifacts belong under the ignored local directory research-private/; never commit unredacted logs, tokens or employer incident data.
- Do not run third-party attachments or arbitrary issue code during discovery.
- Public issues may contain personal information and may change; use minimal descriptions and retain links, not entire bodies.
- Keep a separate review-only evidence ledger for the adjudication panel. It must not be passed into the diagnosis or tool-selection process.
- This queue is not randomly sampled and cannot yield population coverage or accuracy estimates.

## 5. Offline validation

Run these commands from the repository root:

    python research/validate_candidates.py
    python -m unittest discover -s tests -p "test_research_candidates.py" -v

Neither command requires GitHub access.

## 6. Target and status

**Current status:** 12 discovery leads; 6 plausibly CI related; 0 independently adjudicated; 0 publicly benchmarked field incidents.

**Minimum next target:** 50 independently reviewed and deduplicated real CI incidents across multiple projects. The full methodology is in [BENCHMARK_PROTOCOL.md](BENCHMARK_PROTOCOL.md).
