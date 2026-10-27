# Sprint 6 journeys (package 8)

The ten journeys J1 to J10 (and the S1 to S4 setup scenarios) run with `tests/ux/run_baseline.py` on the
hygiene branch (tip 9cfae3c), against the fake server, at 80 columns (`80/`) and 60 columns (`60/`) with
`RACT_UX_COLS` set. Headers carry the build and run time.

Comparison with `docs/ux/b054r`: the scenario inputs differ (for example J9 is a weak model with a summary
request in the sprint 6 set, and J8 is a question run with `ract -p`), so line differences show scenario
changes as well as behaviour changes. Compared as like for like only where the scenario matches; the bar
check rows that these captures move are updated in docs/ux/ux_bar_check.md.
