# README "what is new" paragraph (draft, B-151)

**New in 0.6.0.** RACT can now run your tests, builds and linters under a grant you sign once with `ract policy init --guided`, and asks before each command unless you choose allowlist mode (cite: tests/test_b142_guided_verifiers.py::test_one_signature_grants_every_detected_rule). Every file a run writes is signed, and `ract provenance verify` checks it (cite: tests/test_s015b_signing.py::test_each_way_a_person_runs_it_signs). On Linux, commands run inside bubblewrap once its self-test passes; on Windows they run with your user's rights and RACT says so (cite: tests/test_b025_doctor_sandbox.py). Text from the web is marked as data, and a proposal that follows it always asks (cite: tests/test_b149_untrusted_text.py::test_a_command_after_fetched_text_carries_the_origin_line_and_asks). `ract doctor --tier3` shows the whole state in one place (cite: tests/test_b147_doctor_tier3.py::test_no_grant).

## Not claimed

- Confinement on Windows or macOS (cite: docs/TIER3.md).
