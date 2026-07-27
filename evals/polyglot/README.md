# Aider Polyglot subset — 10-problem RACT anchor

**Origin.** SUBSTRATE spec §9 (Eval-First as Engineering Discipline) and
module_07 of the v0.4.0 pipeline. The Aider Polyglot benchmark is the
first public, per-provider coding leaderboard that scores end-to-end
edit + test loops (not function-scale like HumanEval, not repo-scale
like SWE-bench). Ten of its problems anchor RACT on the existing map.

## Reference sources

- Aider Polyglot public repository:
  `https://github.com/Aider-AI/aider`
- Aider Polyglot public leaderboard:
  `https://aider.chat/docs/leaderboards/`
- Two-attempt-with-test-feedback pattern per SUBSTRATE §2.2.
- Unified-diff output format per SUBSTRATE §5.2 (Aider's canonical
  output shape).

## Subset selection rule (deterministic, pinned)

The subset is deterministic and pinned so leaderboard numbers do not
drift between runs:

1. Enumerate every problem in the upstream Polyglot repository under
   `benchmark/`.
2. Filter to problems whose seed language directory is `python/` or
   `javascript/` (per module_07 plan text).
3. Sort by problem id (lowercase, ASCII-alpha) ascending.
4. Take the first 10.

The pinned list lives in `subset.json`. Every entry carries the
upstream source URL at pinning time so a subset revision is a distinct
commit with an ADR entry (Lateral Chain branch C, module_07).

Changing `subset.json` requires a new ADR that documents why the
subset changed. Historical numbers remain readable against the
historical subsets.

## Runner shape

`runner.py` runs one Polyglot problem end-to-end:

1. **Clone.** Shallow-clones the upstream reference repository into a
   fresh directory under the workspace's `.tmp/polyglot/<problem_id>/`
   at runtime (the module_07 tree ships neither the reference source
   nor the container images). If the clone fails (offline, upstream
   moved), the runner returns a `SKIPPED` result with a specific
   reason and the CI summary counts the skip.
2. **Open a `StepTransaction` (module_02).** Every problem attempt
   runs inside a fresh worktree-per-step scope with a
   `CapabilityManifest` (module_03) attached. Aider Polyglot's
   filesystem footprint is fully containable in a manifest-declared
   scratch directory.
3. **Invoke the RACT loop** with the Polyglot problem statement as the
   compiled intent (module_01's `IntentCompiler`). The loop's output
   is a unified diff over the seed files, per Aider's canonical
   output shape.
4. **Two attempts with feedback** (Aider Polyglot's scoring pattern):
   on the first attempt, apply the diff, run the hidden test suite;
   if any test fails, feed the failing test output back into the loop
   as a follow-up intent and take one more attempt.
5. **Score.** Pass = the hidden test suite is green after either
   attempt. Boolean per problem.

`report.py` aggregates per-provider pass rate across the 10 problems
and writes `evals/runs/<date>-polyglot-<provider>.json` plus a
markdown summary at `evals/runs/<date>-polyglot-<provider>.md`.

## Fixture provider path

Live provider runs are gated by the nightly `evals-full.yml` workflow
and the `RACT_EVAL_ENABLED` repository secret (Lateral Chain branch B,
module_07). Every-PR CI runs the smoke tier against a fixture
provider whose event stream lives at
`evals/fixtures/providers/aider_polyglot/<problem_id>.jsonl`. The
fixture stream conforms to `docs/EVENTS.md` `schema_version: "2"` and
is loaded by `ract trace replay` (module_05).

## Not-in-tree at module_07 close

The reference repository is **not** vendored under this directory.
The runner clones at execution time. Docker images and dataset shards
are similarly runtime-fetched. This keeps the RACT tree free of
upstream copyright and out-of-date snapshots. See
`_BUILD/ract_v0.4.0_substrate/module_07.md` "Flagged gaps" for the
list of things the module_07 close explicitly does not include.

RACT 0.4.0
