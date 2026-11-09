# Public development exemplars (excluded from held-out evaluation)

These cases originate from **already-publicly diagnosed or fixed** incidents.
They are valuable for reproducing specific failure mechanisms and regression
tests, but they are NOT blinded benchmark cases. Their source and fix have
already been visible to EnvGuard developers.

| Case | Topic | External evidence | EnvGuard replay |
| --- | --- | --- | --- |
| [CI-0002](CI-0002.json) | pip resolver conflict between pytest 9.0.3 and pytest-asyncio 1.2.0 | [Original failed CI](https://github.com/cvsz/zbase/actions/runs/42434561391), [fix PR](https://github.com/cvsz/zbase/pull/24), [post-fix CI](https://github.com/cvsz/zbase/actions/runs/42434951881) | [Hosted minimal-pair replay](https://github.com/zgcharaf/ENV-Guard/actions/runs/42664192392) |

The [permanent hosted observation JSON](CI-0002-observed-2026-11-09.json) is derived from the successful workflow job output and stores status, fingerprints of output, EnvGuard hypothesis and the source run URL, without raw logs. It remains a disclosed development case.

## Strict boundaries

- `holdout_eligible=false` is a **permanent** flag for disclosed cases.
- The replay uses `pip install --dry-run --ignore-installed --only-binary=:all:` with public PyPI wheel metadata.
- The raw third-party logs and full upstream application are not part of this repository.
- A passing minimal-pair replay demonstrates only package constraint behavior; it does not prove the historical CI job's entire dependency set or tests are equivalent.
- Only independently reviewed, previously unseen incidents belong in field-accuracy analysis.
- Never claim that EnvGuard independently discovered the fix to CI-0002.

Documentation: [case study](https://zgcharaf.github.io/ENV-Guard/research/cases/ci-0002/) and [corpus selection protocol](../CORPUS.md).
