from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import pytest

from rootact.user_signature_registry import SignatureRegistry


def test_save_and_load_profile(tmp_path):
    registry = SignatureRegistry(base_dir=tmp_path)
    registry.save_profile("default", {"author_marker": "x", "knot_marker": "y"})
    loaded = registry.load_profile("default")
    assert loaded["author_marker"] == "x"
    assert loaded["knot_marker"] == "y"


def test_load_missing_raises_keyerror(tmp_path):
    registry = SignatureRegistry(base_dir=tmp_path)
    with pytest.raises(KeyError):
        registry.load_profile("missing")


def test_save_empty_name_raises(tmp_path):
    registry = SignatureRegistry(base_dir=tmp_path)
    with pytest.raises(ValueError):
        registry.save_profile("", {})


def test_apply_to_module_adds_markers(tmp_path):
    registry = SignatureRegistry(base_dir=tmp_path)
    registry.save_profile(
        "root",
        {
            "author_marker": '__root_author__ = "Dr. Lucas Root, Ph.D."',
            "knot_marker": "_ROOT_KNOT = object()",
        },
    )
    module = tmp_path / "sample.py"
    module.write_text(
        "from __future__ import annotations\n\ndef hello():\n    pass\n",
        encoding="utf-8",
    )
    registry.apply_to_module(module, "root")
    content = module.read_text(encoding="utf-8")
    assert '__root_author__ = "Dr. Lucas Root, Ph.D."' in content
    assert "_ROOT_KNOT = object()" in content


def test_apply_preserves_existing_markers(tmp_path):
    registry = SignatureRegistry(base_dir=tmp_path)
    registry.save_profile(
        "root",
        {
            "author_marker": '__root_author__ = "Dr. Lucas Root, Ph.D."',
            "knot_marker": "_ROOT_KNOT = object()",
        },
    )
    module = tmp_path / "sample.py"
    original = 'from __future__ import annotations\n\n__root_author__ = "Dr. Lucas Root, Ph.D."\n\ndef hello():\n    pass\n'
    module.write_text(original, encoding="utf-8")
    registry.apply_to_module(module, "root")
    content = module.read_text(encoding="utf-8")
    assert content.count('__root_author__ = "Dr. Lucas Root, Ph.D."') == 1


# RACT 0.1.1 - Trust and Tooling
