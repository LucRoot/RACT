"""UX gap package F and soak: the setup prompt's text and its Ctrl-C."""

from __future__ import annotations

from ract import cli


def test_setup_question_fits_sixty_columns(monkeypatch, capsys):
    # Soak, 60 columns: the first line of the setup prompt was 73 columns.
    monkeypatch.setenv("COLUMNS", "60")
    cli._offer_setup(ask=lambda prompt: "n")
    first = capsys.readouterr().out.splitlines()[0]
    assert len(first) <= 60, first


def test_ctrl_c_at_the_setup_prompt_says_no_config_was_written(capsys):
    # Error sweep row 15: Ctrl-C at the setup question printed nothing.
    def interrupted(prompt):
        raise KeyboardInterrupt

    assert cli._offer_setup(ask=interrupted) is False
    assert "Setup stopped; no ract.yaml was written." in capsys.readouterr().out
