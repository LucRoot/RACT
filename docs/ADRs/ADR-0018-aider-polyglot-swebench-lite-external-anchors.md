# ADR-0018 — Aider Polyglot subset and SWE-bench Lite as external eval anchors

## Status

Accepted (v0.4.0, module_07).

## Context

SUBSTRATE spec §9 (Eval-First as Engineering Discipline) requires
that "the loop is measured against corpora other people also measure
against." v0.3 shipped three RACT-authored tasks under `evals/tasks/`
(refactor, FastAPI validation, file watcher) and one loop-vs-baseline
token-usage benchmark. Those are internal — they prove the harness
runs but they do not locate RACT on the map the field already reads.

The two coding-eval anchors the field converges on are:

- **Aider Polyglot** — Aider's per-provider public leaderboard,
  scored on multi-language edit + test-feedback loops at the
  function-to-file scale. Two attempts per problem, hidden test
  suite, unified-diff output.
- **SWE-bench Lite** — a filtered subset of SWE-bench where every
  instance ships as one Docker image, scored on a repo-scale
  issue-to-patch loop with `FAIL_TO_PASS` + `PASS_TO_PASS`
  verification.

Reference sources:

- Aider Polyglot: `https://github.com/Aider-AI/aider`,
  `https://aider.chat/docs/leaderboards/`.
- SWE-bench: `https://www.swebench.com/`,
  `https://github.com/SWE-bench/SWE-bench`.
- OpenHands V1 SDK per-instance execution:
  `https://github.com/All-Hands-AI/OpenHands`.
- SUBSTRATE spec §9 and §11 signal 16 (leaderboard as canonical
  published record).

## Decision

Anchor RACT on both benchmarks with a deterministic, pinned subset
of each:

1. **Aider Polyglot subset (10).** Enumerate `benchmark/` in the
   upstream repository, filter to problems whose seed language is
   `python/` or `javascript/`, sort by id ascending, take the first
   10. Pin the list in `evals/polyglot/subset.json` with source URLs
   per problem.
2. **SWE-bench Lite subset (5).** Pin 5 instances spanning 3
   repositories and 3 issue types so a single-repo regression does
   not silently swing the leaderboard. `evals/swe_bench_lite/
   instances.json` carries the pinned list with source URLs and
   per-instance Docker image names.
3. **Runners.** `evals/polyglot/runner.py` and
   `evals/swe_bench_lite/runner.py` execute each problem/instance
   inside a fresh `StepTransaction` (module_02) with a
   `CapabilityManifest` (module_03) attached. Output shape is the
   canonical shape for each benchmark (unified diff / git patch).
4. **Reports.** `report.py` per corpus aggregates per-provider pass
   rate and writes `evals/runs/<date>-<corpus>-<provider>.{json,md}`.
5. **Leaderboard.** `evals/LEADERBOARD.md` is the canonical published
   record. `evals/leaderboard/update.py` regenerates it from the most
   recent report per `(provider, corpus)`. The regenerator is
   idempotent — a no-op nightly produces no commit.
6. **Fixture providers.** `evals/fixtures/providers/<corpus>/<id>.jsonl`
   hold synthetic schema-v2 event streams the runners replay when
   `provider=fake` (default in CI). The fixtures prove the harness
   without live-provider cost (Lateral Chain branch B) or
   upstream-registry access (Lateral Chain branch A).
7. **CI wiring.** The existing `eval-smoke` job runs one Polyglot
   problem + one SWE-bench instance against the fixture provider on
   every PR. A nightly `evals-full.yml` workflow runs the full 10 + 5
   against live providers, gated by `RACT_EVAL_ENABLED`.

Changing `subset.json` or `instances.json` is a distinct commit with
its own ADR entry (Lateral Chain branch C, module_07). Historical
numbers remain readable against the historical subsets.

## Rejected alternatives

- **RACT-authored evals only** (the v0.3 baseline). Rejected because
  the reviewer cannot locate RACT on the field's existing map from
  numbers no one else runs. The three v0.3 tasks stay as legacy
  entries but are not the primary published record.
- **Full Aider Polyglot 225-problem corpus.** Rejected as the per-PR
  smoke tier because a full sweep costs significant live-provider
  budget and CI time; the nightly full-run is deferred to a future
  hardening item that lifts the subset from 10 to the full corpus.
- **HumanEval or MBPP.** Rejected because both are function-scale;
  they do not exercise the module_02 transactional substrate or the
  module_03 sandbox in the way SWE-bench Lite and Polyglot do. RACT's
  differentiator is the substrate — an eval anchor that never opens a
  transaction fails to measure it.
- **Vendoring the upstream reference repositories.** Rejected because
  the tree would carry third-party source under conflicting licences
  and would drift from the live upstream. The runners clone /
  `docker pull` at runtime; when the registry is unreachable, the run
  reports SKIPPED with a specific reason and the CI summary counts
  the skip (Lateral Chain branch A).

## Consequences

- The leaderboard has room for numbers the field can compare RACT
  against.
- Every subset revision is an ADR-tracked event, so numbers cannot
  drift silently.
- The nightly workflow is idempotent — a no-op night produces no
  commit and no leaderboard churn.
- Live-provider runs and container-image pulls are operator-triggered
  work. Module_07 ships the harness, the pins, the fixtures, and the
  workflows; the first per-provider scored rows land on the operator's
  own budget.

## Reference sources

- `_BUILD/ract_v0.4.0_substrate/module_07.md` — the pipeline module
  driving this change.
- `evals/polyglot/README.md`, `evals/swe_bench_lite/README.md` — per-
  corpus operator-facing docs.
- `evals/LEADERBOARD.md` — the canonical record itself.

RACT 0.4.0
