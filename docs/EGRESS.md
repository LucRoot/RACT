# What leaves the machine

RACT records every request it sends to another host in an egress ledger,
and scans every request that carries content for secret-shaped values
before it is sent. This page lists every place a request can leave, what
it carries, and how it is checked.

## The ledger

Each request leaves one line in `egress.jsonl` in the user state directory:

| Platform | Path |
|---|---|
| Windows | `%LOCALAPPDATA%\ract\egress.jsonl` |
| Linux, macOS | `$XDG_STATE_HOME/ract/egress.jsonl`, or `~/.local/state/ract/egress.jsonl` |

`RACT_EGRESS_LEDGER` names another file. The file is rotated to
`egress.1.jsonl` at 10 MB. Only the newest rotation is kept.

A record holds the time, the process id, the purpose (`plan`, `step 2`,
`health`, or the kind when nothing more specific applies), the kind
(`model`, `mcp`, `web_search`, `github`, `marketplace`), the destination
host, the HTTP status or the error class, the time taken, the bytes sent
and received, and the input and output tokens when the provider reported
them. It never holds content: no URL path or query, no header, no request
or response body.

Tokens are `null` when the provider did not report them. Streamed replies
from most local servers carry no token counts, so a streamed turn is
listed as "not reported" rather than estimated.

Read it with:

- `/cost` in the interactive session: this session's requests, tokens and
  bytes, by host.
- `ract doctor --egress`: the last 7 days by kind and host, the ledger's
  path, and the exempt sites below.
- `ract -p ... --output-format json`: the `cost` field of `ract.result/1`
  holds the same totals for that turn.

If the ledger cannot be written, RACT prints one note and carries on; the
request is not stopped.

## Every outbound site

All network requests go through one httpx client factory
(`ract.egress_ledger.client`); a test fails if any module makes a client
or request any other way. RACT runs no git command that talks to a remote
and does not call `gh`.

| Site | Carries | Scanned before sending | Reached from |
|---|---|---|---|
| Model provider, chat completion (plain and streamed) | the prompt: intent, file contents, retrieved snippets | yes, every string in the payload | every turn |
| Internal provider command | the last message, on stdin | yes | a turn with `adapter: internal`, trusted repositories only |
| Web search | the search query | yes | a turn with `retrieval.adapter: web`, trusted repositories only; `ract retrieval search` |
| MCP server over HTTP, `tools/list` and `tools/call` | tool arguments written by the model | yes, every string in the request | turns in trusted repositories with MCP servers; `ract mcp list`, `ract mcp invoke` |
| MCP server over stdio | the same, to a local process | yes | as above |
| GitHub release notes | the release body | yes | `ract release create` |
| GitHub release assets | whole files | a text asset holding a secret-shaped value is refused | `ract release create --asset` |

## Exempt sites

These send no content, so there is nothing to scan. They are still
recorded in the ledger when RACT makes the request itself.

| Site | Why exempt |
|---|---|
| Provider health check (`GET /models`) | sends only the API key, to the provider it belongs to |
| GitHub release list | sends only the token |
| Skill marketplace catalog and skill downloads | downloads only |
| Embedding model download (`ract memory`, only with `RACT_EMBED_ONLINE=1`) | made by the sentence-transformers library, not recorded |
| Language-server downloads (`ract memory` graph build) | made by the multilspy library, not recorded |

Hooks, a repository's own MCP servers and the internal provider command
are programs the repository supplies. RACT does not see what they send. They
run only in a repository you trusted (`ract trust`); see THREAT_MODEL.md.
