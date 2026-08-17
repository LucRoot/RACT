# RACT v0.3.1 — Hardening Master Spec

**Author:** Dr. Lucas Root
**Predecessor:** v0.3.0 (2026-07-25) — Auditability and Depth
**Input:** the flagged-gaps log carried forward from `_BUILD/ract_v0.3_rebuild/module_02..07`
**Version target:** 0.3.1
**Tag target:** `v0.3.1`

---

## Why this pipeline exists

v0.3.0 shipped seven modules with each module's Definition of Done met at the
declared floor. The operator's honest assessment on close was: *not MVP yet,
let alone good, and a long way from excellent.* Each v0.3 module logged a
"Flagged gaps" section as the durable record of that distance.

This pipeline is that log turned into a build. **The bar is raised past each
flagged-gap's own "bar raise" suggestion.** Where v0.3 said "queue a hardening
module for X", v0.3.1 does X plus one more level: the audit-anywhere claim,
the multi-task honest sweep, the offline-verifiable sidecar, the pre-commit
lockdown, the concurrency proof.

Rootknot remains the philosophical spine. Every module in v0.3.1 either
strengthens the mechanism around it (self-contained sidecars, real assumption
binding, complete CLI surface) or hardens the ground it stands on
(config-schema safety, independence, hygiene, concurrency).

---

## Non-negotiable invariants

- **Rootknot is sacred.** Not renamed, demoted, or replaced.
- **Every module's Definition of Done is a yes/no test.** No qualitative DoDs.
- **The DoD is the floor.** After it passes, log what is still shallow in
  the module's `Flagged gaps` section. Excellence goes to the next pipeline;
  gaps stay visible.
- **Independence.** No new third-party dependencies. Curated allowlist stays
  the ceiling. If a module needs one, it justifies it in a fresh ADR first.
- **Full suite green at every commit.** `ruff check`, `mypy`, `pytest -q` all
  clean before a module lands.
- **Cron is the watchdog.** The end-of-turn pulse and long-cycle re-anchor
  run via CronCreate rather than `.ps1` scripts. Same discipline, different
  delivery.
- **No merge to `origin/main` inside this pipeline.** Local commits only;
  push is a separate operator-approved step.

---

## Module map (raised bars)

Eight modules. Each header includes the flagged-gap origin and the specific
bar raise beyond the v0.3 module's "queue a hardening module for X" note.

### module_01 — Config schema versioning (ADR-0008 realized)

**Origin.** v0.3 module_03 gap 1, module_07 gap 1.

**Scope.**

1. Add `schema_version: "1"` at the top of `ract.yaml.example`.
2. `src/ract/config.py` (or the current config loader) rejects a versionless
   or unknown-version config with a clear, actionable diagnostic that names
   the exact file and the supported versions.
3. Add a `ract config migrate` CLI verb that rewrites a v0-shape file to v1
   in-place with a `.bak` sidecar.
4. Add a `ract config lint` CLI verb (parallel to the independence lint) so
   CI catches config drift before load-time.

**Bar raise past flagged.** ADR-0008 only asked for enforcement; this module
adds `migrate` and `lint` so future breaking changes are safe *and* visible
in CI.

**Definition of Done.**

- `ract.yaml.example` carries `schema_version: "1"`.
- Loading a versionless or unknown-version config raises `ConfigVersionError`
  with the exact filename and supported version list. Test: `pytest -q
  tests/test_config_schema_version.py` — 5 tests green.
- `ract config migrate <path>` rewrites v0 → v1 and writes `<path>.bak`.
- `ract config lint` exits non-zero on a bad file, zero on a good one.
- Full suite green.

### module_02 — Self-contained sidecars + offline `provenance verify`

**Origin.** v0.3 module_05 gap 1, module_07 gap 2.

**Scope.**

1. Sidecar schema bumps to v2: adds `generator.public_key` (raw 32-byte
   ed25519 pubkey, base64-encoded). `public_key_id` stays (backwards-compat
   read).
2. `ract provenance verify <path>` works on a machine with **no `.ract/`
   directory, no `keys/` directory, and no RACT install state** — only the
   sidecar + the `cryptography` stdlib-safe stub.
3. Verifier reads v1 sidecars (key-id + local resolve) OR v2 sidecars
   (embedded pubkey, offline).
4. Add `--strict` flag to `provenance verify` that refuses v1 sidecars.
5. Add `ract provenance verify --batch <dir>` for directory sweeps.

**Bar raise past flagged.** Flagged only asked for embedding the raw pubkey.
This module adds offline batch mode + strict opt-in so v0.3.1's sidecars are
the full audit artifact and CI can enforce it.

**Definition of Done.**

- Sidecar produced by v0.3.1 carries `generator.public_key`.
- A test that runs verify inside a `tmp_path` with `HOME` and `RACT_HOME`
  pointed away from any keys still passes on a v0.3.1-produced sidecar
  and fails on a v0.2 sidecar under `--strict`. Test:
  `pytest -q tests/test_provenance_offline_verify.py` — 6 tests green.
- Verify batch on a directory of 3 sidecars (2 valid, 1 tampered) prints
  `2 valid, 1 invalid` and exits non-zero.
- Full suite green.

### module_03 — Loop → executor: real assumption binding + RK-1.5

**Origin.** v0.3 module_05 gap 2, module_07 gap 4, and (bar raise) module_07
gap 7.

**Scope.**

1. `Executor.write_artifact(...)` (or current equivalent) takes a
   `PlanContext(plan_id, step_id, assumption_id)`.
2. `core/loop.py` supplies the context from the active plan step on every
   emitted write.
3. `core/provenance.py::verify_workspace` gains **RK-1.5**: *every recorded
   rootknot's assumption_id resolves to a registered assumption in state
   `active` or `discharged`.* Violation raises `TerminationCause.T3_PROVENANCE_FAILURE`.
4. Executor provenance signing is **ON by default** (`sign_and_index: true`);
   `--no-sign` is the opt-out. Update `ract.yaml.example` and docs to match.

**Bar raise past flagged.** Flagged asked for real binding; this module also
inverts the default so safety is opt-out not opt-in, and adds the RK-1.5
gate so the binding is enforced across the loop, not just recorded.

**Definition of Done.**

- Property test (Hypothesis): for any generated loop run, every emitted
  artifact has a rootknot whose assumption_id is present in the assumption
  registry. Test: `pytest -q tests/property/test_rk_1_5.py` — Hypothesis
  passes with `max_examples=200`.
- `verify_workspace` raises `T3_PROVENANCE_FAILURE` when an unregistered
  assumption is injected.
- Default config has `sign_and_index: true`; a fresh `ract init` produces a
  run that signs by default.
- Full suite green.

### module_04 — Provenance CLI complete + audit-bundle format

**Origin.** v0.3 module_05 gap 4, module_07 gap 6.

**Scope.**

1. `ract provenance list [--json]` — lists all indexed artifacts (SQLite).
2. `ract provenance inspect <path> [--json]` — full sidecar + registry
   snapshot dump.
3. `ract provenance export <path> [--out <file>]` — writes a single JSON
   *audit bundle*: sidecar + parent-chain sidecars + assumption-registry
   snapshot + independence-lint result at export time.
4. Every provenance verb supports `--json`.

**Bar raise past flagged.** Flagged only asked for list/inspect; this module
also defines the audit-bundle export format — a third party can verify an
entire chain end-to-end from one file.

**Definition of Done.**

- `pytest -q tests/test_provenance_cli.py` — 12 tests green (each verb, each
  `--json`, empty state, tampered sidecar).
- An exported bundle for a 3-parent chain verifies fully offline (chained
  into the module_02 offline verifier test).
- `docs/PROVENANCE.md` updated with the bundle schema.
- Full suite green.

### module_05 — Benchmark: multi-task honest sweep

**Origin.** v0.3 module_04 gaps 1, 2, 3, module_07 gap 3.

**Scope.**

1. Extend `evals/benchmarks/refactor-token-usage/` (rename to
   `evals/benchmarks/loop-termination/`) with **≥5 tasks**:
   - `refactor` (existing, passes iter 1).
   - `converge-2` (passes on iter 2 — mocked convergence).
   - `converge-4` (passes on iter 4 — worst case just under budget=5).
   - `budget-exhaust` (never converges — both contender and naive hit budget).
   - `adversarial-false-negative` (a valid solution the milestone detector
     wrongly rejects — naive wins because contender false-negatives). This
     task **must exist** and its "contender loses" result must be reported
     honestly.
2. Report includes an aggregate table (mean tokens, wins, ties, losses per
   configuration) and a `"When does the contender NOT win?"` section that
   names the losing tasks.
3. CI `benchmark` job (from v0.3 module_06) runs the sweep and uploads
   the report artifact.

**Bar raise past flagged.** Flagged asked for ≥3 tasks and an honest section.
This module raises to ≥5 tasks including an adversarial false-negative that
the contender must lose, and demands the honest section include the loss.

**Definition of Done.**

- `evals/benchmarks/loop-termination/report.md` and `report.json` are
  committed and reflect a real run of the 5 tasks.
- `tests/test_benchmark_gate.py` asserts: contender wins ≥3 of 5,
  adversarial-false-negative is a reported loss, and the report file
  parses.
- CI `benchmark` job runs the sweep (workflow updated).
- Full suite green.

### module_06 — Independence auto-derived + pre-commit hook

**Origin.** v0.3 module_02 gap 2, module_06 gaps 2 and 4.

**Scope.**

1. `ALLOWED_IMPORT_ROOTS` in `tests/test_public_provenance.py` becomes
   **derived at test time** from `pyproject.toml`'s `[project.dependencies]`
   plus a small hard-coded stdlib pin. The test fails if a declared
   dependency lacks a plausible top-level module OR if `src/` imports a
   root not in the derived set.
2. `.pre-commit-config.yaml` runs: ruff, ruff-format check, mypy on `src/`,
   pytest quick tier (`pytest -q -k "not slow"`), independence lint, config
   lint (from module_01), and hygiene lint.
3. CI runs the same hooks so drift between local and CI is impossible.
4. Rename tracked `ract.yaml` → `ract.yaml.example`; remove `ract.yaml` from
   `.gitignore` OR add a comment explaining the tracked-example pattern.

**Bar raise past flagged.** Flagged asked for auto-derivation and a hook;
this module additionally makes CI run the same hooks and closes the
`ract.yaml` gitignore inconsistency.

**Definition of Done.**

- Adding a top-level import of a package not in `pyproject.toml` and not in
  the stdlib set fails `pytest -q tests/test_public_provenance.py`.
- Adding a bogus dependency to `pyproject.toml` that no import uses fails
  the same test with a distinct error.
- `pre-commit run --all-files` exits zero on the current tree.
- CI `hooks` job runs `pre-commit run --all-files` and is green.
- `ract.yaml.example` is the tracked template; `ract.yaml` behavior in
  `.gitignore` documented.
- Full suite green.

### module_07 — Executor concurrency: real serialization proof

**Origin.** v0.3 module_03 gap 4.

**Scope.**

1. Add threaded test: two threads race to write the same output_path via
   `Executor.write_artifact`. Assert exactly one succeeds, one raises a
   distinguishable `ExecutorContention` (or existing equivalent).
2. Add threaded test: 10 threads write to 10 distinct paths — all succeed,
   all sidecars valid.
3. If the executor does NOT currently serialize same-path writes,
   implement it (SQLite `BEGIN IMMEDIATE` on the provenance index, or a
   `fcntl`/`msvcrt` file lock on the target path).
4. Document the concurrency guarantee in `docs/ARCHITECTURE.md`'s
   "Failure modes and concurrency" section, replacing the current
   qualitative claim with the exact primitive used.

**Bar raise past flagged.** Flagged asked for a serialization test; this
module also implements the primitive if missing and documents it exactly.

**Definition of Done.**

- `pytest -q tests/test_executor_concurrency.py` — 4 tests green
  (same-path race, distinct-path parallelism, 10-thread stress, contention
  error is distinguishable).
- ARCHITECTURE.md concurrency section names the exact primitive.
- Full suite green.

### module_08 — v0.3.1 close

**Scope.**

1. CHANGELOG `[0.3.1]` entry summarizing every module's delta.
2. README Verify section updated to show `ract provenance verify --strict`
   (offline path).
3. VERSION + `pyproject.toml` + `src/ract/__init__.py` → `0.3.1`.
4. `test_version.py` sweep (release-shape + VERSION cross-check) still green.
5. `docs/ROADMAP.md` updated: mark hardened items done; carry a fresh
   distance-to-excellent list.
6. Tag `v0.3.1` on the final commit.
7. Final honest-gap log — what is still shallow after this pipeline.

**Definition of Done.**

- `git describe --tags --exact-match HEAD` returns `v0.3.1`.
- `python -c "import ract; print(ract.__version__)"` prints `0.3.1`.
- CHANGELOG entry present.
- README verify section shows the offline path.
- Full suite green.

---

## Cadence and watchdog

- **Cadence mode:** per-sub-task. Same as v0.3.
- **Bar policy:** DoD is the floor; log flagged gaps at each module close.
- **Watchdog:** Cron (CronCreate). The end-of-turn pulse and long-cycle
  re-anchor are cron-driven. Same discipline as `watchdog_SKILL.md`, cron
  delivery instead of `.ps1`.
- **Advance rule:** module boundaries advance on the resume pulse reading
  `active_module` from `build_state.md`, not on operator green-light. The
  operator is the designer + course-corrector, not the per-module gate.

---

## Signals checklist (final gate before v0.3.1 tag)

- [ ] All eight modules DONE with verifiable DoD met.
- [ ] `v0.3.1` tag exists.
- [ ] `VERSION`, `pyproject.toml`, `__init__.py` all = `0.3.1`.
- [ ] `ruff check`, `mypy`, `pytest -q` all clean.
- [ ] CHANGELOG `[0.3.1]` entry present.
- [ ] `pre-commit run --all-files` clean.
- [ ] Benchmark sweep report committed with adversarial-false-negative
      loss visible.
- [ ] Sidecars from a v0.3.1 run verify offline.
- [ ] Provenance CLI complete: verify / list / inspect / export, all with
      `--json`.
- [ ] Fresh honest-gaps log carried into `docs/ROADMAP.md`.

If any signal fails, module_08 is not done. No shortcuts.
