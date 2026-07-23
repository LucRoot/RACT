# RACT Public Quality Leaderboard

This page tracks RACT's own quality metrics over time. The goal is to make the loop's progress visible and comparable across commits.

## Current snapshot

| Metric | Value | Date | Commit |
|---|---|---|---|
| Test suite | 1079 passed, 1 skipped | 2026-07-09 | `41854c0`+WIP |
| Line coverage | 91.30% | 2026-07-09 | `41854c0`+WIP |
| `src/ract/cli.py` coverage | 76% | 2026-07-09 | `41854c0`+WIP |
| Lint (`ruff`) | clean | 2026-07-09 | `41854c0`+WIP |
| Type check (`mypy`) | clean | 2026-07-09 | `41854c0`+WIP |
| Dead-code auction on RACT | 0 candidates | 2026-07-09 | `41854c0`+WIP |
| Doctor self-check | 7/7 | 2026-07-09 | `41854c0`+WIP |
| Audit meta-command | 9/9 checks passed | 2026-07-09 | `41854c0`+WIP |
| Audit `--deep` | consolidate scan included | 2026-07-09 | `41854c0`+WIP |
| Novelty detector — verbatim duplicate | `low` (ratio ~0.66) | 2026-07-09 | `41854c0` |
| Novelty detector — novel Python | `nominal` (ratio ~0.81) | 2026-07-09 | `41854c0` |
| Novelty detector — prose | `nominal` (ratio ~1.03) | 2026-07-09 | current |
| Mutation score — `src/ract/rooted.py` | 38.0% (18/47 mutants killed) | 2026-07-09 | prior |
| Mutation score — `src/ract/executor.py` | 47.81% (328/686 non-suspicious killed) | 2026-07-09 | current |
| Coverage badge | dynamic endpoint (`docs/coverage-badge.json`) | 2026-07-09 | current |

## Methodology

- **Coverage** is measured with `pytest --cov=src` against the full suite.
- **Dead-code auction** is `ract auction list` run against RACT itself; candidates are modules with no inbound references from production code.
- **Novelty detector** scores are from `ract novelty scan` against representative probes.
- **Mutation score** is from `mutmut` targeted at a single file using `tests/test_<file>.py`; a higher percentage means more mutants were killed by the test suite.

## History

| Date | Coverage | Auction candidates | Notes |
|---|---|---|---|
| 2026-07-09 | 91.30% | 0 | `audit --deep` now runs consolidate scan; 1079 tests; 10s scan time |

## Next targets

- Keep per-file mutation floor for `executor.py` at the measured 47.81% and add dynamic badges.
- Raise `src/ract/cli.py` coverage above 80%.
- Record a real terminal asciicast once asciinema is available on Windows ARM64.
- Extend `ract audit --deep` to include mutation-score drift checks.
- Optimize `ract novelty scan` so it can rejoin `audit --deep` without timing out.
<!-- RACT 0.1.1 - Trust and Tooling -->
