"""B-027 red team: ``run_build`` (the shared verifier attacks, _verifier_cases)."""

from __future__ import annotations

from pathlib import Path

import pytest

from tests.security.redteam._verifier_cases import ALL
from tests.security.redteam._world import build


@pytest.mark.parametrize("case", ALL, ids=lambda c: c.__name__)
def test_build_holds(tmp_path: Path, monkeypatch, case) -> None:
    case(build(tmp_path, monkeypatch), "build")
