"""B-111 (ADR-0048 D2, amendment 9): the unlock window keeps the signing key in memory only.

Off by default where the grant says ``sandbox: best_effort``, 10 minutes where
commands are confined, ``unlock_window_minutes`` in user config, 0 disables,
closed by ``/permissions lock``. Throwaway keys in temporary folders only.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.policy.operator_key import generate
from ract.policy.unlock import UnlockWindow, window_minutes

PASS = "throwaway passphrase for a test"


@pytest.fixture
def cfg(tmp_path: Path) -> Path:
    folder = tmp_path / "config"
    generate(PASS, config=folder)
    return folder


class Clock:
    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now


def _asked() -> tuple[list[str], object]:
    asked: list[str] = []

    def read(prompt: str = "", **_kw: object) -> str:
        asked.append(prompt)
        return PASS

    return asked, read


def test_best_effort_asks_every_time(cfg: Path) -> None:
    assert window_minutes("best_effort", cfg) == 0
    window = UnlockWindow()
    asked, read = _asked()
    for _ in range(3):
        window.signing_key(read, minutes=window_minutes("best_effort", cfg), config=cfg)
    assert len(asked) == 3 and not window.is_open


def test_confined_keeps_it_ten_minutes(cfg: Path) -> None:
    assert window_minutes("enforced", cfg) == 10
    clock = Clock()
    window = UnlockWindow(clock)
    asked, read = _asked()
    first = window.signing_key(read, minutes=10, config=cfg)
    clock.now += 9 * 60
    assert window.signing_key(read, minutes=10, config=cfg) is first
    assert len(asked) == 1
    clock.now += 2 * 60  # past ten minutes
    window.signing_key(read, minutes=10, config=cfg)
    assert len(asked) == 2


def test_the_user_config_sets_it_and_zero_disables(cfg: Path) -> None:
    config_file = cfg / "config.yaml"
    config_file.write_text(
        config_file.read_text(encoding="utf-8") + "unlock_window_minutes: 3\n",
        encoding="utf-8",
    )
    assert window_minutes("best_effort", cfg) == 3
    config_file.write_text(
        config_file.read_text(encoding="utf-8").replace(
            "unlock_window_minutes: 3", "unlock_window_minutes: 0"
        ),
        encoding="utf-8",
    )
    assert window_minutes("enforced", cfg) == 0
    for bad in ("-1", "true", "'ten'"):
        config_file.write_text(
            "\n".join(
                line
                for line in config_file.read_text(encoding="utf-8").splitlines()
                if not line.startswith("unlock_window_minutes")
            )
            + f"\nunlock_window_minutes: {bad}\n",
            encoding="utf-8",
        )
        assert (
            window_minutes("best_effort", cfg) == 0
        )  # an invalid value keeps the default


def test_lock_closes_it(cfg: Path) -> None:
    window = UnlockWindow(Clock())
    asked, read = _asked()
    window.signing_key(read, minutes=10, config=cfg)
    assert window.is_open
    window.lock()
    assert not window.is_open
    window.signing_key(read, minutes=10, config=cfg)
    assert len(asked) == 2


def test_permissions_lock_in_the_session(tmp_path: Path, cfg: Path) -> None:
    from ract.policy.unlock import SESSION_WINDOW
    from tests.test_repl import _session

    asked, read = _asked()
    SESSION_WINDOW.signing_key(read, minutes=10, config=cfg)
    assert SESSION_WINDOW.is_open
    session, _, console = _session(config=tmp_path / "ract.yaml")
    session.handle("/permissions")
    assert (
        "Signing key: unlocked in memory; /permissions lock closes it." in console.text
    )
    session.handle("/permissions lock")
    assert not SESSION_WINDOW.is_open
    assert "Signing key locked" in console.text


def test_the_window_writes_nothing_to_disk(cfg: Path) -> None:
    before = sorted(p.relative_to(cfg).as_posix() for p in cfg.rglob("*"))
    window = UnlockWindow(Clock())
    _asked_list, read = _asked()
    window.signing_key(read, minutes=10, config=cfg)
    after = sorted(p.relative_to(cfg).as_posix() for p in cfg.rglob("*"))
    assert after == before
