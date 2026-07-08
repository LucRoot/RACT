from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

from rootact.execution_context import ExecutionContext, _ROOT_KNOT


def test_set_and_get():
    ctx = ExecutionContext()
    ctx.set("key1", "value1")
    assert ctx.get("key1") == "value1"
    assert ctx.get("missing", None) is None


def test_clear_resets_state():
    ctx = ExecutionContext()
    ctx.set("a", "b")
    assert bool(ctx) is True
    ctx.clear()
    assert len(ctx) == 0
    assert not ctx


def test_write_and_read_json_file(tmp_path: Path):
    ctx = ExecutionContext()
    sample = {"foo": "bar", "num": "42"}
    ctx._store = sample
    file_path = tmp_path / "ctx.json"
    ctx.write_to_file(str(file_path))
    new_ctx = ExecutionContext()
    new_ctx.read_from_file(str(file_path))
    assert new_ctx.get("foo") == sample["foo"]
    assert new_ctx.get("num") == sample["num"]


def test_root_knot_is_defined_at_module_scope():
    import rootact.execution_context as mod

    assert hasattr(mod, "_ROOT_KNOT")
    assert mod._ROOT_KNOT is _ROOT_KNOT


# RACT 0.1.0 - Initial Public Release
