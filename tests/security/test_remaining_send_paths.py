"""S-018b: the three remaining path-chosen reads that send file content to a
provider follow the S-018 rule (inventory rows 3, 6 and 13 in L-035).

Keyword retrieval sent 2,000 characters of every matching file, including
ract.yaml and anything under ``.GIT``; ``ract fence inspect --file .env``
sent the first 50 lines of the file; a skill name was joined into a path,
so ``../`` reached any .json file.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest

from ract.chestertons_fence import ChestertonsFence
from ract.retrieval_adapter import KeywordRetrievalAdapter
from ract.skills_registry import SkillRegistry
from ract.workspace_path import is_never_sent, resolve_workspace_path

SECRET = "zebra-5ecret-31f9"


def _plant(root: Path) -> None:
    (root / "src").mkdir()
    (root / "src" / "zebra.py").write_text(
        "ZEBRA = 'zebra stripes'\n", encoding="utf-8"
    )
    (root / "ract.yaml").write_text(f"api_key: zebra {SECRET}\n", encoding="utf-8")
    (root / "config").mkdir()
    (root / "config" / ".env.local.yaml").write_text(
        f"zebra: {SECRET}\n", encoding="utf-8"
    )
    (root / "vendor" / ".GIT").mkdir(parents=True)
    (root / "vendor" / ".GIT" / "notes.txt").write_text(
        f"zebra {SECRET}\n", encoding="utf-8"
    )
    (root / ".Ract").mkdir()
    (root / ".Ract" / "state.json").write_text(
        f'{{"zebra": "{SECRET}"}}\n', encoding="utf-8"
    )


def test_retrieval_never_returns_protected_files(tmp_path: Path) -> None:
    _plant(tmp_path)

    found = KeywordRetrievalAdapter(tmp_path).search("zebra", top_k=10)

    assert found.value is not None
    sources = {r.source.replace("\\", "/") for r in found.value}
    assert sources == {"src/zebra.py"}
    assert all(SECRET not in r.content for r in found.value)


@pytest.mark.parametrize(
    "target", [".env", "ract.yaml", ".git/config", "keys/deploy.key"]
)
def test_fence_refuses_without_reading_or_calling_the_provider(
    tmp_path: Path, target: str
) -> None:
    path = tmp_path / target
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(f"TOKEN={SECRET}\n", encoding="utf-8")
    provider = MagicMock()

    result = ChestertonsFence(tmp_path, provider).inspect(target)

    assert result.value == ""
    assert "never sent to a model" in (result.error or "")
    provider.complete.assert_not_called()
    assert not provider.method_calls


@pytest.mark.parametrize("name", ["../x", "a/b", "..", "", ".hidden", "a\\b", "x..y"])
def test_skill_names_must_be_one_file_name(tmp_path: Path, name: str) -> None:
    registry = SkillRegistry(tmp_path)
    with pytest.raises(ValueError, match="skill name"):
        registry.load(name)
    with pytest.raises(ValueError, match="skill name"):
        registry.register(name, "t")


def test_ordinary_skill_name_still_works(tmp_path: Path) -> None:
    registry = SkillRegistry(tmp_path)
    registry.register("write-tests_v2.1", "Write tests for $intent")
    assert registry.load("write-tests_v2.1")["template"] == "Write tests for $intent"


@pytest.mark.parametrize("path", ["ract.yaml", "sub/RACT.YML"])
def test_ract_config_is_never_sent_or_written(tmp_path: Path, path: str) -> None:
    assert is_never_sent(path)
    assert resolve_workspace_path(tmp_path, path, purpose="send").value is None
    written = resolve_workspace_path(tmp_path, path, purpose="write")
    assert written.provenance[-1] == "refused:ract_config"
