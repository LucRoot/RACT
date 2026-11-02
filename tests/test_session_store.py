from __future__ import annotations


_SENTINEL = object()

import tempfile
from pathlib import Path
from typing import Dict

from ract.manager import Plan, Step
from ract.session_store import SessionStore, _SENTINEL


def test_save_and_load_roundtrip() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SessionStore(base_dir=tmp_dir)
        state: Dict[str, object] = {
            "intent": "test intent",
            "plan": Plan(
                assumption="initial assumption",
                confidence=0.95,
                steps=[
                    Step(action="noop", provider_hint="test", expected_artifact="none")
                ],
            ),
            "artifacts": {"key": "value"},
            "outcomes": ["success"],
        }
        session_id = "test_session"
        store.save(session_id, state)
        loaded = store.load(session_id)
        assert loaded == state


def test_list_sessions_returns_saved_ids() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SessionStore(base_dir=tmp_dir)
        store.save("session1", {"intent": "a"})
        store.save("session2", {"intent": "b"})
        sessions = store.list_sessions()
        assert "session1" in sessions
        assert "session2" in sessions
        assert len(sessions) == 2


def test_load_missing_session_raises_keyerror() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SessionStore(base_dir=tmp_dir)
        try:
            store.load("nonexistent")
            assert False, "Expected KeyError"
        except KeyError:
            pass


def test_session_store_includes_sentinel() -> None:
    from ract.session_store import _SENTINEL as knot

    assert knot is _SENTINEL


def test_exists_returns_true_for_saved_session() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SessionStore(base_dir=tmp_dir)
        store.save("existing", {"intent": "x"})
        assert store.exists("existing") is True


def test_exists_returns_false_for_missing_session() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SessionStore(base_dir=tmp_dir)
        assert store.exists("missing") is False


def test_load_corrupted_session_raises_session_corrupted_error() -> None:
    with tempfile.TemporaryDirectory() as tmp_dir:
        store = SessionStore(base_dir=tmp_dir)
        file_path = Path(tmp_dir) / "broken.json"
        file_path.write_text("not valid json", encoding="utf-8")
        try:
            store.load("broken")
            assert False, "Expected SessionCorruptedError"
        except Exception as exc:
            assert "corrupted" in str(exc).lower()


def test_default_base_dir_is_created(tmp_path: Path) -> None:
    import os

    original = os.getcwd()
    try:
        os.chdir(tmp_path)
        store = SessionStore()
        assert store.base_dir == Path(".ract") / "sessions"
        assert store.base_dir.exists()
    finally:
        os.chdir(original)


# RACT 0.1.1 - Trust and tooling


# ------------------------------------------------------- B-8s: strict JSON
# and atomic writes


def _strict_constant(name: str) -> None:
    raise ValueError(f"non-finite constant {name} reached a session file")


def test_save_with_non_finite_float_refuses(tmp_path: Path) -> None:
    store = SessionStore(base_dir=tmp_path)
    state: Dict[str, object] = {
        "intent": "x",
        "plan": Plan(
            assumption="a",
            confidence=float("nan"),
            steps=[Step(action="s", provider_hint="p", expected_artifact="")],
        ),
    }
    try:
        store.save("sess1", state)
        assert False, "Expected ValueError for a non-finite float"
    except ValueError as exc:
        assert "Out of range" in str(exc)
    assert not (tmp_path / "sess1.json").exists()


def test_save_of_event_cleaned_state_is_strict_json(tmp_path: Path) -> None:
    from ract.session_events import EventStream, plan_event_data

    stream = EventStream(session="s1")
    events: list = []
    stream.subscribe(events.append)
    plan = Plan(
        assumption="a",
        confidence=float("inf"),
        steps=[Step(action="s", provider_hint="p", expected_artifact="")],
    )
    stream.emit("plan.proposed", plan_event_data(plan), turn=1)
    store = SessionStore(base_dir=tmp_path)
    store.save("sess1", {"intent": "i", "events": [events[0].to_dict()]})
    import json

    parsed = json.loads(
        (tmp_path / "sess1.json").read_text(encoding="utf-8"),
        parse_constant=_strict_constant,
    )
    assert parsed["events"][0]["data"]["confidence"] is None


def test_save_replaces_a_planted_link(tmp_path: Path) -> None:
    from tests.test_b224_atomic_sites import _plant

    store = SessionStore(base_dir=tmp_path)
    target = tmp_path / "sess1.json"
    outside = tmp_path / "outside.txt"
    outside.write_text("sentinel\n", encoding="utf-8")
    _plant(target, outside)

    store.save("sess1", {"intent": "a"})

    assert outside.read_text(encoding="utf-8") == "sentinel\n"
    assert not target.is_symlink()
    assert store.load("sess1") == {"intent": "a"}


def test_save_failure_mid_write_keeps_previous_file(
    tmp_path: Path, monkeypatch
) -> None:
    store = SessionStore(base_dir=tmp_path)
    store.save("sess1", {"intent": "old"})

    def boom(path, data):
        raise OSError("simulated crash between write and rename")

    monkeypatch.setattr("ract.session_store.write_atomic", boom, raising=False)
    try:
        store.save("sess1", {"intent": "new"})
        assert False, "Expected the simulated crash to propagate"
    except OSError:
        pass
    assert store.load("sess1") == {"intent": "old"}
    assert list(tmp_path.glob("*.ract-tmp")) == []
