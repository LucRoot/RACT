from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

from pathlib import Path

import pytest

from rootact.memory_arena import MemoryArena, _ROOT_KNOT


def test_store_and_retrieve():
    arena = MemoryArena()
    plan = type(
        "Plan",
        (),
        {
            "assumption": "test assumption",
            "confidence": 0.9,
            "steps": [
                type(
                    "Step",
                    (),
                    {
                        "action": "write_file",
                        "provider_hint": "local_io",
                        "expected_artifact": "out.txt",
                    },
                )()
            ],
        },
    )()
    key = arena.store(plan)
    assert isinstance(key, str)
    retrieved = arena.retrieve(key)
    assert len(retrieved) == 1
    record = retrieved[0]
    assert record["assumption"] == plan.assumption
    assert record["confidence"] == str(plan.confidence)
    assert record["step_count"] == str(len(plan.steps))


def test_store_with_explicit_key():
    arena = MemoryArena()
    plan = type(
        "Plan", (), {"assumption": "explicit key test", "confidence": 0.45, "steps": []}
    )()
    key = "my_custom_key"
    stored_key = arena.store(plan, key=key)
    assert stored_key == key
    retrieved = arena.retrieve(key)
    assert retrieved == [
        {
            "assumption": plan.assumption,
            "confidence": str(plan.confidence),
            "step_count": str(len(plan.steps)),
        }
    ]


def test_clear_resets_state():
    arena = MemoryArena()
    plan = type(
        "Plan",
        (),
        {
            "assumption": "to be cleared",
            "confidence": 1.0,
            "steps": [
                type(
                    "Step",
                    (),
                    {
                        "action": "noop",
                        "provider_hint": "none",
                        "expected_artifact": "",
                    },
                )()
            ],
        },
    )()
    arena.store(plan)
    assert bool(arena) is True
    arena.clear()
    assert len(arena) == 0
    assert not arena


def test_root_knot_is_module_singleton():
    import rootact.memory_arena as mod

    assert hasattr(mod, "_ROOT_KNOT")
    assert mod._ROOT_KNOT is _ROOT_KNOT


def test_record_and_replay():
    arena = MemoryArena()
    arena.record("constraint", "always use pathlib", importance=2)
    arena.record("outcome", "wrote src/foo.py", importance=1)
    replay = arena.replay()
    assert "Memory:" in replay
    assert "constraint" in replay
    assert "always use pathlib" in replay
    assert "outcome" in replay


def test_replay_ranks_importance_then_recency():
    arena = MemoryArena()
    arena.record("outcome", "older low-priority", importance=1)
    arena.record("constraint", "high-priority", importance=3)
    arena.record("outcome", "newer low-priority", importance=1)
    replay = arena.replay(max_entries=2)
    lines = replay.splitlines()
    # First entry after the header should be the high-priority constraint.
    assert lines[1].startswith("- [constraint]")
    assert "high-priority" in lines[1]


def test_replay_respects_token_budget():
    arena = MemoryArena()
    arena.record("constraint", "a very long memory that consumes tokens", importance=2)
    arena.record("outcome", "short", importance=1)
    replay = arena.replay(max_tokens=5)
    # Header alone is two tokens; no entry should fit beyond the header.
    assert replay == "" or replay == "Memory:\n"


def test_save_and_load(tmp_path):
    arena = MemoryArena()
    arena.record("constraint", "use dataclasses", importance=2)
    plan = type(
        "Plan",
        (),
        {"assumption": "saved plan", "confidence": 0.9, "steps": []},
    )()
    arena.store(plan, key="plan_key")
    path = tmp_path / "memory.json"
    arena.save(path)

    loaded = MemoryArena.load(path)
    replay = loaded.replay()
    assert "use dataclasses" in replay
    assert "saved plan" in replay
    assert "plan_key" in loaded._records


def test_for_session_loads_existing_file(tmp_path):
    arena = MemoryArena.for_session(tmp_path, "session_a")
    arena.record("fact", "loaded from session", importance=1)
    arena.save(tmp_path / ".rootact" / "memory" / "session_a.json")

    loaded = MemoryArena.for_session(tmp_path, "session_a")
    replay = loaded.replay()
    assert "loaded from session" in replay


def test_for_session_creates_empty_arena(tmp_path):
    arena = MemoryArena.for_session(tmp_path, "session_b")
    assert bool(arena) is False
    assert len(arena) == 0


def test_replay_recency_within_equal_importance():
    arena = MemoryArena()
    arena.record("outcome", "older", importance=1)
    arena.record("outcome", "newer", importance=1)
    replay = arena.replay(max_entries=2)
    lines = replay.splitlines()
    assert lines[1].startswith("- [outcome]")
    assert "newer" in lines[1]
    assert "older" in lines[2]


def test_load_raises_on_invalid_json(tmp_path):
    path = tmp_path / "bad.json"
    path.write_text("not json", encoding="utf-8")
    with pytest.raises(Exception):  # noqa: B017
        MemoryArena.load(path)


def test_save_raises_on_write_error(tmp_path, monkeypatch):
    arena = MemoryArena()
    arena.record("fact", "value")
    path = tmp_path / "memory.json"

    def _raise(*_args, **_kwargs):
        raise OSError("disk full")

    monkeypatch.setattr(Path, "write_text", _raise)
    with pytest.raises(Exception):  # noqa: B017
        arena.save(path)


# RACT 0.1.1 - Trust and tooling
