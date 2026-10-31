# Upgrading from v0.5.2 to 0.6.0 (draft, B-151)

Draft for the operator's release cut; the real `docs/UPGRADING.md` already carries the detailed list (cite: docs/UPGRADING.md).

## What changes

- **Runs sign what they write.** Each file a run changes gets a record beside it, `.<name>.rootknot.json`, which shows in `git status`. Commit it with its file to keep the record (cite: tests/test_s015b_signing.py::test_each_way_a_person_runs_it_signs).
- **Commands need a grant.** RACT runs no command of your project until you sign a grant (cite: docs/TIER3.md).
- **The git tools refuse more.** They refuse a repository whose own config sets a filter, a signing program, `pushurl` or `credential.helper`. A push approval made before 0.6.0 no longer matches: approve the new id when the push asks (cite: tests/security/redteam/test_git_push.py).

## What asks now

- Every tier-3 command, unless an allow rule answers in allowlist mode (cite: tests/test_b113_allowlist.py).
- A tier-2 call (a commit, a branch, a control file) at a terminal, also in auto-accept mode (cite: tests/test_ract_runner.py::test_d145_tier_2_asks_at_a_terminal_in_every_mode).
- Any proposal that follows a fetched web page, whatever the mode (cite: tests/test_b149_untrusted_text.py::test_a_command_after_fetched_text_carries_the_origin_line_and_asks).
- Every `web_fetch` (cite: tests/security/redteam/test_web_fetch.py).

## What to run

1. `ract doctor --tier3`: what is on, what is off, and the command that fixes each problem (cite: tests/test_b147_doctor_tier3.py::test_no_grant).
2. `ract policy init --guided` at a terminal: it proposes and signs your first grant, with one passphrase (cite: tests/test_policy_guided.py::test_a_new_user_reaches_a_signed_pytest_rule).
3. `ract doctor --sandbox`: whether commands are confined on this machine (cite: tests/test_b025_doctor_sandbox.py).

## Not claimed

- That a grant from another machine or another key holds here: it does not, by design (cite: docs/TIER3.md).
