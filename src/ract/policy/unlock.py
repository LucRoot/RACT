"""The unlock window: the decrypted operator key kept in memory for a while (ADR-0048 D2).

LR:: After the operator types the passphrase, the signing key may stay in
this process's memory so the next signature does not ask again. The window
is off by default where the grant says ``sandbox: best_effort`` (Windows
without WSL2 or a container: every signature asks), and 10 minutes where
commands are confined. ``unlock_window_minutes`` in the user config changes
it; 0 disables it. The key is never written to disk, the window closes on
exit or ``/permissions lock``, and it covers signing only: it never answers
an approval, which is asked at the terminal every time.
"""

from __future__ import annotations

import sys

import time
from collections.abc import Callable
from typing import Any

from ract.policy.operator_key import unlock

DEFAULT_CONFINED_MINUTES = 10
# The longest window a user config may ask for (G-213 U1).
MAX_MINUTES = 60


def window_minutes(sandbox: str, config: Any = None) -> float:
    """The window for a grant whose sandbox is *sandbox*, from the user config."""
    from ract.policy.operator_key import _config_file

    configured = None
    path = _config_file(config)
    if path.is_file():
        import yaml

        try:
            data = yaml.safe_load(path.read_text(encoding="utf-8"))
        except (OSError, yaml.YAMLError) as exc:
            # stdout belongs to the --json runs; diagnostics go to stderr.
            print(
                f"[unlock] the user config cannot be read: {exc}",
                file=sys.stderr,
                flush=True,
            )
            data = None
        value = data.get("unlock_window_minutes") if isinstance(data, dict) else None
        if (
            isinstance(value, (int, float))
            and not isinstance(value, bool)
            and value >= 0
        ):
            configured = min(float(value), float(MAX_MINUTES))
    if configured is not None:
        return configured
    return 0.0 if sandbox == "best_effort" else float(DEFAULT_CONFINED_MINUTES)


class UnlockWindow:
    """Holds the unlocked signing key for *minutes*, in memory only."""

    def __init__(self, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._key: Any = None
        self._until = 0.0

    def signing_key(
        self,
        read_passphrase: Callable[..., str],
        *,
        minutes: float,
        config: Any = None,
    ) -> Any:
        """The private key: from the window while it is open, else asked for."""
        if self._key is not None and self._clock() < self._until:
            return self._key
        self.lock()
        key = unlock(read_passphrase("Passphrase: "), config)
        if minutes > 0:
            self._key = key
            self._until = self._clock() + minutes * 60
        return key

    def lock(self) -> None:
        """Close the window now (exit, ``/permissions lock``)."""
        self._key = None
        self._until = 0.0

    @property
    def is_open(self) -> bool:
        return self._key is not None and self._clock() < self._until


# The process's one window: ``ract policy sign`` and the session use it, and
# ``/permissions lock`` closes it.
SESSION_WINDOW = UnlockWindow()

__all__ = [
    "DEFAULT_CONFINED_MINUTES",
    "SESSION_WINDOW",
    "UnlockWindow",
    "window_minutes",
]


def window_note(config: Any = None) -> str | None:
    """What ``ract doctor`` says when the configured window is over the cap (U1)."""
    from ract.policy.operator_key import _config_file

    path = _config_file(config)
    if not path.is_file():
        return None
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        print(
            f"[unlock] the user config cannot be read: {exc}",
            file=sys.stderr,
            flush=True,
        )
        return None
    value = data.get("unlock_window_minutes") if isinstance(data, dict) else None
    if (
        isinstance(value, (int, float))
        and not isinstance(value, bool)
        and value > MAX_MINUTES
    ):
        return f"unlock_window_minutes {value:g} is read as {MAX_MINUTES}, the most it may be"
    return None
