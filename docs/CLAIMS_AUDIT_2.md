# Claims audit, round 2 (S-017)

The earlier audit could not verify these sentences. Each row says whether the
claim is true of this release, what the evidence is, and what the text says
now. A test (`tests/docs/test_claims_audit_2.py`) keeps the corrected
sentences and this table in step.

Evidence so far is the code. The real-CLI run of each row is recorded in the
"CLI run" column when it has been made; until then it says "pending".

| Claim (where) | True? | Evidence | CLI run | The text now |
|---|---|---|---|---|
| `ract receipt-export` can "upload to a signed archive" (README) | false | `_receipt_export_command` in `src/ract/cli.py` reads a directory of signed receipt files and prints them as JSON; there is no upload and no archive | pending | `ract receipt-export` — Print the signed receipts in a directory as JSON. |
| `ract receipt` lists, shows or verifies receipts (README) | true | `show`, `verify` (with `--pubkey`), `chain-export`, `chain-verify` and `diff` exist in `_receipt_command` | pending | unchanged |
| RACT ships "signed skill templates" (QUICKSTART) | false | `src/ract/builtin_skill_library.py` and `src/ract/builtin_skills/` hold the templates; nothing signs them and `ract skills install` checks no signature | pending | RACT ships skill templates for common tasks (they are not signed): |
| Each step runs in "an OS-enforced sandbox derived from a signed capability manifest" (PHILOSOPHY) | false | No backend confines a plan step's commands; only a tier-3 command on Linux runs inside bubblewrap, after a self-test (B-114), and on Windows and macOS nothing confines one (ADR-0048 D7). The manifest is built per run and its digest goes into each Rootknot (S-015b); the manifest itself carries no signature | pending | a sandbox described by a capability manifest (no backend enforces it yet: ADR-0048 D7) |

After S-015b lands, the signing rows are run again: a run followed by
`ract provenance verify` on a file it changed.
