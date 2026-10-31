# 0.6.0 CHANGELOG entry (draft, B-151)

Draft for the operator's release cut. `VERSION` and the real `CHANGELOG.md` are unchanged. Every line cites the test or document that backs it; the "Not claimed" list at the end holds what this draft does not assert.

## [0.6.0] (unreleased)

### Tools and tiers

- Tier 3 runs a command only under a signed operator grant, asks before each command by default, and stays off without one (cite: docs/TIER3.md) (cite: tests/test_policy_guided.py::test_a_new_user_reaches_a_signed_pytest_rule).
- `ract policy init --guided` proposes the narrowest rule for the test runner, the linter, the type checker, the formatter and the build, all signed with one signature, and `ract policy add-rule` adds one later (cite: tests/test_b142_guided_verifiers.py::test_one_signature_grants_every_detected_rule).
- Verifier tools run the grant's build, lint, typecheck and format rules the way `run_tests` does (cite: tests/test_b023_verifiers.py).
- Allowlist mode lets a matching command run without asking. A changed entry point still asks, and so does a selector in a folder the record skips (cite: tests/test_b113_allowlist.py::test_a_selector_in_an_uncollected_folder_asks).
- A tier-2 call asks at a terminal in every session mode; headless runs and `--yolo` refuse tiers 2 and 3 (cite: tests/test_ract_runner.py::test_d145_tier_2_asks_at_a_terminal_in_every_mode).
- A model that answers with tool calls instead of a plan gets the request as one step through the step loop (cite: tests/test_b137_agent_plan.py::test_headless_a_tool_call_first_reply_runs_as_the_one_step).
- A malformed tool call is answered plainly, never reaches a tool, and three in a step end it (cite: tests/test_b140_malformed_calls.py::test_three_bad_calls_end_the_step_and_none_reaches_a_tool).
- Text of unknown origin is delimited for the model, and a proposal that follows a fetched page says so on its card and always asks (cite: tests/test_b149_untrusted_text.py::test_a_command_after_fetched_text_carries_the_origin_line_and_asks).
- `ract doctor --tier3` reports the grant, the key, the sandbox, the tools and the fix for each problem (cite: tests/test_b147_doctor_tier3.py::test_no_grant).

### Signing and provenance

- A run signs what it writes, and `ract provenance verify` passes on it, in the session, in `ract run --auto` and in `ract -p --accept-edits` (cite: tests/test_s015b_signing.py::test_each_way_a_person_runs_it_signs).
- Each signed file's record sits beside it; the summary names it, the per-hunk review leaves it out, and a rejected file takes it back (cite: tests/test_s015b_sidecar_review.py::test_a_rejected_file_leaves_its_sidecar_out).
- The work at run entry is bounded; past a bound it says so and goes on (cite: tests/test_b148_bounds.py::test_the_signing_snapshot_stops_at_its_deadline_and_says_so).
- What the Rootknot and the trace chain each attest is written down as a proposed ADR (cite: docs/ADRs/ADR-0050-rootknot-and-trace-attestation-and-ract-verify.md).

### Sandbox

- On Linux, a tier-3 command runs inside bubblewrap once a self-test shows it confines files, the network and processes; `/etc` is bound entry by entry (cite: tests/test_b114_command_sandbox.py::test_etc_is_bound_entry_by_entry_and_resolution_only_with_the_network).
- `ract doctor --sandbox` says what confines a command on this machine (cite: tests/test_b025_doctor_sandbox.py).
- A grant rule may name a `wsl2` or `container` backend; such a rule is refused at run in this release (cite: tests/test_b028_other_backends.py::test_a_wsl2_rule_is_refused_at_run_and_nothing_runs).

### Git and network tools

- The git tools scan each staged file whole and the commit message for secrets, refuse a repository config that can run a program, and tie a push approval to one URL and one commit (cite: tests/test_g239_git_hardening.py::test_d145_a_secret_in_the_commit_message_refuses_before_the_question) (cite: tests/security/redteam/test_git_push.py).
- `web_fetch` checks the host by its name, scans the URL and asks before any DNS lookup, then connects to the address it vetted (cite: tests/security/redteam/test_web_fetch.py::test_a_key_in_the_host_name_is_refused_before_any_dns) (cite: tests/security/redteam/test_web_fetch.py::test_a_rebinding_answer_cannot_move_the_connection).

### Linux fixes

- A drive-letter path is refused on Linux and macOS as on Windows (cite: tests/test_workspace_path_drive.py::test_a_drive_path_is_refused_as_on_windows).
- A step worktree an ended process left is removed when the next session starts (cite: tests/test_b146_worktree_sweep.py::test_a_killed_process_leaves_a_worktree_the_next_sweep_removes).

### UX

- The turn summary names what changed, what was verified and each signed file's record (cite: docs/EVENTS_SESSION.md).

## Not claimed

- That Windows confines a tier-3 command: it does not; grants say `best_effort` (cite: docs/TIER3.md).
- That `ract verify` exists: it is designed in ADR-0050 and not built (board card B-039).
- That a WSL2 or container backend runs commands: both are refused at run until the operator's row D4 and an image.
- That every Linux journey passes on a real terminal: B-146's quit test and the J7 walk are WRIGHT's open repeats.
