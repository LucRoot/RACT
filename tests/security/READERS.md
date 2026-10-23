# Workspace readers under hostile files (B-075)

Each row is a reader that loads a file a cloned repository can ship. The tests are in `test_workspace_readers_hostile.py`. Status is what the run shows. Every finding below was a strict expected failure until S-035 fixed it; those cases are normal tests now.

| Reader | File | What the test shows | Status |
|---|---|---|---|
| `refactor_ledger` | `.ract/refactor_ledger.json` | Seven hostile cases (oversize, not JSON, wrong type, huge number, control text, widening key) and a directory in place of the file; a symlink out of the project | holds since S-035 (was B-075 FOUND: json errors and wrong types escaped; a shipped `allow_debt_override` was read; control text kept; symlink followed). A stored threshold is read only when it is stricter than the default |
| `memory_arena` | `.ract/memory/<session>.json` | Oversize, not JSON, wrong types, a hostile key; a directory in place of the file; a symlink out of the project | holds since S-035 (was B-075 FOUND: wrong-type items escaped as TypeError or ValueError; symlink followed); a wrong shape is now the documented `MemoryArenaError` |
| `reasoning.configured_default` | `ract.yaml` | Oversize, not YAML, wrong types, a control character in the effort value; a directory in place of the file | holds (predicted) |
| `error_memory` | `.ract/error_memory.jsonl` | A non-JSON line, an oversize line, a directory in place of the file; a number line, an object without `pattern`, a control character and bidi override in `pattern` | holds since S-035 (was B-075 FOUND: a number line and an object without `pattern` escaped from summarize; raw ESC and bidi kept). Lines are read one by one, so one bad line no longer loses the others |
| `session_listing` | `.ract/sessions/<id>.json` | Oversize, not JSON, wrong types, a directory in place of the file; a bidi override and ESC in `intent` | holds; the bidi case was a strict expected failure until B-077 (`e57678b`), now a normal test |
| `sandbox_env.allowlist` | `.ract/sandbox_env.allowlist` | Oversize line, not JSON, a number, a JSON list; a directory in place of the file | holds since S-035 (was B-075 FOUND: a directory raised IsADirectoryError, not the documented refusal) |
| `ract_runner._configured_budget` | `ract.yaml` (token_budget) | Oversize, wrong shapes, a directory in place of the file | holds (predicted) |
| `assumptions_wal` | `.ract/wal/assumptions.wal` | A garbage line and an oversize file (refused or skipped); a directory in place of the file | holds since S-035 (was B-075 FOUND: a directory let PermissionError escape); a non-object line and non-UTF-8 bytes are `WalCorruptError` too |
| `handshake_registry` | `.ract/handshakes.json` | Non-list roots, an oversize file, a directory in place of the file; a non-object item and an unknown key; a shipped `approved` item must not widen the manifest | holds since S-035 (was B-075 FOUND: wrong items raised TypeError; a shipped approval widened the manifest). An approval widens only when this machine recorded it, in the user state directory |
| `session_config` | `session.json` | Not JSON, a list, a number | holds since S-035 (was B-075 FOUND: JSONDecodeError and TypeError escaped); the refusal is `SessionConfigUnreadable` |
| `trust_items` | `.ract/hooks/*.json` | Bad hook files listed as unreadable; a directory in place of a hook file; a command with ESC and bidi override (checked on `TrustItem.line()`, the printed form) | holds. The raw `detail` keeps the ESC and bidi on purpose (S-034: the digest uses the raw fields); the printed line is escaped |

## Not yet covered

These readers are on the B-075 list and have no test.

- `cli_toggles`, `workspace_state`: no workspace file is read at the entry point. `cli_toggles` reads `~/.ract/session.json` in the user's home; `workspace_state` only renames `.rack` to `.ract`, and its symlink case needs a privilege. Listed here so the omission is visible.

## Broken-copy checks (one per reader that passes)

Each check copies `src/ract` and the test folder into a scratch project, breaks one line of the reader there, and runs the reader's test against that copy. Each broken copy fails its test; the real code passes it.

- `session_listing`: `except (OSError, ValueError)` narrowed to `OSError` (a not-JSON session escapes): 1 failed.
- `sandbox_env.allowlist`: the non-string refusal removed: 2 failed.
- `reasoning.configured_default`: the root-type check removed: 2 failed.
- `handshake_registry` roots: the non-list return removed: 2 failed.
- `assumptions_wal`: the middle-line refusal raises `ValueError` instead of `WalCorruptError`: 1 failed.

The `assumptions_wal` garbage case now uses two bad lines, so the first is a middle line; a single bad line is a truncated tail and is tolerated by design.

## Prediction status

The strict expected failures were predicted from reading the code and confirmed by the run; none XPASSed before S-035, and each XPASSed after its fix, before its markers were removed. The two symlink cases (`refactor_ledger`, `memory_arena`) are skipped on this account; they are normal tests now and run on Linux (B-046) or an elevated Windows run.
