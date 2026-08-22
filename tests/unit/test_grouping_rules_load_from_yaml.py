"""v0.5.1 spec-completeness module_04 -- YAML config loader.

:func:`ract.memory.grouping.load_grouping_rules` reads
``<workspace_root>/.ract/grouping_rules.yaml`` and returns a
:class:`GroupingRules` with the file's values folded over the
shipped defaults. Missing file → defaults.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ract.memory.grouping import GroupingRules, load_grouping_rules


def test_missing_config_returns_defaults(tmp_path: Path):
    rules = load_grouping_rules(tmp_path)
    defaults = GroupingRules()
    assert rules == defaults


def test_full_config_overrides_every_field(tmp_path: Path):
    ract_dir = tmp_path / ".ract"
    ract_dir.mkdir()
    (ract_dir / "grouping_rules.yaml").write_text(
        """
grouping:
  dataclass_methods: false
  trait_impls: false
  test_subject: false
  function_type_aliases: false
  languages: [python]
""",
        encoding="utf-8",
    )
    rules = load_grouping_rules(tmp_path)
    assert rules.dataclass_methods is False
    assert rules.trait_impls is False
    assert rules.test_subject is False
    assert rules.function_type_aliases is False
    assert rules.languages == frozenset({"python"})


def test_partial_config_folds_over_defaults(tmp_path: Path):
    ract_dir = tmp_path / ".ract"
    ract_dir.mkdir()
    (ract_dir / "grouping_rules.yaml").write_text(
        """
grouping:
  trait_impls: false
""",
        encoding="utf-8",
    )
    rules = load_grouping_rules(tmp_path)
    defaults = GroupingRules()
    assert rules.trait_impls is False
    # Untouched fields keep defaults.
    assert rules.dataclass_methods == defaults.dataclass_methods
    assert rules.test_subject == defaults.test_subject
    assert rules.function_type_aliases == defaults.function_type_aliases
    assert rules.languages == defaults.languages


def test_top_level_not_mapping_raises(tmp_path: Path):
    ract_dir = tmp_path / ".ract"
    ract_dir.mkdir()
    (ract_dir / "grouping_rules.yaml").write_text(
        "- not a mapping\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="top-level shape"):
        load_grouping_rules(tmp_path)


def test_grouping_key_not_mapping_raises(tmp_path: Path):
    ract_dir = tmp_path / ".ract"
    ract_dir.mkdir()
    (ract_dir / "grouping_rules.yaml").write_text(
        "grouping: 42\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="'grouping' key"):
        load_grouping_rules(tmp_path)


def test_languages_not_sequence_raises(tmp_path: Path):
    ract_dir = tmp_path / ".ract"
    ract_dir.mkdir()
    (ract_dir / "grouping_rules.yaml").write_text(
        "grouping:\n  languages: python\n",
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="'languages' must be a sequence"):
        load_grouping_rules(tmp_path)


def test_shipped_example_config_parseable(tmp_path: Path):
    """The ``docs/grouping_rules.example.yaml`` shipped alongside
    the module is parseable via
    :func:`ract.memory.grouping.load_grouping_rules` when copied to
    the workspace runtime path ``<workspace_root>/.ract/grouping_rules.yaml``
    (``.ract/`` is gitignored so the runtime file itself is not
    shipped in the repo; the example is)."""
    repo_root = Path(__file__).resolve().parents[2]
    example_path = repo_root / "docs" / "grouping_rules.example.yaml"
    if not example_path.exists():
        pytest.skip("example config not present in this checkout")
    # Stage the example under a fresh workspace root's .ract/ dir.
    ract_dir = tmp_path / ".ract"
    ract_dir.mkdir()
    (ract_dir / "grouping_rules.yaml").write_text(
        example_path.read_text(encoding="utf-8"),
        encoding="utf-8",
    )
    rules = load_grouping_rules(tmp_path)
    assert rules.dataclass_methods is True
    assert rules.trait_impls is True
    assert rules.test_subject is True
    assert rules.function_type_aliases is True
    assert "python" in rules.languages
    assert "rust" in rules.languages
