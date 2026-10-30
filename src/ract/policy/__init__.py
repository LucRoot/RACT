"""The operator's tier-3 policy: the key, the signed grant, its layers (ADR-0048 D2, D3).

LR:: Tier 3 stays off by default (``RACT_TIER_3_ENABLED`` is False and no
code edit loosens it). A project opens it only through a grant the operator
signs with a key that lives outside every workspace and is encrypted with a
passphrase typed at a terminal. ``operator_key`` holds that key; the grant
loader and the status line build on it.
"""

from __future__ import annotations

import os
from pathlib import Path


def config_dir() -> Path:
    """The user config directory for RACT: ``%APPDATA%\\ract`` or ``~/.config/ract``.

    Never inside a workspace (ADR-0048 D2). The test run points it at a
    temporary folder, so no test reaches the operator's key or pins.
    """
    if os.name == "nt":
        appdata = os.environ.get("APPDATA")
        if appdata:
            return Path(appdata) / "ract"
        return Path.home() / "AppData" / "Roaming" / "ract"
    xdg = os.environ.get("XDG_CONFIG_HOME")
    if xdg:
        return Path(xdg) / "ract"
    return Path.home() / ".config" / "ract"


__all__ = ["config_dir"]
