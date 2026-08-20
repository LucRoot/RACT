"""Sandbox environ allowlist -- security tests (v0.5.1 module_05).

Locks REVIEW_4_UNKNOWN §D1 (data-exfil via ``os.environ.copy()``):
sandbox init must build the child environment from a strict allowlist,
never from a blacklist over the parent env. Any name-shaped-like-a-
secret that lives on the harness process must NEVER appear in the
sandbox subprocess env unless the operator explicitly declared it.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from ract.security.sandbox_env import (
    ALLOWLIST_FILE_NAME,
    AllowlistFileMalformed,
    DEFAULT_ALLOWLIST,
    NEVER_PASSTHROUGH,
    build_sandbox_env,
    default_allowlist_path,
    load_allowlist_file,
)


# ---------------------------------------------------------------------------
# The load-bearing D1 test
# ---------------------------------------------------------------------------


def test_secret_token_absent_from_sandbox_env(caplog: pytest.LogCaptureFixture) -> None:
    """Seed process env with a fake SECRET_TOKEN; sandbox must not carry it."""
    seeded = {
        "PATH": "/usr/bin",
        "HOME": "/home/lucas",
        "SECRET_TOKEN": "sk-xxxxxxxxxxxx",
        "MY_ENTERPRISE_TOKEN": "abcdef123",
        "GITHUB_TOKEN": "ghp_notreal",
    }
    with caplog.at_level(logging.WARNING, logger="ract.security.sandbox_env"):
        result = build_sandbox_env(process_env=seeded)
    assert "SECRET_TOKEN" not in result.env, (
        "SECRET_TOKEN slipped past the allowlist -- D1 data-exfil defect"
    )
    assert "MY_ENTERPRISE_TOKEN" not in result.env
    assert "GITHUB_TOKEN" not in result.env
    # Standard vars survive.
    assert result.env.get("PATH") == "/usr/bin"
    assert result.env.get("HOME") == "/home/lucas"
    # WARN fired with count-only (never the value).
    warn_text = " ".join(rec.message for rec in caplog.records)
    assert "scrubbed" in warn_text
    assert "SECRET_TOKEN" not in warn_text  # NAME is not logged
    assert "MY_ENTERPRISE_TOKEN" not in warn_text
    assert result.scrubbed_count == 3


def test_never_passthrough_blocks_even_declared_allowlist(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """Even if an operator lists ``OPENAI_API_KEY`` in the manifest, refuse."""
    seeded = {
        "PATH": "/usr/bin",
        "OPENAI_API_KEY": "sk-xxxx",
    }
    with caplog.at_level(logging.WARNING, logger="ract.security.sandbox_env"):
        result = build_sandbox_env(
            process_env=seeded,
            manifest_passthrough=("OPENAI_API_KEY",),
        )
    assert "OPENAI_API_KEY" not in result.env
    assert result.never_passthrough_denied == 1


def test_never_passthrough_covers_named_secrets() -> None:
    for name in (
        "AWS_ACCESS_KEY_ID",
        "AWS_SECRET_ACCESS_KEY",
        "GITHUB_TOKEN",
        "OPENAI_API_KEY",
        "ANTHROPIC_API_KEY",
        "ANTHROPIC_AUTH_TOKEN",
    ):
        assert name in NEVER_PASSTHROUGH


def test_default_allowlist_includes_standard_names() -> None:
    for name in ("PATH", "HOME", "USER", "TMPDIR", "LANG", "TZ"):
        assert name in DEFAULT_ALLOWLIST
    # Windows equivalents.
    for name in ("USERPROFILE", "TEMP", "SYSTEMROOT"):
        assert name in DEFAULT_ALLOWLIST


# ---------------------------------------------------------------------------
# Manifest passthrough
# ---------------------------------------------------------------------------


def test_manifest_passthrough_admits_named_env_var() -> None:
    """An operator-declared name lands in the sandbox env when set."""
    seeded = {"PATH": "/usr/bin", "MY_BUILD_ID": "42"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("MY_BUILD_ID",)
    )
    assert result.env["MY_BUILD_ID"] == "42"


def test_manifest_passthrough_absent_var_silent_pass() -> None:
    """Manifest names a var that is not set; do not fabricate it."""
    seeded = {"PATH": "/usr/bin"}
    result = build_sandbox_env(
        process_env=seeded, manifest_passthrough=("NOT_SET_ANYWHERE",)
    )
    assert "NOT_SET_ANYWHERE" not in result.env


# ---------------------------------------------------------------------------
# Allowlist file
# ---------------------------------------------------------------------------


def test_load_allowlist_file_parses_valid_entries(tmp_path: Path) -> None:
    p = tmp_path / ".ract" / ALLOWLIST_FILE_NAME
    p.parent.mkdir(parents=True)
    p.write_text(
        "\n".join(
            [
                "# comment",
                "",
                '"MY_VAR"',
                '"BUILD_ID"',
            ]
        ),
        encoding="utf-8",
    )
    entries = load_allowlist_file(p)
    assert entries == ("MY_VAR", "BUILD_ID")


def test_load_allowlist_missing_file_returns_empty(tmp_path: Path) -> None:
    entries = load_allowlist_file(tmp_path / "nope")
    assert entries == ()


def test_load_allowlist_malformed_line_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad"
    p.write_text('not_a_json_string\n"OK"\n', encoding="utf-8")
    with pytest.raises(AllowlistFileMalformed):
        load_allowlist_file(p)


def test_load_allowlist_non_string_entry_raises(tmp_path: Path) -> None:
    p = tmp_path / "bad2"
    p.write_text("42\n", encoding="utf-8")
    with pytest.raises(AllowlistFileMalformed, match="JSON strings"):
        load_allowlist_file(p)


def test_default_allowlist_path_composes_dot_ract(tmp_path: Path) -> None:
    p = default_allowlist_path(tmp_path)
    assert p == tmp_path / ".ract" / "sandbox_env.allowlist"


def test_allowlist_file_source_admits_names(tmp_path: Path) -> None:
    """End-to-end: file source overrides default when compatible."""
    p = tmp_path / ".ract" / ALLOWLIST_FILE_NAME
    p.parent.mkdir(parents=True)
    p.write_text('"CI_PROJECT_ID"\n', encoding="utf-8")
    seeded = {"CI_PROJECT_ID": "42"}
    result = build_sandbox_env(
        process_env=seeded,
        allowlist_file=p,
        include_default=False,
    )
    assert result.env == {"CI_PROJECT_ID": "42"}
    assert result.allowlist_source == "file"


# ---------------------------------------------------------------------------
# Include_default toggle
# ---------------------------------------------------------------------------


def test_include_default_false_narrows_to_manifest_only() -> None:
    seeded = {"PATH": "/usr/bin", "MY_VAR": "x"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("MY_VAR",),
        include_default=False,
    )
    # PATH is a DEFAULT-only allowlist entry -- must be absent.
    assert "PATH" not in result.env
    assert result.env == {"MY_VAR": "x"}


# ---------------------------------------------------------------------------
# extra_denied
# ---------------------------------------------------------------------------


def test_extra_denied_blocks_operator_custom_secret() -> None:
    seeded = {"PATH": "/usr/bin", "MY_CUSTOM_TOKEN": "xxx"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("MY_CUSTOM_TOKEN",),
        extra_denied=("MY_CUSTOM_TOKEN",),
    )
    assert "MY_CUSTOM_TOKEN" not in result.env
    assert result.never_passthrough_denied == 1


# ---------------------------------------------------------------------------
# WARN log discipline (never leak values)
# ---------------------------------------------------------------------------


def test_warn_never_carries_secret_value(caplog: pytest.LogCaptureFixture) -> None:
    seeded = {"PATH": "/x", "SECRET_TOKEN": "the-actual-secret-value"}
    with caplog.at_level(logging.WARNING, logger="ract.security.sandbox_env"):
        build_sandbox_env(process_env=seeded)
    for record in caplog.records:
        assert "the-actual-secret-value" not in record.getMessage()


# RACT 0.5.1
