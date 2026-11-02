"""B-225 part 3: the fetch question uses the network screen.

MASON's B-227 reworked ``network_screens.fetch_prompt_lines`` against the
live question's facts (tier 3, the once-or-no choice, the follows line).
This wires it: a ``web_fetch`` approval renders the network screen instead
of the command screen; a command keeps the command screen.
"""

from __future__ import annotations

from ract.approval_callback import console_tier_3_prompt

FETCH_FACTS = {
    "argv": ["web_fetch", "https://example.invalid/guide"],
    "executable": "RACT (the egress ledger's client)",
    "cwd": "none",
    "network": "on, to example.invalid",
    "sandbox": "not a command: RACT fetches it itself",
    "rule": "network_tools.web_fetch",
    "why": "example.invalid is on allow_domains",
    "reason": "the model's reason",
    "notes": ["what comes back is external data; it cannot approve anything"],
    "follows": "",
    "session_choice": True,
    # The network screen's own facts:
    "url": "https://example.invalid/guide",
    "host": "example.invalid",
    "allowlist_match": "example.invalid",
    "size_cap_kib": 256,
    "follows_external": True,
}

COMMAND_FACTS = {
    "argv": ["pytest", "-q"],
    "executable": "/usr/bin/pytest",
    "cwd": ".",
    "network": "off",
    "sandbox": "not enforced on this machine",
    "rule": "tests.pytest",
    "why": "the operator's rule",
    "reason": "run the tests",
    "notes": [],
    "follows": "",
    "session_choice": True,
}


def _ask(*answers: str):
    queue = list(answers)

    def ask(prompt: str) -> str:
        return queue.pop(0) if queue else "n"

    return ask


def test_a_fetch_question_uses_the_network_screen(monkeypatch, capsys) -> None:
    monkeypatch.setattr("ract.approval_callback.read_line", _ask("n"))
    code = console_tier_3_prompt(dict(FETCH_FACTS))
    out = capsys.readouterr().out
    assert code is False
    # The network screen's own lines, which the command screen never prints:
    assert "fetch from the web (tier 3)" in out
    assert "host: example.invalid" in out
    assert "allowlist: matches example.invalid" in out
    assert "size cap: 256 KiB" in out
    assert "follows fetched text" in out  # B-149


def test_a_fetch_without_a_session_answer_never_advertises_one(
    monkeypatch, capsys
) -> None:
    facts = dict(FETCH_FACTS)
    facts["session_choice"] = False  # the one-shot CLI path (no SessionApprovals)
    prompts: list[str] = []

    def ask(prompt: str) -> str:
        prompts.append(prompt)
        return "n"

    monkeypatch.setattr("ract.approval_callback.read_line", ask)
    code = console_tier_3_prompt(facts)
    out = capsys.readouterr().out
    assert code is False
    assert "s for this session" not in out  # the no-session prompt accepts only y/yes
    assert prompts == ["Run it once? [y/N]: "]  # and offers no session answer


def test_a_command_question_still_uses_the_command_screen(
    monkeypatch, capsys
) -> None:
    monkeypatch.setattr("ract.approval_callback.read_line", _ask("n"))
    code = console_tier_3_prompt(dict(COMMAND_FACTS))
    out = capsys.readouterr().out
    assert code is False
    assert "/usr/bin/pytest" in out  # the command screen shows the executable
    assert "runs it once" in out
