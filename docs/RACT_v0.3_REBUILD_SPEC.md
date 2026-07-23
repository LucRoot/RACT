# RACT v0.3 Rebuild Spec: From "Handled" to "Convincing"

**Version:** 0.1 (draft)
**Prepared for:** Lucas Root
**Status:** Design spec for the next rebuild iteration
**Sacred:** Rootknot — the concept, the brand, and the signed provenance capability.

---

## 0. Preamble

The v0.2.0 rebuild addressed the surface-level tells in the two senior-architect critiques:

- Runtime state was removed from the repo root.
- The README was rewritten to a technical pitch under 500 words, with bio/book content moved to `AUTHOR.md`.
- The Architecture doc was replaced with a system diagram + boundaries/contracts.
- A signed `Rootknot` capability with `verify()` replaced the presence-checked sentinel.
- An `AssumptionRegistry` with violation propagation replaced the `Rooted[T]` quirk.
- A reproducible eval harness with three tasks and committed run reports landed under `evals/`.
- CI was pointed at core coverage and eval smoke tests.
- The `v0.2.0-rc1` tag was cut.

That gets the repo from "builder's dump" to "plausible architect's repo." The remaining work is to close the gaps the critiques both flagged as depth signals:

1. **Legacy author markers are still in source and skill templates.** The README is clean, but `__root_author__`, `__ract_name__`, and `_ROOT_KNOT = object()` still appear across `src/ract/*.py` and the skill JSON files. A senior scanning the tree will see the old vocabulary and conclude the decoupling is cosmetic.
2. **There is no public separation statement.** `docs/internal/PROVENANCE.md` was deleted (correctly), but nothing replaced it at the public boundary. The provenance story now lives only in code (`Rootknot`) and in `docs/ADRs/ADR-0001-provenance-anchored-artifacts.md`. A senior architect wants a single public file that says "here is exactly how RACT stays independent of private systems."
3. **The Architecture doc lacks failure modes and concurrency.** It has boundaries and contracts, but no "what happens when..." section. Seniors read architecture for the failure model: malformed JSON, provider disagreement, repeated rejection by the milestone oracle, concurrent tool execution.
4. **The eval harness is a smoke test, not a proof.** Three tasks that pass is good. A benchmark that shows the milestone-driven recursion loop beating a naive baseline on a real dimension (tokens spent, wall time, edit correctness) is the depth signal. Cursor and Claude Code comparisons are still claims until a reproducible benchmark says otherwise.
5. **Rootknot is correct but not yet ergonomic.** It signs and verifies. It does not yet persist sidecars, rotate keys, expose a CLI verifier, or survive copy/paste of artifacts across workspaces. Those are the next depth signals.

This spec turns those gaps into a finite set of modules, each with a verifiable Definition of Done.

---

## 1. What Stays Sacred

**Rootknot.** The word, the concept, and the signed provenance capability remain the philosophical spine of the tool. The mechanism can be improved (persistence, key rotation, CLI inspection), but the rootknot is not renamed, demoted, or replaced.

**What changes around it:**

- The legacy `_ROOT_KNOT = object()` sentinel is removed from all source files and skill templates. It has done its deprecation window.
- Author identity is removed from source files and templates; it lives only in `AUTHOR.md`, package metadata, and the `--about` footer.
- `Assumed[T]` is the public vocabulary for assumption-bound values. `Rooted[T]` is retired everywhere except the git history.

---

## 2. Design Principles for v0.3

1. **Identity is metadata, not vocabulary.** The source code speaks in domain terms: `Rootknot`, `Assumption`, `Plan`, `TerminationCause`. The author speaks in `AUTHOR.md`.
2. **Every public claim is reproducible.** If the README says RACT is more efficient or safer than a naive loop, there is a committed benchmark report that proves it.
3. **Architecture is failure-mode first.** The ARCHITECTURE.md describes what breaks and how the system refuses to break silently.
4. **Rootknots are inspectable.** A human reviewer can look at any artifact and see its provenance without running the full tool.
5. **Runtime state never lives in the repo.** Sessions, coverage files, approval queues, and benchmark scratch dirs all live in XDG dirs or `_BUILD/`.

---

## 3. Module Breakdown

### Module 1 — Decouple identity from source and templates

**Goal:** Remove `__root_author__`, `__ract_name__`, and `_ROOT_KNOT = object()` from every source file and skill template.

**Current state:** These markers still appear across `src/ract/*.py` and in `src/ract/builtin_skills/*.json` templates.

**Path:**

1. Run a scripted removal across `src/ract/**/*.py`.
2. Update skill JSON templates to reference `Assumed[T]` and omit author markers.
3. Update `tests/test_signature_guardian.py`, `tests/test_signature_survival.py`, and any other tests that assert the markers. They should either be retired or changed to assert that source files **do not** contain author markers (the inverse test becomes the new gate).
4. Update `CONTRIBUTING.md` to state the new convention explicitly.
5. Update `pyproject.toml` `tool.ruff.lint.ignore` to remove the `E402` exception if it was only there for markers.

**Definition of Done:**

```bash
grep -R "__root_author__\|__ract_name__\|_ROOT_KNOT = object()" src/ tests/ || echo "clean"
```

returns clean, and the full test suite is still green.

**What the senior architect appreciates:** They grep for the old markers and find nothing. The source now reads like a system, not a signature campaign.

---

### Module 2 — Public provenance and separation statement

**Goal:** Create `docs/PROVENANCE.md` as the authoritative public statement of how RACT stays independent of private systems and how every artifact is bound to a rootknot.

**Current state:** The story is split between ADR-0001 and code. There is no single public document.

**Path:**

1. Write `docs/PROVENANCE.md` with four short sections:
   - **What a Rootknot attests:** plan step, assumption, generator, parent artifacts, artifact digest, signature.
   - **How RACT stays independent of [REDACTED] and other private systems:** no proprietary code, no private endpoints, no shared state.
   - **How to verify a Rootknot without the tool:** CLI command (see Module 5), sidecar format, public-key location.
   - **What happens if a Rootknot is missing or invalid:** loop halts with `TerminationCause.PROVENANCE_VIOLATION`.
2. Update `docs/ARCHITECTURE.md` to reference `docs/PROVENANCE.md` in the provenance contract bullet.
3. Add a lint test `tests/test_public_provenance.py` that asserts `docs/PROVENANCE.md` exists, contains the key phrases, and that no source file imports from a `[REDACTED]` module.

**Definition of Done:** `docs/PROVENANCE.md` exists, is under 800 words, and the lint test passes.

**What the senior architect appreciates:** One file answers the "who owns this?" and "how do I audit it?" questions without them having to read source.

---

### Module 3 — Failure modes and concurrency in architecture

**Goal:** Add a "Failure modes and concurrency" section to `docs/ARCHITECTURE.md`, plus two ADRs: config-schema versioning and MCP/tool-execution boundaries.

**Current state:** ARCHITECTURE.md has boundaries and contracts but no failure-mode narrative.

**Path:**

1. Extend `docs/ARCHITECTURE.md` with:
   - **Malformed plan JSON:** `PlanValidator` rejects; loop halts with `T6` (provider fault) or `T2` (regression) depending on context.
   - **Provider disagreement / timeout:** `Router` falls back through the configured chain; if all fail, loop halts with `T7`.
   - **Milestone oracle rejects three plans in a row:** loop halts with `T5` (handshake block) or escalates to operator review.
   - **Concurrent tool execution:** MCP tools are run serially within a plan step unless explicitly marked idempotent; workspace writes are serialized by the executor chokepoint.
   - **Workspace mutation outside the root:** `authorize_action` refuses T3 actions; T2 requires handshake.
2. Write `docs/ADRs/ADR-0008-ract-yaml-versioning.md`:
   - Context: config schema must evolve without breaking existing projects.
   - Decision: `ract.yaml` carries `schema_version`; unknown versions are rejected; migrations are explicit scripts under `scripts/migrations/`.
   - Rejected alternatives: silent upgrades, JSON Schema only, no versioning.
3. Write `docs/ADRs/ADR-0009-mcp-tool-execution-boundaries.md`:
   - Context: MCP tools can mutate workspace, network, and shell.
   - Decision: MCP calls are routed through `authorize_action`; arguments are validated against the tool's declared schema; destructive calls require handshake.
   - Rejected alternatives: trust-all, prompt-level filtering, post-hoc logging only.

**Definition of Done:** ARCHITECTURE.md failure-mode section is present, two new ADRs are committed, and `tests/test_public_docs.py` passes.

**What the senior architect appreciates:** They see that you have thought about what breaks before it breaks. The ADRs show rejected alternatives, which is the strongest signal that a decision was made rather than defaulted.

---

### Module 4 — Benchmark harness: prove the loop is better than naive

**Goal:** Add a `evals/benchmarks/` directory with a reproducible benchmark that compares the milestone-driven recursion loop against a naive fixed-iteration baseline on a concrete dimension.

**Current state:** Three eval tasks prove correctness. They do not prove efficiency or superiority over a simpler approach.

**Path:**

1. Pick one dimension: **tokens spent to reach a passing state** on a multi-step refactoring task.
2. Create two runners:
   - `RACTLoopRunner`: uses `src/ract/core/loop.py` with milestone termination.
   - `NaiveLoopRunner`: same executor, but runs for exactly N iterations regardless of milestone state.
3. Create `evals/benchmarks/refactor-token-usage/` with:
   - `task.py`: the refactoring task (e.g., "extract validation and discount logic from `process_order`).
   - `baseline.py`: the naive runner.
   - `contender.py`: the RACT loop runner.
   - `report.py`: runs both, collects token usage and pass/fail, writes `evals/benchmarks/refactor-token-usage/report.json` and `report.md`.
4. Add a CI job `benchmark` that runs the benchmark on every PR and fails if the contender is not strictly better on the chosen dimension.
5. Update `README.md` "What makes RACT different" to reference the benchmark report instead of claiming superiority in prose.

**Definition of Done:**

```bash
python evals/benchmarks/refactor-token-usage/report.py
```

produces `report.md` showing RACT loop uses fewer tokens than the naive baseline, and the benchmark CI job passes.

**What the senior architect appreciates:** A benchmark is a claim with a receipt. They no longer have to trust marketing; they can read the report and reproduce it.

---

### Module 5 — Rootknot ergonomics and persistence

**Goal:** Make rootknots auditable outside the tool: sidecar files, SQLite index, key rotation, and a CLI verifier.

**Current state:** `Rootknot.sign()` and `Rootknot.verify()` work in memory. There is no persistence or inspection CLI.

**Path:**

1. **Sidecar format.** When the executor writes an artifact at `src/foo.py`, also write `.ract/provenance/src/foo.py.rootknot.json` containing the canonical rootknot fields and the signature (hex-encoded).
2. **SQLite index.** Maintain `.ract/provenance/rootknots.db` with tables for `rootknots`, `assumptions`, and `artifacts`. This is the fast lookup path; sidecars are the human audit path.
3. **Key rotation.** `SessionKey.load_or_create(session_id)` creates a key per session. Add `SessionKey.rotate(session_id)` that archives the old key and generates a new one, with a `rotated_at` record in the SQLite index. Old rootknots remain verifiable with archived keys.
4. **CLI verifier.** Add `ract provenance verify <path>` that loads the sidecar and verifies the signature against the stored public key.
5. **Property tests.** Extend `tests/property/test_rootknot_invariants.py` to assert:
   - RK-1 holds after every simulated write.
   - Rotating a key does not invalidate previously signed rootknots.
   - A tampered sidecar fails verification.

**Definition of Done:**

```bash
ract provenance verify src/foo.py
```

prints `valid` for an untouched artifact and `invalid` for a tampered one, and the property tests pass.

**What the senior architect appreciates:** The rootknot is no longer a code abstraction; it is an auditable artifact with a human-readable sidecar and a CLI. That is what "shipped signed protocols" looks like.

---

### Module 6 — Repo hygiene finishing

**Goal:** Close the remaining hygiene tells.

**Current state:** `.ract_sessions/` exists at root but is gitignored. `tests/fixtures/` does not exist. Branch protection is not configured (repo-level GitHub setting).

**Path:**

1. **Runtime state.** Ensure every runtime file (sessions, approval queues, coverage data, benchmark scratch) writes to either XDG state/cache or a single `_BUILD/` directory that is already gitignored. If `.ract_sessions/` must stay at root for compatibility, document why in `docs/ARCHITECTURE.md`.
2. **Fixtures convention.** Create `tests/fixtures/` and move any remaining test JSON files there (`tests/test_report.json` if it is a fixture). Update tests that load it. Add a lint test that asserts no JSON/JSONL fixtures live at repo root.
3. **Branch protection.** Document the required GitHub settings in `docs/CONTRIBUTING.md` or `docs/GOVERNANCE.md`:
   - PRs required to `main`.
   - CI must pass.
   - One review required.
   - Force-push disabled.
4. **CI hardening.** Add a CI step that runs `ruff`, `mypy`, the full test suite, the eval smoke, and the benchmark. Upload the benchmark report as an artifact.

**Definition of Done:**

```bash
find . -maxdepth 1 -type f \( -name '*.json' -o -name '*.jsonl' \)
```

returns nothing, and the documented branch-protection rules are applied in the GitHub repo settings.

**What the senior architect appreciates:** The repo root is clean, the history is protected, and the CI is the source of truth for quality.

---

### Module 7 — README and version polish

**Goal:** Finalize the public-facing surface and cut `v0.3.0`.

**Current state:** README is clean but still references claims that will be backed by the benchmark after Module 4.

**Path:**

1. Update `README.md`:
   - Replace generic superiority claims with references to `evals/benchmarks/refactor-token-usage/report.md`.
   - Add a "Verify" section: `ract doctor`, `ract provenance verify <path>`, and `pytest -q`.
   - Keep it under 500 words.
2. Update `CHANGELOG.md` with v0.3.0 entries.
3. Bump version in `pyproject.toml` and `src/ract/__init__.py` to `0.3.0`.
4. Tag `v0.3.0`.

**Definition of Done:** `v0.3.0` tag exists, README is under 500 words, every claim in it references a command or a committed report, and the full suite is green.

---

## 4. Signals Checklist for the v0.3 Review

After the rebuild, the senior architect scanning the repo should find:

- [ ] No `__root_author__`, `__ract_name__`, or `_ROOT_KNOT = object()` in `src/` or skill templates.
- [ ] `docs/PROVENANCE.md` exists and explains public separation + rootknot verification.
- [ ] `docs/ARCHITECTURE.md` includes a failure-mode and concurrency section.
- [ ] `docs/ADRs/` contains 9 numbered ADRs (7 existing + config versioning + MCP boundaries).
- [ ] `evals/benchmarks/` contains a reproducible benchmark with a baseline comparison and committed report.
- [ ] Rootknot sidecars and SQLite index are written by the executor.
- [ ] `ract provenance verify <path>` works.
- [ ] `tests/fixtures/` exists and no fixtures live at repo root.
- [ ] CI runs lint, type-check, tests, eval smoke, and benchmark.
- [ ] README is under 500 words and every claim points to a command or report.
- [ ] `v0.3.0` tag exists.

---

## 5. Why This Closes the Critique

The two critiques converge on one message: the repo needs to read like the product of someone who has paid for their scars. The v0.2.0 rebuild removed the obvious tells. The v0.3.0 rebuild adds the depth signals:

- **No vanity in source.** Author identity is metadata.
- **Public separation statement.** [REDACTED] never appears, and the independence claim is documented.
- **Failure-mode architecture.** The system is described by what it refuses to do.
- **Benchmarked superiority.** The loop is not just claimed to be better; it is measured against a baseline.
- **Auditable rootknots.** The sacred concept now has a persistence layer and a CLI.

That is the genre change from "builder's repo" to "architect's repo."
