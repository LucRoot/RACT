# RACT v0.6 agentic roadmap

Running record of the v0.6 work that turns RACT into a full agentic coding
tool: what shipped, what is next, and what was decided. Updated with every
commit on `feat/interactive-session-and-setup-fixes`. Sections 1 to 8 follow
the numbering of the v0.6 brief.

## Status at a glance

| Section | Area | State |
|---|---|---|
| 0 | Interactive session, setup and config fixes | Shipped (`ed27155`) |
| 1 | Filesystem execution: tool layer, per-step agent loop, review, undo | Design proposed (ADR-0047), waiting for operator ratification. Tool-call extraction shipped (`85a56ca`) |
| 2 | Tier 2 and 3: operator grant, commands, tests, git, network, approvals, trust | Design proposed (ADR-0048), waiting for operator ratification |
| 3 | Session UX | Baseline measured (`b4230a1`); building starts with the event stream |
| 4 | Project memory, instructions, context | Not started |
| 5 | Extensibility (MCP, skills, hooks, subagents, SDK) | Not started |
| 6 | Model and provider layer | Not started |
| 7 | Verification, review, safety | Not started |
| 8 | Editor, CI, distribution | Not started |

## Shipped

| Commit | What |
|---|---|
| `109dc41` | Scripted fake OpenAI-compatible model server for tests and walkthroughs (`tests/fixtures/`). |
| `85a56ca` | `ract.tool_calls`: tool-call extraction ladder, unparsed-markup refusal, truncation explanation, unique-only repairs, loop guards. Pure; no caller until the agent loop lands. |
| `b4230a1` | Real-terminal walkthrough tooling (`tests/ux/`) and the UX baseline with 20 defects (`docs/ux/baseline/`). |
| this commit | ADR-0047, ADR-0048, and the "v0.6 agentic execution amendment" in `docs/THREAT_MODEL.md`. Docs only. |

## Next

1. Operator ratification of ADR-0047 and ADR-0048. Nothing in the tool layer
   or tier 3 is coded before it.
2. Defect fixes that do not wait for ratification, one commit each:
   the shared path resolver with its red-team tests (closes `..` in the diff
   applier and artifact writer); honest sandbox reporting in `ract doctor`,
   `THREAT_MODEL.md` and the README; scrubbed environment for hook commands;
   registering the trace event kinds that are emitted but missing.
3. Session event stream and renderer v1 against the fake model server.
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

- `ed27155`: full suite excluding `tests/memory`: 3134 passed, 24 skipped,
  0 failed.
- UX baseline at `85a56ca`: 9 S1 defects. The worst: a turn commits onto the
  user's branch and leaves the working file unchanged; Ctrl-C is ignored
  until the turn ends; one failed turn blocks every later one in the
  session. Details in `docs/ux/baseline/defects.md`.
- `mypy --platform linux` reports one type error at
  `src/ract/executor/steps.py:867` that predates this work.

<!-- RACT 0.6 roadmap -->
