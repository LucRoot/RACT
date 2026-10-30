# RACT security

This page says what has been checked, by whom and when, what RACT trusts, and where each input is checked. It does not claim confinement the backend does not give.

## Audit status

| Record | Date | What it covers | Status |
|--------|------|----------------|--------|
| Grand audit of the v0.6 workstream | 2026-10-22 | the journeys J1 to J10 on the scripted model server, the outbound request inventory, the commit sites, the diff applier, the secret scanner | findings recorded on the project board; the open ones are gated |
| Builder audit | 2026-10-22 | dead code, skipped tests, platform assumptions, the repository-supplied execution and egress inventory (S-025) | S-025 is marked done on the board, with its open leaves listed there |
| Gate economics | 2026-10-22 | the test gate's cost on the development machine | evidence only |

Open at the time of writing (each is a board finding, gated where the board says so):

- Nothing has run on Linux or macOS in the record; the POSIX path of the terminal driver is untested (G-06).
- A tier-2 action that requires a handshake is treated as allowed and no handshake is created (S-004).
- The handshake file is not signed and is not locked (S-005).
- Sandbox confinement is not enforced on Windows without WSL2 (see below).

The audit records are kept in the project's coordination folder, which is not part of this repository. Each finding has an identifier on the project board. The board is the source of truth for status; this page is updated when a finding is closed.

## What is trusted

- The user at the terminal, and the files the user owns in the project.
- The configuration the user wrote in `ract.yaml` and in the user state directory.

## What is not trusted

- A repository's files, including files a clone brings in and any `.ract/` or `.rack/` folder it ships.
- Model output, tool output and hook output.
- Text in a file the model reads, which is repository content and reaches the model as untrusted input.

## Where each input is checked

| Input | Check |
|-------|-------|
| A file a step writes | the write gate (`src/ract/write_gate.py`): parse of new Python, the diff against the old file, the byte-order rule |
| A path in a plan or a reply | the workspace path jail (`src/ract/workspace_path.py`): a path that leaves the workspace, a Windows device name, an alternate stream, or (for a write) a hard link is refused |
| A file the operator did not write | the untrusted file reader (`src/ract/untrusted_file.py`): a link is refused, the size is capped, the real path must stay under the root |
| An extension, playbook or role from a repository | the trust store (`src/ract/trust.py`): untrusted until the user runs `ract trust` |
| Text printed to a terminal | `safe_text` (`src/ract/session_events.py`): control and bidirectional characters are shown escaped |
| Text sent to a provider | the egress scan (`src/ract/egress_scan.py`) and the egress ledger (`src/ract/egress_ledger.py`); credentials are redacted (`src/ract/redaction.py`) |
| A sandboxed command | the sandbox backend. Where the backend does not enforce, the run records `sandbox.unenforced` and the page says "declared, not enforced". |

## Declared, not enforced

On Windows without WSL2, the sandbox backend does not enforce confinement. The stub backend emits `sandbox.unenforced` into the event log when it runs a command. Read every sandbox claim in this page and in the other documents as a declaration of intent unless the run record shows `sandbox.granted`.
