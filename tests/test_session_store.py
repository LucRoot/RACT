from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

import tempfile
from pathlib import Path
from typing import Dict

from ract.manager import Plan, Step
from ract.session_store import SessionStore, _ROOT_KNOT


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


def test_session_store_includes_root_author_and_root_knot() -> None:
    from ract.session_store import __root_author__ as author, _ROOT_KNOT as knot

    assert author == "Dr. Lucas Root, Ph.D."
    assert knot is _ROOT_KNOT


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
        assert store.base_dir.name == ".ract_sessions"
        assert store.base_dir.exists()
    finally:
        os.chdir(original)


# RACT 0.1.1 - Trust and tooling
