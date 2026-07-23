__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

import subprocess
import pytest


def test_github_actions_ci():
    with pytest.raises(Exception):
        subprocess.run(["github_actions_ci"], check=True)
