from __future__ import annotations


import pytest

from ract.skills_registry import SkillRegistry


def test_register_and_load(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    registry.register("greet", "Hello, $name!")
    loaded = registry.load("greet")
    assert loaded["name"] == "greet"
    assert loaded["template"] == "Hello, $name!"
    assert loaded["tools"] == []


def test_register_with_tools(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    registry.register("search", "Find $query", tools=["web_search", "summarize"])
    loaded = registry.load("search")
    assert loaded["tools"] == ["web_search", "summarize"]


def test_list_skills_sorted(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    registry.register("b", "b-template")
    registry.register("a", "a-template")
    assert registry.list_skills() == ["a", "b"]


def test_load_missing_raises_keyerror(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    with pytest.raises(KeyError):
        registry.load("missing")


def test_invoke_renders_template(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    registry.register("greet", "Hello, $name!")
    rendered = registry.invoke("greet", {"name": "World"})
    assert rendered == "Hello, World!"


def test_invoke_missing_skill_raises_keyerror(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    with pytest.raises(KeyError):
        registry.invoke("missing", {})


def test_register_empty_name_raises(tmp_path):
    registry = SkillRegistry(base_dir=tmp_path)
    with pytest.raises(ValueError):
        registry.register("", "template")


def test_copy_legacy_skills_copies_once_and_keeps_old(tmp_path):
    from ract.skills_registry import _COPIED_MARK, copy_legacy_skills

    old = tmp_path / "skills"
    old.mkdir()
    (old / "terse.json").write_text("{}", encoding="utf-8")
    (old / "notes.txt").write_text("not a skill", encoding="utf-8")

    copied = copy_legacy_skills(tmp_path)
    assert copied == ["terse"]
    new_dir = tmp_path / ".ract" / "skills"
    assert (new_dir / "terse.json").is_file()
    # The old folder is left as it was; non-json files are not copied.
    assert (old / "terse.json").is_file()
    assert not (new_dir / "notes.txt").exists()
    assert (new_dir / _COPIED_MARK).is_file()
    # The copy runs once.
    assert copy_legacy_skills(tmp_path) is None


def test_copy_legacy_skills_keeps_existing_target_and_skips_links(tmp_path):
    from ract.skills_registry import copy_legacy_skills

    assert copy_legacy_skills(tmp_path) is None  # no old folder at all

    old = tmp_path / "skills"
    old.mkdir()
    (old / "terse.json").write_text('{"name": "old"}', encoding="utf-8")
    new_dir = tmp_path / ".ract" / "skills"
    new_dir.mkdir(parents=True)
    (new_dir / "terse.json").write_text('{"name": "new"}', encoding="utf-8")

    copied = copy_legacy_skills(tmp_path)
    assert copied == []
    assert (new_dir / "terse.json").read_text(encoding="utf-8") == '{"name": "new"}'


def test_project_registry_targets_ract_skills_and_notices_legacy(tmp_path, capsys):
    from ract.skills_registry import project_registry

    registry = project_registry(tmp_path)
    assert registry.skills_dir == tmp_path / ".ract" / "skills"
    capsys.readouterr()  # nothing to migrate yet: no notice

    old = tmp_path / "skills"
    old.mkdir()
    (old / "terse.json").write_text("{}", encoding="utf-8")
    registry = project_registry(tmp_path)
    assert "terse" in registry.list_skills()
    notice = capsys.readouterr().err
    assert ".ract" in notice and "skills" in notice


def test_register_refuses_link_under_ract(tmp_path):
    # B-213: a .ract path component that is a link must not be written through.
    link = tmp_path / ".ract"
    real = tmp_path / "real"
    real.mkdir()
    try:
        link.symlink_to(real, target_is_directory=True)
    except OSError:
        pytest.skip("symlinks unavailable")
    from ract.workspace_state import StateDirRefused

    with pytest.raises(StateDirRefused):
        SkillRegistry(base_dir=link)


# RACT 0.1.1 - Trust and tooling
