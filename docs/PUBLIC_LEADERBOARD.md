# RACT Public Quality Leaderboard

This page tracks RACT's own quality metrics over time. The goal is to make the loop's progress visible and comparable across commits.

## Current snapshot

| Metric | Value | Date | Commit |
|---|---|---|---|
| Test suite | 999 passed, 1 skipped | 2026-07-09 | `b3b05cd` |
| Line coverage | 91% | 2026-07-09 | `b3b05cd` |
| Lint (`ruff`) | clean | 2026-07-09 | `0243d80` |
| Type check (`mypy`) | clean | 2026-07-09 | `0243d80` |
| Dead-code auction on RACT | 0 candidates | 2026-07-09 | `0243d80` |
| Doctor self-check | 7/7 | 2026-07-09 | `0243d80` |
| Novelty detector — verbatim duplicate | `low` (ratio ~0.66) | 2026-07-09 | `0243d80` |
| Novelty detector — novel Python | `nominal` (ratio ~0.81) | 2026-07-09 | `0243d80` |
| Novelty detector — prose | `high` (ratio ~0.87) | 2026-07-09 | `0243d80` |
| Mutation score — `src/rootact/rooted.py` | 38.0% (18/47 mutants killed) | 2026-07-09 | prior |
| Mutation score — `src/rootact/executor.py` | 39.1% (239/611 non-suspicious killed) | 2026-07-09 | `eae16f4` |

## Methodology

- **Coverage** is measured with `pytest --cov=src` against the full suite.
- **Dead-code auction** is `rootact auction list` run against RACT itself; candidates are modules with no inbound references from production code.
- **Novelty detector** scores are from `rootact novelty scan` against representative probes.
- **Mutation score** is from `mutmut` targeted at a single file using `tests/test_<file>.py`; a higher percentage means more mutants were killed by the test suite.

## History

| Date | Coverage | Auction candidates | Notes |
|---|---|---|---|
| 2026-07-09 | 91% | 0 | Post-pruning, symbol-graph fix, novelty detector calibration |

## Next targets

- Decide whether to set a per-file mutation floor for `executor.py` at the measured 39.1% or first add tests to raise it.
- Raise `src/rootact/cli.py` coverage above 70%.
- Add a dynamic mutation-score badge to the README once per-file floors are stable.
