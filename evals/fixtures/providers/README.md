# Fixture provider event streams

**Origin.** module_07 of the v0.4.0 pipeline. The two runners under
`evals/polyglot/` and `evals/swe_bench_lite/` default to `provider=fake`
in CI; the fixture path replays a canned event stream from this
directory. That proves the harness parses, dispatches, and reports
correctly without live-provider cost (Lateral Chain branch B) or
upstream-registry access (Lateral Chain branch A).

## Layout

```
evals/fixtures/providers/
  aider_polyglot/<problem_id>.jsonl
  swebench_lite/<instance_id>.jsonl
```

Every fixture is one JSONL file per problem/instance. The **first
non-comment line is a header** carrying at minimum:

- `schema_version` — the `docs/EVENTS.md` schema version the fixture
  conforms to. Module_07 fixtures target `"2"` (module_06 bumped
  1 → 2 with the new `auction.proposal` event kind).
- `corpus` — either `"aider_polyglot"` or `"swebench_lite"`.
- `problem_id` or `instance_id` — matches the pinned subset/instance
  record.
- `note` — human-facing description; synthetic-vs-recorded is called
  out explicitly.

Subsequent lines are event dicts with `kind` and `payload` fields
matching the closed vocabulary in `src/ract/trace/events.py`. Empty
lines and `#`-prefixed lines are ignored.

## What the runner reads

- **Polyglot runner** (`evals/polyglot/runner.py`) reads
  `response.received` events keyed by `attempt_index` for the unified
  diff, and `tool.result` events with `tool == "hidden_test_suite"`
  for the boolean pass. Two attempts, feedback from attempt 1 flows
  into attempt 2 when present.
- **SWE-bench runner** (`evals/swe_bench_lite/runner.py`) reads
  `response.received` events with `output_shape == "git_patch"` for
  the patch, and `tool.result` events with `tool` in
  `{"fail_to_pass", "pass_to_pass"}` for the boolean sets. Pass
  requires both sets green.

## What the fixtures are NOT

The shipped fixtures are **synthetic** event streams authored to
prove the runner shape. They are NOT recordings of live provider
runs. Real per-provider recordings are operator-triggered work
(`RACT_EVAL_ENABLED=1`, live API keys, upstream reachability) and
land as their own commits with the resulting artifacts under
`evals/runs/<date>-<corpus>-<provider>.{json,md}`.

## Reference sources

- `docs/EVENTS.md` — closed event vocabulary and schema version.
- `src/ract/trace/events.py` — `EventKind` literal.
- `src/ract/trace/cli_trace.py` — `ract trace replay` load path.
- module_05 of the v0.4.0 pipeline for the fixture-provider design
  origin.

RACT 0.4.0
