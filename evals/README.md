# RACT Evaluations

Reproducible tasks and benchmarks for measuring RACT across providers.
The **canonical published record** is `LEADERBOARD.md`, regenerated
by `leaderboard/update.py` from the per-provider reports under
`runs/` (SUBSTRATE spec §11 signal 16; module_07 of the v0.4.0
pipeline).

## Corpora

Four corpora contribute to the leaderboard:

- `polyglot/` — Aider Polyglot subset (10 problems, deterministic
  pin under `polyglot/subset.json`). Function-to-file scale;
  two-attempts-with-test-feedback pattern; unified-diff output.
  Reference: `https://github.com/Aider-AI/aider`.
- `swe_bench_lite/` — SWE-bench Lite subset (5 instances,
  deterministic pin under `swe_bench_lite/instances.json`).
  Repo-scale; container-per-instance; git-patch output;
  `FAIL_TO_PASS` + `PASS_TO_PASS` verification. Reference:
  `https://www.swebench.com/`, `https://github.com/SWE-bench/SWE-bench`.
- `conformance/` — module_04's typed-action-union corpus (schema
  compliance, tool discipline, refusal fidelity). Router gates
  on a recent passing report per provider.
- `tests/security/` — module_03's adversarial sandbox corpus.

## Legacy: v0.3 RACT-authored tasks

The v0.3 tasks remain valid; the v0.4 leaderboard supersedes them as
the primary published record but does not retire the tasks. They
continue to run in the smoke CI step.

- `tasks/refactor-function/` — split a 200-line function into
  testable units.
- `tasks/fastapi-validation/` — add input validation to a FastAPI
  endpoint.
- `tasks/file-watcher/` — implement a file watcher that rebuilds on
  change.

## Running

Legacy v0.3 tasks:

```bash
python -m ract.eval.runner evals/tasks/refactor-function --provider mock --seed 42
python -m ract.eval.runner evals/tasks/fastapi-validation --provider mock --seed 42
python -m ract.eval.runner evals/tasks/file-watcher --provider mock --seed 42
```

v0.4 polyglot / swebench (fixture provider, no live API required):

```bash
python -c "from pathlib import Path; from evals.polyglot.runner import RunConfig, run_subset; from evals.polyglot.report import build_report, write_report; results = run_subset(RunConfig(workspace=Path('.'), subset_path=Path('evals/polyglot/subset.json'), provider='fake')); write_report(build_report('fake', results), Path('evals/runs'))"
python -c "from pathlib import Path; from evals.swe_bench_lite.runner import RunConfig, run_instances; from evals.swe_bench_lite.report import build_report, write_report; results = run_instances(RunConfig(workspace=Path('.'), instances_path=Path('evals/swe_bench_lite/instances.json'), provider='fake')); write_report(build_report('fake', results), Path('evals/runs'))"
python -m evals.leaderboard.update --repo-root .
```

Nightly full-sweep runs (10 + 5 across live providers) are wired in
`.github/workflows/evals-full.yml` and gated by the
`RACT_EVAL_ENABLED` repository secret (Lateral Chain branch B,
module_07). Public forks and PRs do not incur cost.

## Reports

Per-provider reports land under `runs/<date>-<corpus>-<provider>.{json,md}`.
The leaderboard update script picks up the most recent report per
`(provider, corpus)` tuple and rewrites `LEADERBOARD.md`. The
regenerator is idempotent — a no-op nightly run produces no commit
(Lateral Chain branch D, module_07).

RACT 0.4.0
