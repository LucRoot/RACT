---
session_events_version: 1
---

# RACT session events

The session event stream is what a running session tells the outside world.
The terminal renderer draws it, `--output-format stream-json` prints it, and
editors and scripts read it through the SDK. All three see the same events
in the same order.

This is a different stream from the trace log described in
[`EVENTS.md`](EVENTS.md). The trace log is the hash-chained audit record of
what happened in a run. Session events are the live view of a session for a
person or a program. Some facts appear in both: a tool call is a
`tool.invocation.*` trace event and a `tool.call.*` session event.

Status: version 1, proposed with ADR-0047 D7. The kinds for tool calls,
diffs and approvals are defined now; until the tool layer exists only the
fake model server produces them, in tests.

## The envelope

Every event is one JSON object:

| Field | Type | Meaning |
|---|---|---|
| `v` | integer | Schema version of this document. Currently `1`. |
| `seq` | integer | Position in the session stream, starting at 1, no gaps. |
| `t` | string | UTC time, RFC 3339 with milliseconds, for example `2026-10-21T18:02:11.482Z`. |
| `session` | string | Session id. |
| `turn` | integer or null | Turn number within the session, starting at 1. Null for events outside a turn. |
| `kind` | string | One of the kinds below. |
| `data` | object | Fields for the kind. |

## Rules

- **Order.** `seq` is the order. Consumers never reorder by `t`.
- **Additive.** Within a version, new kinds and new optional fields may be
  added. A consumer ignores kinds and fields it does not know. Removing or
  renaming anything is a new version.
- **No secrets.** Values are redacted before an event is created. An event
  never carries an API key, a token, a passphrase or the value of an
  environment variable.
- **No tracebacks.** Errors carry a sentence, a hint and a log path. The
  traceback goes to the log file named in the event.
- **Text is safe to print.** Text fields are valid UTF-8, split only at
  character boundaries. Control characters other than newline and tab are
  replaced, so an event can be printed to a terminal without risk.
- **Paths** are relative to the workspace root, with forward slashes.
- **Sizes** are bounded: a text delta is at most 4 KiB, a tool result
  summary at most 200 characters. Full results live in the trace.

## Kinds

### Session

| Kind | `data` fields |
|---|---|
| `session.started` | `workspace` (string, display name only), `model` (string), `provider` (string), `branch` (string or null), `mode` (`default`, `plan`, `auto-accept`, `unrestricted`), `tier3` (`off`, `ask`, `allowlist`, `unrestricted`, `suspended`), `context_limit` (integer or null) |
| `session.resumed` | the same fields as `session.started`, plus `resumed_from` (session id) and `turns` (integer, turns already in the session) |
| `mode.changed` | `mode`, `tier3`, `by` (`operator`) |

### Turn

| Kind | `data` fields |
|---|---|
| `turn.started` | `input` (string, what the operator typed, redacted), `queued` (boolean, true when it was typed during the previous turn) |
| `turn.finished` | `outcome` (`done`, `failed`, `interrupted`, `budget`, `refused`), `duration_ms` (integer), `verdict` (string, one sentence written by the harness, never by the model), `changed` (list of paths), `checkpoint` (string or null) |

### Model output

| Kind | `data` fields |
|---|---|
| `agent.text.delta` | `text` (string) |
| `agent.reasoning.delta` | `text` (string). Renderers show it dimmed and collapsed. It never becomes answer text. |
| `agent.heartbeat` | `waiting_on` (`model`, `tool`, `approval`, `workspace`), `elapsed_ms` (integer), `detail` (string, short, for example `"first token not yet received"`) |

`agent.heartbeat` comes from a timer, every 2 seconds while the session waits
on anything. It is how a renderer keeps a sign of life on screen when a slow
local model has not produced a token yet.

### Tools

| Kind | `data` fields |
|---|---|
| `tool.call.started` | `id` (string), `tool` (string), `tier` (`T0` to `T3`), `summary` (string, one line, for example `read_file src/app.py:1-60`), `repairs` (list of strings, for example `["repaired: path -> file_path"]`), `rung` (string, how the call was read: `native`, `tag`, `envelope`, ...) |
| `tool.call.finished` | `id`, `ok` (boolean), `duration_ms` (integer), `summary` (string), `truncated` (boolean), `hint` (string or null, set when `ok` is false) |

### Changes

| Kind | `data` fields |
|---|---|
| `diff.proposed` | `path` (string), `hunks` (list of `{id, header, added, removed, text}`), `tier` (`T1` or `T2`) |
| `diff.reviewed` | `path`, `hunk` (id), `decision` (`accepted`, `rejected`, `edited`) |
| `change.applied` | `paths` (list), `checkpoint` (string), `skipped` (list of `{path, reason}`) |

### Approvals

| Kind | `data` fields |
|---|---|
| `approval.requested` | `id` (string), `tier` (`T2` or `T3`), `action` (string, the exact command or change, control characters escaped), `reason` (string, labeled as the model's), `facts` (object: `cwd`, `network`, `sandbox_enforced`, `env_names`, `limits`), `choices` (list of `once`, `session`, `always`, `deny`) |
| `approval.resolved` | `id`, `choice` (one of `choices`, or `denied` when nobody could answer), `by` (`operator-tty`, `signed-record`, `unattended`) |

No model output can produce `approval.resolved` (ADR-0048 Invariant A-1).

### Cost and context

| Kind | `data` fields |
|---|---|
| `cost.updated` | `tokens_in` (integer), `tokens_out` (integer), `by_purpose` (object, for example `{"turn": 3400, "probe": 12}`), `total_usd` (number or null when unknown), `context_used` (integer or null), `context_limit` (integer or null) |

### Errors and notices

| Kind | `data` fields |
|---|---|
| `error.surfaced` | `message` (string, one or two sentences), `hint` (string, never empty: the next action or the exact command), `workspace` (string, one line, for example `"no files were changed"`), `log` (string or null, path of the log with details) |
| `notice` | `level` (`info` or `warning`), `text` (string) |

## Headless mapping

- `--output-format stream-json` prints every event, one JSON object per
  line, in `seq` order.
- `--output-format json` prints one object at the end:
  `{"outcome", "verdict", "final_text", "changed", "cost", "events_path"}`.
- `--output-format text` prints the answer text only.

Exit codes: 0 done, 1 the task failed or its tests failed, 2 usage or
configuration error, 3 refused by policy or tier, 4 a budget was exhausted,
5 interrupted, 6 the provider was unavailable.

## Example

```json
{"v":1,"seq":1,"t":"2026-10-21T18:02:10.001Z","session":"s-0192","turn":null,"kind":"session.started","data":{"workspace":"calc","model":"fake-coder","provider":"local","branch":"main","mode":"default","tier3":"off","context_limit":32768}}
{"v":1,"seq":2,"t":"2026-10-21T18:02:11.482Z","session":"s-0192","turn":1,"kind":"turn.started","data":{"input":"where is the config loader?","queued":false}}
{"v":1,"seq":3,"t":"2026-10-21T18:02:13.483Z","session":"s-0192","turn":1,"kind":"agent.heartbeat","data":{"waiting_on":"model","elapsed_ms":2001,"detail":"first token not yet received"}}
{"v":1,"seq":4,"t":"2026-10-21T18:02:14.210Z","session":"s-0192","turn":1,"kind":"agent.text.delta","data":{"text":"The config loader is "}}
{"v":1,"seq":5,"t":"2026-10-21T18:02:14.950Z","session":"s-0192","turn":1,"kind":"turn.finished","data":{"outcome":"done","duration_ms":3468,"verdict":"Answered from 0 files; no files changed.","changed":[],"checkpoint":null}}
```
