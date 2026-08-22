"""Regression -- module_04 subprocess run_id env plumbing (DA-B F-3.1).

v0.5.2 hardening module_04. Locks the F-3.1 fix + the Ox Alpha
co-build Bug #3 fold (async ContextVar race, single-source-of-truth
capture per spawn):

- Ambient run_id at spawn time appears in child ``env`` under
  ``RACT_RUN_ID`` (via
  :meth:`SubstrateLoop.spawn_step_subprocess`).
- Attacker-supplied ``RACT_RUN_ID=victim`` in parent env is STRIPPED
  by :func:`strip_ract_internal_keys` and RACT's own value wins.
- Prefix strip (Ox Alpha Fork 4): any ``RACT_*`` key in parent env
  is stripped, not just the enumerated set (forward-compat
  hardening).
- Absent ambient AND absent env → subagent's
  :func:`bootstrap_ambient_from_env` generates
  ``RUN-ORPHAN-{uuid}``.
"""

from __future__ import annotations

import os
import subprocess
import sys
import uuid
from pathlib import Path

import pytest

from ract.runtime import (
    RACT_RUN_ID_ENV_KEY,
    bind_run_id,
    bootstrap_ambient_from_env,
    get_current_run_id,
    set_current_run_id,
)
from ract.security.sandbox_env import (
    RACT_INTERNAL_ENV_KEYS,
    strip_ract_internal_keys,
)
from ract.executor.loop import _inject_ract_run_id_env, _capture_ambient_run_id_once


# ---- Env plumbing ----------------------------------------------------------


def _hex_run_id() -> str:
    return uuid.uuid4().hex


def test_inject_ract_run_id_env_adds_ambient_when_bound() -> None:
    """When an ambient is bound, spawn env carries RACT_RUN_ID."""
    rid = _hex_run_id()
    with bind_run_id(rid):
        ambient = _capture_ambient_run_id_once()
        out = _inject_ract_run_id_env({"PATH": "/usr/bin"}, ambient)
    assert out is not None
    assert out.get(RACT_RUN_ID_ENV_KEY) == rid
    assert out.get("PATH") == "/usr/bin"


def test_inject_ract_run_id_env_none_env_none_ambient_strips_and_passes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env dict + no ambient: SP amendment (Ox B S1) strips
    RACT_* from os.environ + returns cleaned env (no reinject).

    Pre-amendment this returned None (child inherits parent
    os.environ wholesale). Post-amendment: strip-and-inherit so
    a subprocess spawned without an active run STILL cannot see
    an attacker's parent-shell RACT_* key.
    """
    monkeypatch.setenv("RACT_UNKNOWN_FUTURE_KEY", "poison")
    monkeypatch.setenv(RACT_RUN_ID_ENV_KEY, "victim")
    # Explicitly no ambient bound in this test.
    set_current_run_id(None)
    out = _inject_ract_run_id_env(None, None)
    assert out is not None
    assert "RACT_UNKNOWN_FUTURE_KEY" not in out
    assert RACT_RUN_ID_ENV_KEY not in out


def test_inject_ract_run_id_env_none_env_with_ambient_strips_and_reinjects(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No env dict + ambient bound: SP amendment (Ox B S1) strips
    RACT_* from os.environ + reinjects captured ambient. Full
    os.environ passes through so PATH/HOME survive."""
    monkeypatch.setenv("RACT_UNKNOWN_FUTURE_KEY", "poison")
    monkeypatch.setenv(RACT_RUN_ID_ENV_KEY, "victim")
    rid = _hex_run_id()
    with bind_run_id(rid):
        ambient = _capture_ambient_run_id_once()
        out = _inject_ract_run_id_env(None, ambient)
    assert out is not None
    assert out[RACT_RUN_ID_ENV_KEY] == rid
    assert "RACT_UNKNOWN_FUTURE_KEY" not in out
    # PATH survives (real os.environ entry passed through).
    assert "PATH" in out or "Path" in out


# ---- Attacker sneak-vector defense -----------------------------------------


def test_parent_env_ract_run_id_stripped_before_reinject() -> None:
    """Attacker sets RACT_RUN_ID=victim; RACT's ambient value wins."""
    real_rid = _hex_run_id()
    victim_rid = "poisoned-victim-run-id-not-ract-controlled"
    parent_env = {
        "PATH": "/usr/bin",
        RACT_RUN_ID_ENV_KEY: victim_rid,
    }
    with bind_run_id(real_rid):
        ambient = _capture_ambient_run_id_once()
        out = _inject_ract_run_id_env(parent_env, ambient)
    assert out is not None
    assert out[RACT_RUN_ID_ENV_KEY] == real_rid
    assert out[RACT_RUN_ID_ENV_KEY] != victim_rid


def test_strip_ract_internal_keys_removes_ract_prefix_family() -> None:
    """Ox Alpha Fork 4: strip-by-PREFIX. Any RACT_* key removed."""
    env = {
        "PATH": "/usr/bin",
        "RACT_RUN_ID": "victim",
        "RACT_FUTURE_KEY_NOT_YET_ENUMERATED": "attacker",
        "SAFE_VAR": "keep",
    }
    cleaned, stripped = strip_ract_internal_keys(env)
    assert "RACT_RUN_ID" not in cleaned
    assert "RACT_FUTURE_KEY_NOT_YET_ENUMERATED" not in cleaned
    assert cleaned["PATH"] == "/usr/bin"
    assert cleaned["SAFE_VAR"] == "keep"
    assert set(stripped) == {
        "RACT_RUN_ID",
        "RACT_FUTURE_KEY_NOT_YET_ENUMERATED",
    }


def test_strip_ract_internal_keys_preserves_non_ract_vars() -> None:
    """A dict with no RACT_* keys is a shallow copy, no strip."""
    env = {"PATH": "/x", "HOME": "/y", "PYTHONPATH": "/z"}
    cleaned, stripped = strip_ract_internal_keys(env)
    assert cleaned == env
    assert stripped == []


def test_ract_run_id_env_key_registered_in_internal_set() -> None:
    """RACT_RUN_ID must be in the registered internal set."""
    assert RACT_RUN_ID_ENV_KEY in RACT_INTERNAL_ENV_KEYS


# ---- Orphan fallback -------------------------------------------------------


def test_bootstrap_ambient_generates_orphan_when_env_absent() -> None:
    """No RACT_RUN_ID in env → synthetic RUN-ORPHAN-* + bound."""
    fresh_env: dict[str, str] = {"PATH": "/usr/bin"}
    rid = bootstrap_ambient_from_env(env=fresh_env, emit_events=False)
    assert rid.startswith("RUN-ORPHAN-")
    assert len(rid) > len("RUN-ORPHAN-")
    # And the ambient is bound.
    assert get_current_run_id() == rid
    # Cleanup: unset for other tests.
    set_current_run_id(None)


def test_bootstrap_ambient_uses_env_when_present() -> None:
    """RACT_RUN_ID present → that value is bound as ambient."""
    rid = _hex_run_id()
    fresh_env = {"PATH": "/usr/bin", RACT_RUN_ID_ENV_KEY: rid}
    bound = bootstrap_ambient_from_env(env=fresh_env, emit_events=False)
    assert bound == rid
    assert get_current_run_id() == rid
    set_current_run_id(None)


def test_bootstrap_ambient_empty_env_value_treated_as_absent() -> None:
    """RACT_RUN_ID='' treated as absent (orphan generated)."""
    fresh_env = {"PATH": "/usr/bin", RACT_RUN_ID_ENV_KEY: ""}
    rid = bootstrap_ambient_from_env(env=fresh_env, emit_events=False)
    assert rid.startswith("RUN-ORPHAN-")
    set_current_run_id(None)


# ---- End-to-end subprocess round-trip --------------------------------------


def test_subprocess_child_sees_parent_ambient_run_id() -> None:
    """End-to-end: parent binds ambient, spawn writes RACT_RUN_ID,
    child (this same Python) reads it back."""
    rid = _hex_run_id()

    script = (
        "import os, sys; "
        f"assert os.environ.get({RACT_RUN_ID_ENV_KEY!r}) == {rid!r}, "
        "'child did not see parent RACT_RUN_ID'; "
        "sys.exit(0)"
    )
    with bind_run_id(rid):
        ambient = _capture_ambient_run_id_once()
        env = _inject_ract_run_id_env(dict(os.environ), ambient)
        assert env is not None
        assert env[RACT_RUN_ID_ENV_KEY] == rid
        result = subprocess.run(
            [sys.executable, "-c", script],
            env=env,
            capture_output=True,
            timeout=30,
        )
    assert result.returncode == 0, (
        f"child failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )


def test_subprocess_child_orphan_generates_when_no_env() -> None:
    """End-to-end: child invoked with no RACT_RUN_ID generates orphan."""
    script = (
        "from ract.runtime import bootstrap_ambient_from_env; "
        "rid = bootstrap_ambient_from_env(emit_events=False); "
        "print(rid)"
    )
    # Explicitly strip RACT_RUN_ID from child env even if this test
    # process has it.
    child_env = {
        k: v for k, v in os.environ.items() if k.upper() != RACT_RUN_ID_ENV_KEY
    }
    result = subprocess.run(
        [sys.executable, "-c", script],
        env=child_env,
        capture_output=True,
        timeout=30,
        text=True,
    )
    assert result.returncode == 0, (
        f"child failed: stdout={result.stdout!r} stderr={result.stderr!r}"
    )
    assert result.stdout.strip().startswith("RUN-ORPHAN-")
