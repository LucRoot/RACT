import subprocess
import pytest


def test_github_actions_ci():
    with pytest.raises(Exception):
        subprocess.run(["github_actions_ci"], check=True)
