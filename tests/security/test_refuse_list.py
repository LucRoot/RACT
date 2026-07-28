"""Security tests for the RACT refuse-list and capability tiers."""

from __future__ import annotations

from ract.core.threat_model import (
    CapabilityTier,
    PolicyDecision,
    authorize_action,
    classify_action,
)
from ract.core.types import Digest


def test_tier_0_read_allowed():
    action = {"action": "read file src/foo.py", "expected_artifact": "src/foo.py"}
    assert classify_action(action) is CapabilityTier.TIER_0_READ
    auth = authorize_action(action, "/workspace")
    assert auth.allowed
    assert auth.decision is PolicyDecision.ALLOW


def test_tier_1_write_classified():
    action = {"action": "write file src/foo.py", "expected_artifact": "src/foo.py"}
    assert classify_action(action) is CapabilityTier.TIER_1_WRITE


def test_tier_1_write_inside_workspace_allowed(tmp_path):
    action = {"action": "write file src/foo.py", "expected_artifact": "src/foo.py"}
    auth = authorize_action(action, tmp_path)
    assert auth.allowed
    assert auth.decision is PolicyDecision.ALLOW_WITH_ROOTKNOT


def test_tier_1_write_outside_workspace_refused(tmp_path):
    action = {
        "action": "write file /etc/passwd",
        "expected_artifact": "/etc/passwd",
    }
    auth = authorize_action(action, tmp_path)
    assert not auth.allowed
    assert auth.decision is PolicyDecision.REFUSE
    assert any("outside workspace" in r.reason for r in auth.refusals)


def test_tier_2_env_requires_handshake(tmp_path):
    action = {"action": "pip install pytest", "expected_artifact": ""}
    assert classify_action(action) is CapabilityTier.TIER_2_ENV
    auth = authorize_action(action, tmp_path)
    assert auth.allowed
    assert auth.decision is PolicyDecision.REQUIRE_HANDSHAKE


def test_tier_3_shell_refused_by_default(tmp_path):
    action = {"tool_call": {"name": "shell", "arguments": {"command": "ls /"}}}
    assert classify_action(action) is CapabilityTier.TIER_3_EXTERNAL
    auth = authorize_action(action, tmp_path)
    assert not auth.allowed
    assert any("tier 3" in r.reason.lower() for r in auth.refusals)


def test_tier_3_allowed_with_flag(tmp_path):
    action = {"tool_call": {"name": "shell", "arguments": {"command": "ls /"}}}
    auth = authorize_action(action, tmp_path, allow_tier_3=True)
    assert auth.allowed
    assert auth.decision is not PolicyDecision.REFUSE


def test_refuse_rm_rf_outside_vcs(tmp_path):
    action = {
        "tool_call": {"name": "shell", "arguments": {"command": "rm -rf /tmp/foo"}}
    }
    auth = authorize_action(action, tmp_path)
    assert not auth.allowed
    assert any("rm -rf" in r.reason for r in auth.refusals)


def test_refuse_publish_without_allow_tier_3(tmp_path):
    action = {"action": "publish package to PyPI"}
    auth = authorize_action(action, tmp_path)
    assert not auth.allowed
    assert any("publish" in r.reason for r in auth.refusals)


def test_refuse_sensitive_file_read(tmp_path):
    action = {"action": "read .env", "expected_artifact": ".env"}
    auth = authorize_action(action, tmp_path)
    assert not auth.allowed
    assert any("sensitive" in r.reason for r in auth.refusals)


def test_refuse_full_workspace_upload_over_threshold(tmp_path):
    action = {"action": "send workspace to provider"}
    auth = authorize_action(
        action, tmp_path, size_bytes=2 * 1024 * 1024, chunk_threshold_bytes=1024 * 1024
    )
    assert not auth.allowed
    assert any("chunk threshold" in r.reason for r in auth.refusals)


def test_refuse_overwrite_with_mismatched_session_key(tmp_path):
    action = {"action": "write src/foo.py", "expected_artifact": "src/foo.py"}
    file_key = Digest(b"a" * 32)
    session_key = Digest(b"b" * 32)
    auth = authorize_action(
        action, tmp_path, file_rootknot_key=file_key, current_session_key=session_key
    )
    assert not auth.allowed
    assert any("different session" in r.reason for r in auth.refusals)


def test_allow_overwrite_with_force_flag(tmp_path):
    action = {"action": "write src/foo.py", "expected_artifact": "src/foo.py"}
    file_key = Digest(b"a" * 32)
    session_key = Digest(b"b" * 32)
    auth = authorize_action(
        action,
        tmp_path,
        file_rootknot_key=file_key,
        current_session_key=session_key,
        force_overwrite_paths={"src/foo.py"},
    )
    assert auth.allowed


# RACT 0.2.0
