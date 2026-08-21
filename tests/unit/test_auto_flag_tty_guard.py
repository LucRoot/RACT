"""``--auto`` requires a TTY; headless invocations refuse loudly (Lens A M4).

v0.5.1 wiring module_10: prior behavior deadlocked silently in CI /
Docker / nohup because :func:`console_approval_callback` fell back to
``EOFError -> reject`` on every step. The guard here refuses at the
CLI boundary with a clear diagnostic instead.
"""

from __future__ import annotations

import contextlib
import io
from unittest.mock import patch

from ract.cli import main


def test_auto_on_headless_stdin_refuses_with_exit_two() -> None:
    """``ract --auto "..."`` on a non-TTY stdin exits 2 with a diagnostic."""
    stderr = io.StringIO()
    stdout = io.StringIO()
    with (
        contextlib.redirect_stdout(stdout),
        contextlib.redirect_stderr(stderr),
        patch("sys.stdin") as fake_stdin,
    ):
        fake_stdin.isatty.return_value = False
        code = main(["--auto", "some intent"])
    assert code == 2, f"expected exit 2 on headless --auto; got {code}"
    combined = stderr.getvalue() + stdout.getvalue()
    assert "TTY" in combined or "yolo" in combined.lower()


def test_yolo_and_auto_are_mutually_exclusive() -> None:
    """Argparse rejects ``--yolo --auto`` combination (Lens A N2)."""
    stderr = io.StringIO()
    stdout = io.StringIO()
    # Argparse exits with SystemExit(2) on mutex violation.
    try:
        with (
            contextlib.redirect_stdout(stdout),
            contextlib.redirect_stderr(stderr),
        ):
            main(["--yolo", "--auto", "some intent"])
    except SystemExit as exc:
        assert exc.code == 2
    combined = stderr.getvalue() + stdout.getvalue()
    assert "not allowed" in combined.lower() or "mutual" in combined.lower() or \
        "--yolo" in combined


# RACT 0.5.1 -- v0.5.1 wiring module_10 (Lens A M4 + N2 regression)
