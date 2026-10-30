# Slice (b) walkthrough: the operator key, the signed grant, the status line (B-111)

A real pseudo-terminal walk (D-003) of slice (b) at 80, 60 and 40 columns,
recorded by `python -m tests.ux.run_slice_b`. Every key in it is a throwaway
made in a temporary user config folder for the walk; the passphrase is a
throwaway string typed into the pseudo-terminal. The passphrase never reaches
the screen (it is read without echo), and the harness's own timeline shows
`<typed passphrase>` where it typed it. The walk runs this checkout's code
(`python -m ract.cli`, `PYTHONPATH` on its `src`).

## Journeys

| Id | What it walks | Ends with |
|---|---|---|
| SB1 | A new user with no key and no grant runs `ract policy init --guided` in a project with tests: the runner is found, the narrowest rule is proposed with one line per field, the policy is shown as a diff, one yes, a new passphrase typed twice, signed. | `T3 ask`, `.ract/policy.yaml.sig` written |
| SB2 | A session in a project with a signed grant: the status line, then `/permissions`. | `T3 ask` on the status line; the grant, its rule, the sandbox and the signing key's state on the screen |
| SB3 | A cloned repository whose grant was signed by someone else's key (this machine pins its own). | `T3 off (no grant)`, a notice "tier 3 is off: the grant is not signed by your operator key", and `/permissions` saying the same |
| SB4 | A grant that expired ten days ago. | `T3 off (grant expired <date>)` and the notice |

## The two-minute target (D13)

From the command to the signed result, typed by the harness: 4.6 to 5.9 s at
every width (`metrics.json`, `to_signed_s`). Three answers: the yes and the new
passphrase twice. A person reading the proposal takes longer; the screen they
read is one page at 80 columns.

## What the walk shows about honesty

- No platform confines commands yet (Windows has no backend; Linux and macOS
  are slice e), so the guided grant writes `sandbox: best_effort`, explains
  it in one line, and `/permissions` says "not enforced on this machine;
  commands are not confined" with or without a grant. A grant that says
  `enforced` does not hold.
- The mode a grant opens is `ask`: every command still asks before it runs.

## Found in the walk, and fixed before this recording

1. Before a key existed, the proposed policy showed `key_id:
   ed25519:0000000000000000`: it now says the key is made when you answer yes.
2. `/permissions` said "T3 off (no grant) (the grant is not signed by your
   operator key)" for a grant that exists: it now says "Tier 3: off: the
   grant is not signed by your operator key".
3. The harness timeline logged the typed passphrase; it is masked there.

## Not in this walk

- The hosted model, and any command run under a grant (slice c, `run_tests`).
- The allowlist and unrestricted states: the session does not raise the mode
  yet (slice d).
- Built after this recording and covered by tests, not by the walk:
  `T3 suspended: policy changed` with `/permissions resume`
  (`tests/test_tier3_status_session.py`), the keys leaving the workspace with
  `ract policy migrate-keys` (`tests/test_keys_leave_the_workspace.py`), and
  signed approvals (`tests/test_signed_approvals.py`).
- MASON's screens for the slice.
