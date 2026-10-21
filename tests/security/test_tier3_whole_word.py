"""Tier-3 classification matches whole words, not substrings of ordinary English."""

from __future__ import annotations

import pytest

from ract.core.threat_model import CapabilityTier, authorize_action, classify_action


def _tier(text: str, artifact: str = "src/mod.py") -> CapabilityTier:
    return classify_action({"action": text, "expected_artifact": artifact})


@pytest.mark.parametrize(
    "text",
    [
        "execute the tests",
        "make the script executable",
        "add a docstring to hello.py",
        "refactor the crosshatch renderer",
        "explain how classes work",
        "describe the publisher interface",
        "document the curly-brace style",
    ],
)
def test_ordinary_english_is_not_tier_3(text):
    assert _tier(text) is not CapabilityTier.TIER_3_EXTERNAL


@pytest.mark.parametrize(
    "text",
    [
        "run the shell command: ls",
        "call exec(code) on the input",
        "curl the endpoint",
        "wget the archive",
        "ssh into the host",
        "scp the build to the server",
        "publish to PyPI",
        "publishing the package",
        "rm -rf build",
        "use subprocess.run to call git",
        "call os.system('ls')",
    ],
)
def test_real_tier_3_actions_still_match(text):
    assert _tier(text) is CapabilityTier.TIER_3_EXTERNAL


@pytest.mark.parametrize("artifact", ["src/ssh.py", "tools/shell.py", "exec.py"])
def test_target_file_name_does_not_make_an_edit_tier_3(artifact):
    assert _tier("edit the module", artifact) is not CapabilityTier.TIER_3_EXTERNAL


def test_structured_shell_tool_call_is_still_tier_3():
    action = {"tool_call": {"name": "shell", "arguments": {"command": "ls"}}}
    assert classify_action(action) is CapabilityTier.TIER_3_EXTERNAL


def test_execute_tests_step_is_authorized(tmp_path):
    """Regression: 'execute tests' used to be refused as tier 3 ("exec" substring)."""
    action = {"action": "execute the unit tests", "expected_artifact": "results.txt"}
    assert authorize_action(action, tmp_path).allowed


def test_publish_inflections_are_refused(tmp_path):
    action = {"action": "publishing the wheel to the registry"}
    assert not authorize_action(action, tmp_path).allowed
