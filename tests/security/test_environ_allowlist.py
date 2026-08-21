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


# ---------------------------------------------------------------------------
# SP amendments (module_05, OpenRouter DEFECT verdicts)
# ---------------------------------------------------------------------------


def test_sp_q3a_case_variant_secret_blocked() -> None:
    """SP Q3(a): lowercase / mixed-case credential name still refuses."""
    seeded = {
        "PATH": "/x",
        "aws_access_key_id": "AKIA",
        "Anthropic_Api_Key": "sk-lower",
    }
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("aws_access_key_id", "Anthropic_Api_Key"),
    )
    assert "aws_access_key_id" not in result.env
    assert "Anthropic_Api_Key" not in result.env
    assert result.never_passthrough_denied >= 2


def test_sp_q3a_prefix_family_blocks_new_aws_variant() -> None:
    """SP Q3(a): AWS_NEW_TOKEN (not in NEVER_PASSTHROUGH) refused via prefix."""
    seeded = {"AWS_NEW_TOKEN_2028": "x"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("AWS_NEW_TOKEN_2028",),
    )
    assert "AWS_NEW_TOKEN_2028" not in result.env
    assert result.never_passthrough_denied == 1


def test_sp_q3a_glob_shape_in_manifest_refused() -> None:
    """SP Q3(a): a manifest entry ``AWS_*`` refuses -- glob is not a name."""
    seeded = {"AWS_SECRET_ACCESS_KEY": "sk"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("AWS_*",),
    )
    # Neither AWS_* nor any AWS_ var enters the sandbox.
    assert "AWS_SECRET_ACCESS_KEY" not in result.env
    assert result.never_passthrough_denied >= 1


def test_sp_q3b_warn_log_redacts_credential_name(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """SP Q3(b): WARN log carries a REDACTED family, not the full name."""
    seeded = {"OPENAI_API_KEY_PROD": "sk"}
    with caplog.at_level(logging.WARNING, logger="ract.security.sandbox_env"):
        build_sandbox_env(
            process_env=seeded,
            manifest_passthrough=("OPENAI_API_KEY_PROD",),
        )
    for record in caplog.records:
        msg = record.getMessage()
        if "denied" in msg.lower():
            assert "OPENAI_API_KEY_PROD" not in msg
            assert "REDACTED" in msg


def test_sp_q3d_bom_at_file_start_stripped(tmp_path: Path) -> None:
    """SP Q3(d): UTF-8 BOM at file start no longer trips JSONDecodeError."""
    p = tmp_path / "allowlist"
    p.write_bytes(b'\xef\xbb\xbf"MY_VAR"\n"OTHER"\n')
    entries = load_allowlist_file(p)
    assert entries == ("MY_VAR", "OTHER")


def test_sp_q3d_trailing_comma_lenient_recovery(tmp_path: Path) -> None:
    """SP Q3(d): a single trailing comma per line recovers, not raises."""
    p = tmp_path / "allowlist"
    p.write_text('"MY_VAR",\n"OTHER",\n', encoding="utf-8")
    entries = load_allowlist_file(p)
    assert entries == ("MY_VAR", "OTHER")


# ---------------------------------------------------------------------------
# v0.5.1 wiring module_04 SP Q6 amendment -- credential-shape heuristic
# ---------------------------------------------------------------------------


def test_sp_wq6_credential_shape_heuristic_counts_new_family(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A new credential family (e.g., MYCO_INTERNAL_TOKEN) is counted.

    SP Q6 (OpenRouter DEFECT verdict): a name shaped like a
    credential (suffix _TOKEN / _KEY / _SECRET / ...) that is NOT
    in NEVER_PASSTHROUGH would silently pass through, giving the
    operator a false impression of safety. The heuristic now bumps
    ``credential_shaped_unblocked_count`` and WARN-logs a redacted
    form so trace-log audits catch the miss.

    Backward-compat: the name IS still passed through (some
    legitimate build systems declare ``BUILD_SIGNING_KEY_PATH``);
    the counter is the SIGNAL, not a hard denial.
    """
    from ract.security.sandbox_env import build_sandbox_env

    seeded = {
        "PATH": "/usr/bin",
        # Credential-shape but not in NEVER_PASSTHROUGH:
        "MYCO_INTERNAL_TOKEN": "sk-x",
        "CLAUDE_LEGACY_SECRET": "sk-y",
    }
    with caplog.at_level(logging.WARNING, logger="ract.security.sandbox_env"):
        result = build_sandbox_env(
            process_env=seeded,
            manifest_passthrough=("MYCO_INTERNAL_TOKEN", "CLAUDE_LEGACY_SECRET", "PATH"),
        )
    # Names ARE passed (backward-compat) but heuristic counts them.
    assert "MYCO_INTERNAL_TOKEN" in result.env
    assert "CLAUDE_LEGACY_SECRET" in result.env
    assert result.credential_shaped_unblocked_count == 2
    # WARN log fired with REDACTED name family.
    warn_text = " ".join(rec.message for rec in caplog.records)
    assert "credential-shaped" in warn_text or "credential-shape" in warn_text.lower()


def test_sp_wq6_credential_shape_heuristic_ignores_denied_family() -> None:
    """A name already caught by NEVER_PASSTHROUGH does NOT double-count.

    A name matching both the deny surface AND the credential-shape
    suffix (e.g., OPENAI_API_KEY -- has _API and _KEY suffixes but
    is denied) should count under ``never_passthrough_denied``, not
    under ``credential_shaped_unblocked_count`` (the heuristic is
    for gaps in the deny surface, not for redundant flagging).
    """
    from ract.security.sandbox_env import build_sandbox_env

    seeded = {"OPENAI_API_KEY": "sk-x", "PATH": "/usr/bin"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("OPENAI_API_KEY", "PATH"),
    )
    assert "OPENAI_API_KEY" not in result.env
    assert result.never_passthrough_denied == 1
    assert result.credential_shaped_unblocked_count == 0


def test_sp_wq6_credential_shape_heuristic_ignores_benign_names() -> None:
    """A non-credential-shaped name does NOT trip the heuristic."""
    from ract.security.sandbox_env import build_sandbox_env

    seeded = {"PATH": "/usr/bin", "BUILD_ID": "42", "MY_VAR": "x"}
    result = build_sandbox_env(
        process_env=seeded,
        manifest_passthrough=("BUILD_ID", "MY_VAR", "PATH"),
    )
    assert result.credential_shaped_unblocked_count == 0


def test_sp_q3d_still_refuses_wholly_malformed(tmp_path: Path) -> None:
    """SP Q3(d): a line that isn't a JSON string still raises."""
    from ract.security.sandbox_env import AllowlistFileMalformed

    p = tmp_path / "allowlist"
    p.write_text("not valid at all\n", encoding="utf-8")
    with pytest.raises(AllowlistFileMalformed):
        load_allowlist_file(p)


# RACT 0.5.1
