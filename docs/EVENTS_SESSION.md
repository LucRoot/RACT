---
session_events_version: 2
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

Status: version 2, proposed with ADR-0047 D7. The kinds for tool calls,
diffs and approvals are emitted by real sessions (the plan, step and tool
events) as well as by the fake model server in tests. The headless result object
`ract.result/1` is defined at the end of this document, so the session
schema and the headless schema live in one place.

## Changes from version 1

Version 1 was reviewed (BOARD G-019) before any consumer existed and never
shipped. Version 2 adds:

- plan and step events (`plan.proposed`, `step.started`, `step.finished`),
  so a renderer can draw the step tracker with the plan's assumption and
  confidence;
- `channel` on `agent.text.delta` (`answer` or `artifact`);
- structured `verification` and `provenance` on `turn.finished`, and a
  one-line `workspace` state;
- `session.ended`, `agent.retry`, `turn.interrupting`, `input.queued`,
  `input.withdrawn` and `session.rewound`;
- the first-event facts for headless runs on `session.started`;
- `rule` on approvals, for the headless denial record;
- the streaming redaction rule, the direction rule, reserved kind names,
  exit code 143, the stdout and stderr rule, and `ract.result/1`.

Nothing from version 1 was removed or renamed.

## The envelope

Every event is one JSON object:

| Field | Type | Meaning |
|---|---|---|
| `v` | integer | Schema version of this document. Currently `2`. |
| `seq` | integer | Position in the session stream, starting at 1, no gaps. |
| `t` | string | UTC time, RFC 3339 with milliseconds, for example `2026-10-21T18:02:11.482Z`. |
| `session` | string | Session id. |
| `turn` | integer or null | Turn number within the session, starting at 1. Null for events outside a turn. |
| `kind` | string | One of the kinds below. |
| `data` | object | Fields for the kind. |

## Rules

- **Order.** `seq` is the order. Consumers never reorder by `t`.
- **Direction.** The stream is output only. Nothing a consumer writes back
  reaches the session through it. Approvals from an editor or the SDK need
  a separate, authenticated channel with its own ADR. This keeps ADR-0048
  Invariant A-1: no model output and no stream consumer can approve.
- **Additive.** Within a version, new kinds, new optional fields and new
  values of an enumerated field may be added. A consumer ignores kinds and
  fields it does not know, and treats an unknown enumerated value as the
  field's most cautious meaning (an unknown `outcome` is a failure).
  Removing or renaming anything is a new version.
- **No secrets.** An event never carries an API key, a token, a passphrase
  or the value of an environment variable. Every text field passes through
  the redactor before the event is created.
- **Streaming redaction.** A secret can be split across two deltas, so the
  redactor on a delta stream releases text up to the last whitespace and
  holds only the trailing incomplete token, at most 128 characters of it,
  until the next chunk arrives or the message ends. Key and token formats
  contain no whitespace, so ordinary prose lags by about one word. Two
  shapes span whitespace and get their own rule: `Bearer` and
  `Authorization:` are held together with the token after them, and a
  private-key block is replaced at its BEGIN line, with everything up to
  its END line dropped. A release never falls inside a match. The rule
  applies to `agent.text.delta`, `agent.reasoning.delta`, operator input
  and every other streamed text. Tests split known keys at every offset
  and check that no event contains any 8 or more consecutive characters of
  them, and that prose fed in 4-character chunks never has more than 20
  characters withheld.
- **No tracebacks.** Errors carry a sentence, a hint and a log path. The
  traceback goes to the log file named in the event.
- **Text is safe to print.** Text fields are valid UTF-8, split only at
  character boundaries. Control characters other than newline and tab are
  replaced, so an event can be printed to a terminal without risk.
- **Paths** are relative to the workspace root, with forward slashes.
- **Sizes** are bounded: a text delta is at most 4 KiB, a tool result
  summary at most 200 characters, a list of paths at most 200 entries
  followed by a count of the rest. Full results live in the trace.
- **Harness facts.** `verdict`, `verification`, `provenance` and
  `workspace` are written by the harness from what it measured. Model text
  never fills them.

## Kinds

### Session

| Kind | `data` fields |
|---|---|
| `session.started` | `workspace` (string, display name only), `model` (string, or null when no config names one), `provider` (string or null, the same), `branch` (string or null), `mode` (`default`, `plan`, `auto-accept`, `unrestricted`), `tier3` (`off`, `ask`, `allowlist`, `unrestricted`, `suspended`), `tier3_status` (string, the status line's words for it from the project's grant: `T3 off (no grant)`, `T3 off (grant expired <date>)`, `T3 ask`, `T3 allowlist`, `UNRESTRICTED (signed grant)`, `T3 suspended: policy changed`), `context_limit` (integer or null: the probe's measured usable window when `.ract/probes/capability.json` exists, else the provider's `context_window` in `ract.yaml`, else null), `session_id` (string or null: the id `--resume` takes; null when the session is not saved), `provider_reachable` (boolean or null when not checked), `tool_calling` (`native`, `fallback`, `none`, `unknown`), `extensions` (object: `loaded`, a list of `{kind, name}`, and `skipped`, a list of `{kind, name, reason}`; `kind` is `hook`, `mcp`, `skill`, `policy`, `guidance`, `command` (a provider the repository runs as a program) or `network` (a model host only the repository names)) |
| `session.resumed` | the same fields as `session.started`, plus `resumed_from` (session id) and `turns` (integer, turns already in the session) |
| `session.ended` | `reason` (`exit`, `eof`, `interrupted`, `terminated`, `error`), `turns` (integer), `duration_ms` (integer), `cleanup` (object, present only when an interrupted turn was still cleaning up at exit: `waited_ms` (integer), `finished` (boolean)) |
| `session.rewound` | `to_turn` (integer), `scope` (`conversation`, `code`, `both`, `summary`), `restored` (integer), `skipped` (list of `{path, reason}`) |
| `mode.changed` | `mode`, `tier3`, `by` (`operator`, or `policy` when tier 3 is suspended because `.ract/policy.yaml` or its signature changed during the session) |

`session.started` is always the first event and `session.ended` the last.
In a headless run the first event is how a script learns whether the
provider answered, how tool calls will be read, the context limit, and
which repository-supplied extensions loaded or were skipped (for example
`{"kind": "hook", "name": "pre-step", "reason": "untrusted project"}`).

### Input

| Kind | `data` fields |
|---|---|
| `input.queued` | `text` (string, redacted), `position` (integer, 1 is the next to be sent) |
| `input.withdrawn` | `position` (integer). The operator took a queued item back for editing. |

`input.queued` is emitted when the operator presses Enter during a turn, so
a renderer can show the line as queued at once. The queued text reaches the
model at the next model-request boundary of the running turn, or starts the
next turn (`turn.started` with `queued: true`).

### Turn

| Kind | `data` fields |
|---|---|
| `turn.started` | `input` (string, what the operator typed, redacted), `queued` (boolean, true when it was typed during the previous turn) |
| `turn.interrupting` | `elapsed_ms` (integer, since the interrupt was received), `cancellable` (boolean, false when a model call cannot be stopped and will finish without writing), `detail` (string, one line) |
| `turn.finished` | `outcome` (`done`, `failed`, `interrupted`, `budget`, `refused`), `duration_ms` (integer), `verdict` (string, one sentence), `workspace` (string, one line, for example `"2 files changed; nothing else touched"`), `changed` (list of paths), `diffstat` (object: per changed path `{added, removed}`, `{new: lines}`, `{deleted: true}` or `{binary: true}`, counting only this turn's change: the turn's backup holds each replaced file's previous bytes), `undo` (string or null: the folder holding the previous versions of the files this turn replaced), `backup_id` (string or null: that folder's name, for `undo_backup.previous_version`; a name, never a path, so a renderer does not take a path apart; absent from an interrupted turn's event), `checkpoint` (string or null), `verification` (object, below), `provenance` (object, below), `review` (list or null: null when no step was reviewed; otherwise each step's `review.finished` data), `citations` (object or null: null when the turn had no answer; otherwise `verified`, `unverified` and `not_checked` counts of the file and line citations in the answer, checked against the repository, and `items`, at most 60, each `{path, lines, status, reason}`) |

`verification`:

| Field | Type | Meaning |
|---|---|---|
| `status` | `verified`, `failed`, `stale`, `no-tests`, `not-run` | `verified`: tests ran after the last change and passed. `failed`: a check ran after the last change and failed. `stale`: they passed before a later change. `no-tests`: the project has none RACT can find. `not-run`: tests exist and did not run. |
| `runs` | list of `{command, exit_code, duration_ms}` | Each test or check command the harness ran in this turn, in order. |
| `no_project_code` | list of paths, present only when not empty | Test files the turn created or rewrote that import no module of the project and start no process, so they cannot exercise project code (for example a test that defines the value it checks). A warning shown next to the verified line; it never makes a turn verified. |
| `claims` | list of strings | Claims in the turn's answer text that a verifier run would have to back (`tests pass`, `verified`, `tested`) and that nothing in the turn checked. Instructions and conditions ("check that the tests pass") are not claims. |
| `test_named` | `true`, present only with `not-run` | True when the request names a test (a test file, a test function, a node id) or says a test fails. RACT cannot run tests yet (slice c), so such a turn is not verified: the summary says `verified: no` and ends with "not verified: RACT cannot run tests yet (slice c)". |

`provenance`:

| Field | Type | Meaning |
|---|---|---|
| `signed` | boolean | True only when every changed file has a signed Rootknot record. Until S-015b lands this is false. |
| `unsigned_files` | list of paths | Changed files without a signed record. |
| `sidecars` | list of paths | The signed record beside each signed file (`src/.calc.py.rootknot.json`); commit it with the file to keep the record (D-143). |

`turn.interrupting` is emitted within 200 ms of Ctrl-C. A renderer prints
the acknowledgement from it; the time until `turn.finished` with outcome
`interrupted` is the time to return to the prompt.

### Plan and steps

| Kind | `data` fields |
|---|---|
| `plan.proposed` | `assumption` (string), `confidence` (number from 0 to 1), `planned` (boolean: false when the model went straight to tools or answered in prose twice, and the request runs as the one step through the step agent loop, B-137), `steps` (list of `{n, action, target}`; `target` is a path or null) |
| `step.started` | `n` (integer), `action` (string), `target` (string or null) |
| `step.finished` | `n`, `outcome` (`done`, `failed`, `skipped`, `refused`), `artifact` (path or null), `confidence` (number or null), `duration_ms` (integer), `hint` (string or null: the next step in words, when `outcome` is not `done` and the step knows one; the turn's `error.surfaced` always has one) |

The plan's assumption and confidence come from the planner's Rooted plan
and are shown with the step list. A step's `confidence` is the executor's
for that step.

### Model output

| Kind | `data` fields |
|---|---|
| `agent.text.delta` | `text` (string), `channel` (`answer` or `artifact`), `path` (string, present when `channel` is `artifact`) |
| `agent.reasoning.delta` | `text` (string). Renderers show it dimmed and collapsed. It never becomes answer text. |
| `agent.heartbeat` | `waiting_on` (`model`, `connection`, `tool`, `approval`, `workspace`), `elapsed_ms` (integer), `detail` (string, short, for example `"first token not yet received"`; for `connection`, the address being connected to) |
| `agent.retry` | `attempt` (integer, starting at 1), `max` (integer), `reason` (string, one line, for example `"connection reset"`), `wait_ms` (integer, delay before the next attempt) |

`channel` keeps a chat answer apart from the content of a file being
generated: in today's single-shot step the model's text is the file, and a
renderer draws it under the file's name, separate from any answer text.

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
| `approval.requested` | `id` (string), `tier` (`T2` or `T3`), `rule` (string, id of the policy rule that requires the approval), `action` (string, the exact command or change, control characters escaped), `reason` (string, labeled as the model's), `facts` (object: `cwd`, `network`, `sandbox_enforced`, `env_names`, `limits`), `choices` (list of `once`, `session`, `always`, `deny`) |
| `approval.resolved` | `id`, `choice` (one of `choices`, or `denied` when nobody could answer), `by` (`operator-tty`, `signed-record`, `unattended`) |
| `review.started` | `n` (number, the step), `reviewer` (string: "reviewed by the same model" or a provider name), `path` (string) |
| `review.finished` | `n`, `reviewer`, `path`, `status` (`done`, `skipped`, `stopped` or `failed`), `note` (string, when not `done`: why, such as "review stopped: token budget"), `shown`, `downgraded` (numbers), `dropped` (object: reason to count), `claims_cut` (number), `findings` (list of `{path, line, severity, claim}`, each checked against the repository; advice only, never a verdict) |
| `plan.approval_requested` | `plan_hash` (string, sha256 of the canonical JSON of each step's `n`, `action` and `target`, computed over the plan's own text before control characters are replaced), `steps` (as in `plan.proposed`) |
| `plan.approval_answered` | `plan_hash`, `answer` (`approve`, `skip`, `edit` or `cancel`), `kept` (step numbers), `skipped` (list of `{n, reason}`; reason is `user` or `depends on step <k>`), `edited` (step number or null) |

No model output can produce `approval.resolved` (ADR-0048 Invariant A-1).
No prompt resolves on a timer: an unanswered approval waits. In a headless
run every approval resolves at once as `denied` with `by: unattended`, and
the denial is recorded in the result (`denials`).

### Cost and context

| Kind | `data` fields |
|---|---|
| `cost.updated` | After each model request, from the egress ledger, totals for the turn so far: `tokens_in` (integer, or null when no request in the turn reported token counts), `tokens_out` (integer or null), `by_purpose` (tokens per purpose, for example `{"plan": 900, "step 1": 1036}`), `requests` (integer, model requests so far in the turn), `total_usd` (number or null when unknown), `context_used` (integer or null), `context_limit` (integer or null) |

### Errors and notices

| Kind | `data` fields |
|---|---|
| `error.surfaced` | `message` (string, one or two sentences), `hint` (string, never empty: the next action or the exact command), `workspace` (string, one line, for example `"no files were changed"`), `log` (string or null, path of the log with details) |
| `notice` | `level` (`info` or `warning`), `text` (string) |

### Reserved names

These kinds will be added later, as additive changes. Nothing else may use
the names:

| Kind | Planned meaning |
|---|---|
| `context.compacted` | the conversation was summarized; `before` and `after` token counts (R-165) |
| `verification.started`, `verification.finished` | a test or check command run, live, ahead of the summary in `turn.finished` |
| `checkpoint.created` | a checkpoint was written (B-013) |
| `mcp.server.started`, `mcp.server.failed` | an MCP server's startup result |

## Headless mode

### Output formats

- `--output-format stream-json` prints every event, one JSON object per
  line, in `seq` order, on stdout.
- `--output-format json` prints one `ract.result/1` object on stdout at the
  end.
- `--output-format text` (the default) prints the answer text only.

stdout carries only the result or the event lines. Progress, notices and
warnings go to stderr. When stdout is not a terminal it carries no ANSI
sequences, so `ract -p "..." > out.txt` gives a clean file.

### Exit codes

| Code | Meaning |
|---|---|
| 0 | done |
| 1 | the task failed, or its tests failed |
| 2 | usage or configuration error; also stdin stalled: piped stdin stayed open and sent nothing for 30 s (`RACT_STDIN_IDLE_TIMEOUT` changes it; `--no-stdin` skips the read) |
| 3 | refused by policy or tier; also the first denial when `--fail-on-denial` is set |
| 4 | a budget was exhausted (turns, tokens, wall time, cost) |
| 5 | interrupted (SIGINT, Ctrl-C) |
| 6 | the provider was unavailable |
| 143 | terminated by SIGTERM (Ctrl-Break on Windows) |

### The result object: `ract.result/1`

| Field | Type | Meaning |
|---|---|---|
| `schema` | string | Always `"ract.result/1"`. A breaking change gets a new name. |
| `outcome` | string | The last turn's `outcome`. |
| `exit_code` | integer | The process exit code, from the table above. |
| `error` | object or null | Null when the exit code is 0. Otherwise exactly four keys: `kind` (below), `message` (text, at most 300 characters, control characters and direction marks shown as escapes), `hint` (the next action, at most 300 characters, empty when there is none) and `exit_code` (equal to the top-level `exit_code`). |
| `session` | string | Session id. |
| `turns` | integer | Turns run. |
| `verdict` | string | The last turn's verdict sentence. |
| `planned` | boolean or null | False when the model went straight to tools and the request ran as one step (B-137); null when no plan was proposed. |
| `final_text` | string | The answer text of the last turn (`channel: answer` only). |
| `changed` | list of paths | Files changed across the run. |
| `verification` | object | As in `turn.finished`, for the run as a whole. |
| `provenance` | object | As in `turn.finished`, for every changed file. |
| `cost` | object | From the egress ledger (docs/EGRESS.md) for this turn: `tokens_in`, `tokens_out` (integers, or null when the provider reported no token counts), `by_purpose` (tokens per purpose, for example `{"plan": 900, "step 1": 1036}`), `total_usd` (number or null; prices are not configured in this release), `requests`, `unreported` (model requests that reported no tokens), `bytes_out`, `bytes_in`. |
| `denials` | list of `{rule, action, tier}` | Every action that would have asked for approval and was denied. |
| `notices` | list of strings | The text of every `notice` event, so a log of stdout alone shows them (for example a question answered instead of written). |
| `plan` | list of objects | The steps of the run, in order. Each object has `step` (integer, one-based), `title` (text), `state` (pending, running, done, failed, refused or skipped), `file` (text or null) and `verdict` (passed, failed, refused or skipped; null before the harness has spoken). An ask-mode run has an empty list. |
| `events_path` | string or null | Path of the full event stream, when it was written to a file. |
| `structured_output` | any | Present only when `--json-schema` was given and the reply validates. An invalid reply leaves the field out and the exit code is 1. |

`error.kind` and the exit code it comes with:

| `kind` | Exit code | When |
|---|---|---|
| `usage` | 2 | The arguments could not be read, a flag is not supported, or there is no prompt. |
| `config` | 2 | `ract.yaml` is missing or cannot be used (for example a key the provider rejects). |
| `stdin_stall` | 2 | Piped stdin stayed open and sent nothing (`RACT_STDIN_IDLE_TIMEOUT`). |
| `refused` | 3 | Refused by policy or tier, including a change the `default` mode had nobody to approve. |
| `budget` | 4 | A budget was exhausted. |
| `cancelled` | 5 or 143 | Interrupted (Ctrl-C) or terminated (SIGTERM, Ctrl-Break). |
| `provider` | 6 | The provider was unavailable. |
| `internal` | 1 | The task failed for a reason RACT does not classify. When the run surfaced no error, `message` is the turn's verdict and `hint` is empty. |

The errors found before the turn starts (`usage`, `config` with no file,
`stdin_stall`) print the same one line on stderr as before, and with
`--output-format json` also a result: `outcome` `failed`, `turns` 0 and
`session` empty. `error` was added within `ract.result/1` under the
additive rule above: a reader that ignores unknown keys is unchanged.

The result carries no secrets and no tracebacks, under the same rules as
events.

## Example

```json
{"v":2,"seq":1,"t":"2026-10-21T18:02:10.001Z","session":"s-0192","turn":null,"kind":"session.started","data":{"workspace":"calc","model":"fake-coder","provider":"local","branch":"main","mode":"default","tier3":"off","context_limit":32768,"session_id":"s-0192","provider_reachable":true,"tool_calling":"fallback","extensions":{"loaded":[],"skipped":[]}}}
{"v":2,"seq":2,"t":"2026-10-21T18:02:11.482Z","session":"s-0192","turn":1,"kind":"turn.started","data":{"input":"fix add so the test passes","queued":false}}
{"v":2,"seq":3,"t":"2026-10-21T18:02:13.483Z","session":"s-0192","turn":1,"kind":"agent.heartbeat","data":{"waiting_on":"model","elapsed_ms":2001,"detail":"first token not yet received"}}
{"v":2,"seq":4,"t":"2026-10-21T18:02:14.020Z","session":"s-0192","turn":1,"kind":"plan.proposed","data":{"assumption":"add subtracts instead of adding","confidence":0.9,"steps":[{"n":1,"action":"Make add return a + b","target":"src/calc.py"}]}}
{"v":2,"seq":5,"t":"2026-10-21T18:02:14.021Z","session":"s-0192","turn":1,"kind":"step.started","data":{"n":1,"action":"Make add return a + b","target":"src/calc.py"}}
{"v":2,"seq":6,"t":"2026-10-21T18:02:14.610Z","session":"s-0192","turn":1,"kind":"agent.text.delta","data":{"text":"def add(a, b):\n    return a + b\n","channel":"artifact","path":"src/calc.py"}}
{"v":2,"seq":7,"t":"2026-10-21T18:02:14.902Z","session":"s-0192","turn":1,"kind":"step.finished","data":{"n":1,"outcome":"done","artifact":"src/calc.py","confidence":0.9,"duration_ms":881,"hint":null}}
{"v":2,"seq":8,"t":"2026-10-21T18:02:16.300Z","session":"s-0192","turn":1,"kind":"turn.finished","data":{"outcome":"done","duration_ms":4818,"verdict":"Changed 1 file; tests passed after the change.","workspace":"1 file changed; nothing else touched","changed":["src/calc.py"],"checkpoint":null,"verification":{"status":"verified","runs":[{"command":"pytest -q","exit_code":0,"duration_ms":1290}]},"provenance":{"signed":false,"unsigned_files":["src/calc.py"]}}}
{"v":2,"seq":9,"t":"2026-10-21T18:02:20.115Z","session":"s-0192","turn":null,"kind":"session.ended","data":{"reason":"exit","turns":1,"duration_ms":10114}}
```

The `ract.result/1` object for the same run:

```json
{"schema":"ract.result/1","outcome":"done","exit_code":0,"session":"s-0192","turns":1,"verdict":"Changed 1 file; tests passed after the change.","final_text":"","changed":["src/calc.py"],"verification":{"status":"verified","runs":[{"command":"pytest -q","exit_code":0,"duration_ms":1290}]},"provenance":{"signed":false,"unsigned_files":["src/calc.py"]},"cost":{"tokens_in":1840,"tokens_out":96,"by_purpose":{"turn":1936},"total_usd":null},"denials":[],"events_path":null}
```
