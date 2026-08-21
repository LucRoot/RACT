# RACT CLI JSON Cheat Sheet

Every RACT command that can emit structured JSON output, as of v0.5.1.

**Scope note.** This sheet covers structured-output verbs only.
The complete CLI verb index (60+ subverbs including memory,
retrieval, session, trace, intent recompile, provenance verify)
lives in README.md; see the "CLI Verb Index" section there. v0.5.1
adds `ract intent recompile`; a fuller `retrieval query` wiring
+ `manifest ledger` verbs are queued behind the v0.5.1 wiring
completion pipeline (`docs/RACT_v0.5.1_WIRING_COMPLETION_SPEC.md`
module_10).

## Commands with `--json`

| Command | What it returns | Example |
|---|---|---|
| `ract audit --json` | Audit result with `passed`, `total`, `findings` | `ract audit --json` |
| `ract consolidate scan --json` | Scan report with `files`, `issues`, `summary` | `ract consolidate scan --json` |
| `ract diff apply --patch patch.txt --json` | Patch application results | `ract diff apply --patch patch.txt --json` |
| `ract doctor --json` | Doctor check results | `ract doctor --json` |
| `ract explain --intent "add tests" --json` | Plan explanation object | `ract explain --intent "add tests" --json` |
| `ract handshakes list --json` | Handshake registry array | `ract handshakes list --json` |
| `ract handshakes approve <id> --json` | Updated handshake entry | `ract handshakes approve abc --json` |
| `ract leaderboard --json` | Loaded receipts array | `ract leaderboard --receipts-dir receipts --json` |
| `ract mcp list --json` | Configured MCP tools array | `ract mcp list --json` |
| `ract mutation run --json` | Mutation report object | `ract mutation run --json` |
| `ract operator-queue list --json` | Operator queue entries | `ract operator-queue list --json` |
| `ract receipt show <file> --json` | Receipt object | `ract receipt show receipt.json --json` |
| `ract receipt verify <file> --pubkey <key> --json` | Verification result | `ract receipt verify receipt.json --pubkey key.pem --json` |
| `ract refactor --old foo --new bar --dry-run --json` | Planned rename edits | `ract refactor --old foo --new bar --dry-run --json` |
| `ract retrieval search <query> --json` | Retrieval results array | `ract retrieval search greeting --json` |
| `ract run-fingerprint <receipt.json> --json` | Run fingerprint object | `ract run-fingerprint receipt.json --json` |
| `ract skills list --json` | Built-in skills array | `ract skills list --json` |
| `ract skills marketplace list --json` | Marketplace catalog array | `ract skills marketplace list --json` |
| `ract whisper --intent "refactor" --json` | Whisper brief object | `ract whisper --intent "refactor" --json` |

## Commands with `--format json`

| Command | What it returns | Example |
|---|---|---|
| `ract report --last --format json --output report.json` | Last run report JSON | `ract report --last --format json --output report.json` |

## Commands that emit JSON by default

| Command | What it returns | Example |
|---|---|---|
| `ract ai-sbom <receipts.json>` | AI manifest object | `ract ai-sbom receipts.json` |
| `ract coverage badge --output badge.json` | Shields-style badge JSON written to file | `ract coverage badge --output badge.json` |
| `ract coverage delta-export --before before.json --after after.json` | Coverage delta object | `ract coverage delta-export --before before.json --after after.json` |
| `ract policy-gate --policy p.json --evidence e.json` | Policy evaluation result | `ract policy-gate --policy p.json --evidence e.json` |
| `ract receipt chain-export <chain.jsonl>` | Chain entries array | `ract receipt chain-export chain.jsonl` |
| `ract receipt chain-verify <chain.jsonl>` | Chain validity object | `ract receipt chain-verify chain.jsonl` |
| `ract receipt diff <a.json> <b.json>` | Receipt differences object | `ract receipt diff a.json b.json` |
| `ract session export --session <id> --output session.json` | Session JSON written to file | `ract session export --session abc --output session.json` |
| `ract session import --input session.json` | Session import result | `ract session import --input session.json` |
