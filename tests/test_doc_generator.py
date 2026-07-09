# Rooted by Dr. Lucas Root, Ph.D.
"""Tests for the documentation generator."""

from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from rootact.doc_generator import DocGenerator


SAMPLE_MODULE = '''\
"""A sample module for doc generation tests."""


def helper(x: int) -> int:
    """Return the input doubled."""
    return x * 2


class Container:
    """Holds a value."""

    def get(self) -> int:
        """Return the held value."""
        return 0
'''


def test_generator_writes_module_doc_and_index(tmp_path):
    (tmp_path / "sample.py").write_text(SAMPLE_MODULE, encoding="utf-8")
    output_dir = tmp_path / "docs" / "api"
    generator = DocGenerator(tmp_path, output_dir=output_dir)
    written = generator.generate()

    module_doc = output_dir / "sample.md"
    index_doc = output_dir / "index.md"
    assert module_doc in written
    assert index_doc in written

    module_text = module_doc.read_text(encoding="utf-8")
    assert "# `sample`" in module_text
    assert "A sample module for doc generation tests." in module_text
    assert "helper" in module_text
    assert "Container" in module_text
    assert "get" in module_text
    assert "Return the input doubled." in module_text
    assert "Holds a value." in module_text
    assert "Return the held value." in module_text

    index_text = index_doc.read_text(encoding="utf-8")
    assert "API Documentation Index" in index_text
    assert "sample.md" in index_text


def test_generator_skips_files_with_no_docstrings(tmp_path):
    (tmp_path / "empty.py").write_text("x = 1\n", encoding="utf-8")
    generator = DocGenerator(tmp_path)
    written = generator.generate()
    assert len(written) == 1
    assert written[0].name == "index.md"


def test_generator_handles_syntax_errors_gracefully(tmp_path):
    (tmp_path / "broken.py").write_text("def bad(\n", encoding="utf-8")
    generator = DocGenerator(tmp_path)
    written = generator.generate()
    assert len(written) == 1
    assert written[0].name == "index.md"


def test_generator_respects_custom_output_dir(tmp_path):
    (tmp_path / "mod.py").write_text(
        '"""Mod."""\ndef f():\n    """F."""\n    pass\n',
        encoding="utf-8",
    )
    custom = tmp_path / "custom_docs"
    generator = DocGenerator(tmp_path, output_dir=custom)
    generator.generate()
    assert (custom / "mod.md").is_file()
    assert (custom / "index.md").is_file()


# RACT 0.1.1 - Trust and tooling
