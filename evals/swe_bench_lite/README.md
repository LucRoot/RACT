# SWE-bench Lite — 5-instance RACT anchor

**Origin.** SUBSTRATE spec §9 (Eval-First as Engineering Discipline)
and module_07 of the v0.4.0 pipeline. SWE-bench Lite is the widely
adopted subset of SWE-bench, filtered to instances that fit in a
single Docker image per instance and that can be scored via
`FAIL_TO_PASS` / `PASS_TO_PASS` test-set verification. Five
instances anchor RACT on the repo-scale portion of the map.

## Reference sources

- SWE-bench public site: `https://www.swebench.com/`.
- SWE-bench repository: `https://github.com/SWE-bench/SWE-bench`.
- OpenHands V1 SDK public repository:
  `https://github.com/All-Hands-AI/OpenHands` — the container-per-
  instance execution pattern reused for this runner.
- Git-patch output format per SUBSTRATE §5.2 (SWE-bench's canonical
  output shape).

## Instance selection rule (deterministic, pinned)

Five instances span three repositories and three issue types so a
single-repo regression does not silently swing the leaderboard.
`instances.json` carries the pinned list. Every entry carries its
upstream source URL at pinning time; changing the pinned set is a
distinct commit with an ADR entry (Lateral Chain branch C, module_07).

## Runner shape

`runner.py` runs one SWE-bench Lite instance end-to-end:

1. **Pull the instance image.** SWE-bench Lite ships per-instance
   Docker images at
   `docker.io/swebench/sweb.eval.<instance_id>:latest` (or the
   equivalent registry-mirrored path). The runner shells out to
   `docker pull` at runtime; failure surfaces as a `SKIPPED` result
   with a specific reason (Lateral Chain branch A, module_07).
2. **Mount the base commit into a fresh worktree** (module_02). The
   worktree lives under `.tmp/swebench_lite/<instance_id>/` and is
   backed by the base commit named in the pinned instance record.
3. **Open a `StepTransaction`** with a `CapabilityManifest`
   (module_03) attached. The manifest allowlists the repo path,
   Python + pip + pytest, and denies network egress (SWE-bench
   images ship their own network-free test environment).
4. **Invoke the RACT loop** with the instance's issue body as the
   compiled intent (module_01's `IntentCompiler`). The loop's output
   is a git patch over the instance's repo state — the SWE-bench
   canonical output shape.
5. **Apply and verify.** Apply the patch, run the instance's
   `FAIL_TO_PASS` and `PASS_TO_PASS` test sets. Pass requires both
   sets green.

`report.py` aggregates per-provider pass rate across the 5 instances
and writes `evals/runs/<date>-swebench_lite-<provider>.json` plus a
markdown summary at `evals/runs/<date>-swebench_lite-<provider>.md`.

## Fixture provider path

Live provider runs are gated by the nightly `evals-full.yml` workflow
and the `RACT_EVAL_ENABLED` repository secret (Lateral Chain branch B,
module_07). Every-PR CI runs the smoke tier against a fixture
provider whose event stream lives at
`evals/fixtures/providers/swebench_lite/<instance_id>.jsonl`. The
fixture stream conforms to `docs/EVENTS.md` `schema_version: "2"` and
is loaded by `ract trace replay` (module_05).

## Not-in-tree at module_07 close

The instance repositories are **not** vendored under this directory.
The runner clones / mounts the base commit at execution time; the
Docker images are runtime-fetched. This keeps the RACT tree free of
upstream copyright, third-party licence encumbrance, and out-of-date
snapshots. See `_BUILD/ract_v0.4.0_substrate/module_07.md`
"Flagged gaps" for the list of things the module_07 close explicitly
does not include.

RACT 0.4.0
