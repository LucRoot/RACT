# SECURITY.md section: tier 3 (draft, B-151)

Draft for the operator's release cut, to go into `SECURITY.md`.

## Tier 3

**What it is.** Tier 3 is RACT running a command of your project: tests, a build, a linter, a git push or a web fetch. It is off until you sign a grant with your operator key at a terminal; the key never leaves your user config folder and the passphrase is never read from a pipe or an environment variable (cite: docs/TIER3.md) (cite: tests/test_policy_guided.py).

**The trust model.**
- Nothing the model writes can approve a tier-2 or tier-3 action. Approvals come from you at the terminal, from a rule you signed, or from your answer for the session (cite: docs/TIER3.md).
- Text RACT reads from files, commands or the web reaches the model marked as data. A proposal that follows a fetched page always asks (cite: tests/test_b149_untrusted_text.py::test_a_command_after_fetched_text_carries_the_origin_line_and_asks).
- A changed test, conftest or runner file puts a command back to the question, even under an allow rule (cite: tests/test_b113_allowlist.py).
- Headless runs and `--yolo` never run tier 3 (cite: tests/test_ract_runner.py::test_d145_tier_2_asks_at_a_terminal_in_every_mode).

**What is not enforced on Windows.** No backend confines a command on Windows in this release. A grant says `sandbox: best_effort`, and the prompt says the network and file limits are not enforced and that the command runs with your user's rights (cite: tests/test_b025_doctor_sandbox.py). On Linux, bubblewrap confines a command once its self-test passes (cite: tests/test_b114_command_sandbox.py).

**How to report.** Report a vulnerability privately to the author (the address in `README.md`), not in a public issue. Say what you ran, the RACT version, and what reached a command or the network that should not have.

## Not claimed

- That an allowed command is safe: an allowed test command runs the project's code, including code the model wrote this session (cite: docs/TIER3.md).
