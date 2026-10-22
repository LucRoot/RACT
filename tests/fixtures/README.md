# Test fixtures

## Fake model server

`fake_model_server.py` is a scripted OpenAI-compatible server for tests and
for walkthroughs in a real terminal. It uses only the standard library, binds
to `127.0.0.1` on an ephemeral port, and plays back a scenario file from
`scenarios/`. Nothing under `src/` imports it.

It serves `GET /v1/models` and `POST /v1/chat/completions`, streaming (SSE)
and non-streaming. Any other path returns 404 with a JSON error body.

### In a test

The `fake_model_server` fixture in `tests/conftest.py` is a factory. Pass a
scenario name, a path, or a `Scenario` object. The server stops at teardown.

```python
def test_reads_the_answer(fake_model_server):
    from ract.providers.local_http_provider import LocalHttpProvider

    server = fake_model_server("j1_first_run")
    provider = LocalHttpProvider({"url": server.base_url, "model": "fake-coder"})
    result = provider.complete([{"role": "user", "content": "hello"}])

    assert result.unwrap()["choices"][0]["message"]["content"].startswith("Hello.")
    assert server.chat_requests[0].body["stream"] is False
```

`server.requests` lists every request received (method, path, headers
without `authorization`, parsed JSON body). `server.chat_requests` keeps the
chat-completion ones. `server.turns_served` maps each request to the scenario
turn that answered it.

### In a terminal

```bash
python -m tests.fixtures.fake_model_server --scenario j3_ask_code
```

Run it from the repository root. It prints the base URL and the values to
export as `RACT_DEMO_BASE_URL` and `RACT_DEMO_MODEL`, then serves until
Ctrl-C. `--list` shows the bundled scenarios and `--verbose` logs each
request to stderr.

### Scenario format

A scenario is a JSON object:

```json
{
  "name": "example",
  "model": "fake-coder",
  "tools_supported": true,
  "usage": true,
  "turns": [
    {"match": {"last_message": "(?i)probe"}, "reply": {"kind": "tool_calls", "calls": [{"name": "echo", "arguments": {"text": "ok"}}]}},
    {"match": {"turn": 2}, "reply": {"kind": "text", "content": "second request"}},
    {"reply": {"kind": "text", "content": "anything else"}, "repeat": true}
  ]
}
```

For each chat request the server picks the first unused turn whose `match`
passes. `match.turn` is the 1-based chat request number; `match.last_message`
is a regex on the last user or tool message. A turn without `match` always
passes. A turn is used once unless it sets `repeat`. When no turn fits, the
server answers 500 with error type `scenario_exhausted`.

Reply kinds:

| `kind` | Fields | Produces |
|---|---|---|
| `text` | `content` | An assistant message |
| `tool_calls` | `calls` (`name`, `arguments`), optional `content`, `arg_fragment_size` | Native `tool_calls`, single or parallel, arguments streamed in fragments |
| `json_envelope` | `envelope`, or `raw` for a malformed one | The fallback envelope as plain text |
| `reasoning` | `reasoning`, `content`, `style` (`field` or `inline`), `close_think` | `reasoning_content`, or `<think>` in the content |
| `truncated` | `reasoning`, `content` | `finish_reason: "length"` |
| `fault` | `fault`, plus `retry_after`, `after_chunks`, `hold_seconds` | `http_429`, `http_500`, `http_503`, `reset_mid_stream` (TCP reset; how many lines arrive first is not deterministic), `truncated_close` (clean close after exactly `after_chunks` lines), `never_respond`, `non_json`, `missing_choices`, `empty_message` |

Options on any reply: `chunk_size` (default 16 characters), `chunk_delay`
(seconds between chunks), `first_byte_delay`, `wait_for` (a gate name: the
reply is held until the test calls `server.release(name)`), `stall`
(`{"after_chunk": n, "seconds": s}`), `finish_reason`, and the real-server
quirks `done: false` (no `[DONE]` line), `crlf: true` (CRLF line endings) and
`close_after: true` (close-delimited body with `Connection: close`).

Scenario settings: `tools_supported: false` makes the server ignore the
`tools` parameter, the way many local servers do, and refuses `tool_calls`
replies at load time. `usage: false` drops the usage block. Ids
(`chatcmpl-fake-N`, `call_N_i`) and `created` are fixed, and delays change
timing only, so a scenario gives the same bytes on every run.

### Bundled scenarios

| Scenario | Journey | What it plays |
|---|---|---|
| `j1_first_run` | J1 | Tool-call probe succeeds, then a greeting |
| `j1_no_tools` | J1 | Probe gets plain text, then JSON-envelope answers |
| `j3_ask_code` | J3 | grep, two parallel reads, a streamed answer with file and line references |
| `j4_fix_test` | J4 | run tests, read, edit, run tests, summary |
| `j6_slow` | J6 | 6 s before the first byte, slow chunks, a 5 s stall |
| `j9_weak_model` | J9 | No native tools, a malformed envelope, a valid one, hidden reasoning |
| `j10_faults` | J10 | Every fault in order, then truncation and a server that never answers |
