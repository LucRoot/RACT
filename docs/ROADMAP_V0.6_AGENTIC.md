# RACT v0.6 agentic roadmap

Running record of the v0.6 work that turns RACT into a full agentic coding
tool: what shipped, what is next, and what was decided. Updated with every
commit on `feat/interactive-session-and-setup-fixes`. Sections 1 to 8 follow
the numbering of the v0.6 brief.

## Status at a glance

| Section | Area | State |
|---|---|---|
| 0 | Interactive session, setup and config fixes | Shipped |
| 1 | Filesystem execution: tool layer, per-step agent loop, review, undo | Design proposed (ADR-0047), waiting for operator ratification. Tool-call extraction shipped. |
| 2 | Tier 2 and 3: operator grant, commands, tests, git, network, approvals, trust | Design proposed (ADR-0048), waiting for operator ratification |
| 3 | Session UX | Baseline measured; event stream schema v2 and the first event-driven turns shipped |
| 4 | Project memory, instructions, context | Not started |
| 5 | Extensibility (MCP, skills, hooks, subagents, SDK) | Not started |
| 6 | Model and provider layer | Not started |
| 7 | Verification, review, safety | Not started |
| 8 | Editor, CI, distribution | Not started |

## Shipped

| Change | What |
|---|---|
| Fake model server (B-004) | Scripted fake OpenAI-compatible model server for tests and walkthroughs (`tests/fixtures/`). |
| Tool-call extraction ladder | `ract.tool_calls`: tool-call extraction ladder, unparsed-markup refusal, truncation explanation, unique-only repairs, loop guards. Pure; no caller until the agent loop lands. |
| UX baseline | Real-terminal walkthrough tooling (`tests/ux/`) and the UX baseline: 20 findings, 7 S1 defects and 2 steps not testable until the tool layer exists (`docs/ux/baseline/`). |
| ADR-0047, ADR-0048 | ADR-0047, ADR-0048, and the "v0.6 agentic execution amendment" in `docs/THREAT_MODEL.md`. Docs only. |
| Type and format fix | CI parity: `mypy --platform linux` type error fixed, nine files `ruff format` clean, `scripts/ci_parity.py`. |
| Tool-call amendments | Tool-call extraction amendments: duplicate JSON keys refused, `invalid_arguments` and `too_many_calls` outcomes, prose around parsed calls reported. |
| ADR details | ADR details (placeholder parent snapshot, hook environment, quoted calls under D9); gated UX steps marked. Docs only. |
| Loop-guard key | Loop-guard key uses canonical JCS (the canonical-path architecture gate caught `sort_keys=True`). |
| S-001 | One path resolver for model-supplied paths; the diff applier and artifact writer no longer accept `..` or outside paths. |
| S-013 | A failed turn no longer wedges the session. |
| S-011 stopgap | Runs never commit onto the operator's branch (stopgap until review before apply). |
| S-012 | `ract doctor` says what it checked and points at `--check-providers`. |
| CI parity script | `scripts/ci_parity.py` mirrors the CI lint and type job, with a drift test. |
| S-014 | Docs state that Windows has no line history or completion yet, and how Ctrl-C behaves during a turn. |
| ADR decision list | ADR additions: decisions list, unlock window, guided first grant, implementation slices, no-timer approvals, approval-fatigue metric, resume rule. Docs only. |
| S-011 overwrite guard | The in-place stopgap never overwrites working-tree content. |
| S-015, S-015a | Provenance reports unsigned files instead of implying signatures; docs and the site page say what is true today. |
| S-008 | `ract doctor` reports sandbox enforcement as it is in this build. |
| S-003 | Hook commands run with a scrubbed environment. |
| S-002 | Seven emitted trace event kinds registered, with a drift guard. |
| UX-21 | The sandbox scrub summary stays off the terminal. |
| S-016 | `.ract/` stays out of `git status`; `ract doctor` lists and prunes step branches. |
| Event schema v1 (B-012) | Session event schema version 1, for review. Docs only. |
| Terminal driver Ctrl-C | The terminal driver delivers Ctrl-C; the J6 baseline re-measured. |
| S-011b, S-011c | Each run starts from a snapshot of the working tree, so a dirty tree keeps isolation and later steps see earlier steps' files. The snapshot is bounded: 2 MiB per file, 2,000 untracked files, 20 s, with a notice naming what was left out. |
| S-018, S-018b, D-014 | Nothing under `.git/` or `.ract/`, no secret-shaped file and no `ract.yaml` reaches a model request (step target, context, retrieval, `ract fence`); skill names are one file name; `.env` template names allowed. |
| Event schema v2 (B-012) | Session event schema version 2: plan and step events, text channel, verification and provenance on each turn, retry, interrupt, queue, rewind and end events, streaming redaction, and the headless result `ract.result/1`. Docs only. |

## Next

1. Operator ratification of ADR-0047 and ADR-0048. Nothing in the tool layer
   or tier 3 is coded before it.
2. Defect fixes that do not wait for ratification, one commit each:
   the shared path resolver with its red-team tests (closes `..` in the diff
   applier and artifact writer); honest sandbox reporting in `ract doctor`,
   `THREAT_MODEL.md` and the README; scrubbed environment for hook commands;
   registering the trace event kinds that are emitted but missing.
3. Session event stream and plain renderer against the fake model server,
   built to schema version 2 (`docs/EVENTS_SESSION.md`).
4. First-run flow, UI toolkit ADR, input, commands, interrupts, modes and
   headless output, as far as they do not need the tool layer.

## Decisions waiting on the operator

The ADRs give each one with its rejected alternatives. Short form:

1. **Tier-3 governance (ADR-0048 D1 to D3).** `RACT_TIER_3_ENABLED` stays
   `False`. One project at a time can reach tier 3 through an Ed25519
   operator grant signed with a passphrase-protected key outside every
   workspace. This amends ADR-0012, which said only an ADR could open tier 3.
2. **Four existing defects (ADR-0048 R1 to R4).** Tier 2 should ask instead
   of running silently; handshake approvals should be signed; keys should
   leave `.ract/`; the production substrate loop should get a manifest,
   handshakes and a sandbox backend.
3. **Trust split for prompt injection (ADR-0048 D9).** Only `external`
   content (web, MCP, network-on command output, third-party gitignored
   paths) disables allowlist rules for the rest of a step.
4. **Review before apply (ADR-0047 D6).** Changes are proposed in a
   worktree, reviewed per hunk, then applied to the live tree with a
   checkpoint. Read-only work creates no worktree.
5. **Control files and executable configuration are tier 2 (ADR-0047 D3).**
6. **Windows posture (ADR-0048 D7).** Windows commands run with process
   limits and a scrubbed environment, reported as not confining the
   filesystem or network. A grant must say `sandbox: best_effort`. WSL2 and
   containers are the enforced paths.
7. **Unrestricted mode (ADR-0048 D6).** Exists only when a signed grant sets
   `max_mode: unrestricted`, and still asks for shell mode, remote git and
   anything after external content.

## Decided (defaults taken)

- Two ADRs. The tool layer and tier 3 answer different review questions.
- `..` segments are refused outright, even inside the root.
- Writes never follow symlinks.
- Edits, overwrites, deletes and moves need the file's current SHA-256.
- Files that are not clean UTF-8 can be read and cannot be edited.
- Budget exhaustion keeps the worktree for inspection and applies nothing.
- `--yolo` never changes the tier-3 mode and never answers an approval.
- `web_search` ships as an interface with no default provider.
- Native tool calling is detected with a visible probe, cached per provider
  and model, and overridable in `ract.yaml`.
- The extraction ladder treats a half-written call object as unparsed
  markup. A final answer that quotes a call object as an example costs one
  reformat request.
- The tool-call parser is allowlisted in the dead-code auction until the
  agent loop imports it.

## Baseline

- Phase 0 (interactive session and setup fixes): full suite excluding
  `tests/memory`: 3134 passed, 24 skipped, 0 failed.
- UX baseline (taken after the tool-call extraction ladder landed): 7 S1 defects, plus 2 steps not testable until the tool layer exists. The worst: a turn commits onto the
  user's branch and leaves the working file unchanged; Ctrl-C is ignored
  until the turn ends; one failed turn blocks every later one in the
  session. Details in `docs/ux/baseline/defects.md`.
- `mypy --platform linux` reported one type error at
  `src/ract/executor/steps.py:867` from the first round; fixed in the type and format fix above.

<!-- RACT 0.6 roadmap -->
