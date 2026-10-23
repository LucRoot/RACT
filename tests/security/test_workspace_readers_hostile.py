"""B-075: hostile files in the project for the readers that load them.

A cloned repository can ship files under ``.ract/`` and ``ract.yaml``. Each
reader here is called on a planted file. The contract: no exception escapes
except the reader's own documented refusal, nothing outside the project is
read, no text printed back carries a raw control or bidi character, and a
file cannot widen a policy.

A case that fails today is ``xfail(strict=True)`` with the finding in the
reason. The fixes are the BUILDER's; nothing under ``src/`` is changed here.
READERS.md lists the readers this file covers.
"""

from __future__ import annotations

import json
import os
import re
import shutil
from pathlib import Path
from typing import Any

import pytest

from ract import session_listing
from ract.core.assumptions_wal import AssumptionWal, WalCorruptError
from ract.handshake_registry import HandshakeRegistry
from ract.session_config import SessionConfig
from ract.security.manifest import (
    CapabilityManifest,
    FilesystemPolicy,
    NetworkPolicy,
    YoloWiden,
)
from ract.trust import trust_items
from ract.error_memory import ErrorMemory
from ract.memory_arena import MemoryArena, MemoryArenaError
from ract.ract_runner import _configured_budget
from ract.security.sandbox_env import AllowlistFileMalformed, load_allowlist_file
from ract.providers.reasoning import configured_default
from ract.refactor_ledger import RefactorLedger

READERS = (
    "refactor_ledger",
    "memory_arena",
    "reasoning.configured_default",
    "error_memory",
    "session_listing",
    "sandbox_env.allowlist",
    "ract_runner._configured_budget",
    "assumptions_wal",
    "handshake_registry",
    "session_config",
    "trust_items",
)

MIB = 1024 * 1024
CONTROL = "\x1b[31mred\x07\r"
BIDI = "\u202eevil\u2066"
RAW_CONTROL = re.compile(
    "[\x00-\x08\x0b\x0c\x0e-\x1f\x7f\u061c\u200e\u200f\u202a-\u202e\u2066-\u2069]"
)
OUTSIDE_SECRET = "OUTSIDE-SECRET-VALUE"

LEDGER_FILE = (".ract", "refactor_ledger.json")
ARENA_FILE = (".ract", "memory", "s1.json")
CONFIG_FILE = ("ract.yaml",)


def _plant(root: Path, parts: tuple[str, ...], data: bytes) -> Path:
    target = root.joinpath(*parts)
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_bytes(data)
    return target


def _plant_dir(root: Path, parts: tuple[str, ...]) -> Path:
    target = root.joinpath(*parts)
    target.mkdir(parents=True, exist_ok=True)
    return target


def _link_or_skip(link: Path, target: Path) -> None:
    link.parent.mkdir(parents=True, exist_ok=True)
    try:
        os.symlink(target, link)
    except (OSError, NotImplementedError) as exc:
        pytest.skip(f"symlinks need a privilege this account lacks: {exc}")


def _no_raw_control(text: str) -> None:
    assert not RAW_CONTROL.search(text), "raw control or bidi character printed"


def _json(obj: Any) -> bytes:
    return json.dumps(obj).encode("utf-8")


# ----------------------------------------------------------- refactor_ledger

LEDGER_CASES: dict[str, bytes] = {
    "oversize": b"x" * (10 * MIB + 1),
    "not_json": b"not json {",
    "wrong_type_list": b"[1, 2]",
    "wrong_type_number": b"42",
    "huge_number": b'{"lines_added": ' + b"1" * 5000 + b"}",
    "control_in_reason": _json({"override_reason": CONTROL}),
    "widening_key": _json({"allow_debt_override": True, "override_reason": "shipped"}),
}


@pytest.mark.parametrize("case", list(LEDGER_CASES))
def test_refactor_ledger_hostile_file(tmp_path: Path, case: str) -> None:
    _plant(tmp_path, LEDGER_FILE, LEDGER_CASES[case])
    try:
        ledger = RefactorLedger.load(tmp_path)
    except Exception as exc:  # the test reports what escaped
        pytest.fail(f"refactor_ledger escaped {type(exc).__name__}: {exc}")
    assert ledger.allow_debt_override is False
    _no_raw_control(ledger.override_reason or "")


def test_refactor_ledger_directory_where_file_is_expected(tmp_path: Path) -> None:
    _plant_dir(tmp_path, LEDGER_FILE)
    ledger = RefactorLedger.load(tmp_path)
    assert ledger.allow_debt_override is False


def test_refactor_ledger_symlink_out_of_project(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_bytes(_json({"override_reason": OUTSIDE_SECRET}))
    project = tmp_path / "project"
    _link_or_skip(project.joinpath(*LEDGER_FILE), outside)
    ledger = RefactorLedger.load(project)
    assert ledger.override_reason != OUTSIDE_SECRET


# ----------------------------------------------------------- memory_arena

ARENA_CASES: dict[str, bytes] = {
    "oversize": b"x" * (10 * MIB + 1),
    "not_json": b"not json {",
    "wrong_type_list_of_numbers": b"[1, 2]",
    "wrong_type_number": b"42",
    "wrong_type_object": b'{"a": 1}',
    "hostile_key": _json(
        [{"category": "note", "content": "x", "key": "../../escape/abs"}]
    ),
}


@pytest.mark.parametrize("case", list(ARENA_CASES))
def test_memory_arena_hostile_file(tmp_path: Path, case: str) -> None:
    _plant(tmp_path, ARENA_FILE, ARENA_CASES[case])
    try:
        arena = MemoryArena.for_session(tmp_path, "s1")
    except MemoryArenaError:
        return  # the documented refusal
    except Exception as exc:
        pytest.fail(f"memory_arena escaped {type(exc).__name__}: {exc}")
    _no_raw_control(arena.replay())


def test_memory_arena_directory_where_file_is_expected(tmp_path: Path) -> None:
    _plant_dir(tmp_path, ARENA_FILE)
    arena = MemoryArena.for_session(tmp_path, "s1")
    assert isinstance(arena.replay(), str)


def test_memory_arena_symlink_out_of_project(tmp_path: Path) -> None:
    outside = tmp_path / "outside.json"
    outside.write_bytes(_json([{"category": "note", "content": OUTSIDE_SECRET}]))
    project = tmp_path / "project"
    _link_or_skip(project.joinpath(*ARENA_FILE), outside)
    arena = MemoryArena.for_session(project, "s1")
    assert OUTSIDE_SECRET not in arena.replay()


# ----------------------------------------------------------- reasoning.configured_default

CONFIG_CASES: dict[str, bytes] = {
    "oversize": b"a: " + b"x" * (10 * MIB),
    "not_yaml": b"providers: [",
    "wrong_type_list": b"[1, 2]",
    "wrong_type_number": b"42",
    "control_in_value": b'providers:\n  p:\n    reasoning_effort: "\x1b[31mhigh"\n',
}


@pytest.mark.parametrize("case", list(CONFIG_CASES))
def test_reasoning_configured_default_hostile_file(tmp_path: Path, case: str) -> None:
    path = _plant(tmp_path, CONFIG_FILE, CONFIG_CASES[case])
    value = configured_default(path)
    assert value in {"off", "low", "medium", "high"}
    _no_raw_control(value)


def test_reasoning_configured_default_directory_where_file_is_expected(
    tmp_path: Path,
) -> None:
    _plant_dir(tmp_path, CONFIG_FILE)
    assert configured_default(tmp_path / CONFIG_FILE[0]) == "off"


# ----------------------------------------------------------- error_memory

ERROR_MEMORY_FILE = (".ract", "error_memory.jsonl")


def test_error_memory_non_json_line_is_dropped(tmp_path: Path) -> None:
    _plant(tmp_path, ERROR_MEMORY_FILE, b"not json\n")
    assert ErrorMemory(tmp_path).summarize() == ""


def test_error_memory_oversize_line_is_dropped(tmp_path: Path) -> None:
    _plant(tmp_path, ERROR_MEMORY_FILE, b"x" * (10 * MIB + 1))
    assert ErrorMemory(tmp_path).summarize() == ""


def test_error_memory_directory_where_file_is_expected(tmp_path: Path) -> None:
    _plant_dir(tmp_path, ERROR_MEMORY_FILE)
    assert ErrorMemory(tmp_path).summarize() == ""


def test_error_memory_number_line(tmp_path: Path) -> None:
    _plant(tmp_path, ERROR_MEMORY_FILE, b"42\n")
    ErrorMemory(tmp_path).summarize()


def test_error_memory_object_without_pattern(tmp_path: Path) -> None:
    _plant(tmp_path, ERROR_MEMORY_FILE, b'{"x": 1}\n')
    ErrorMemory(tmp_path).summarize()


def test_error_memory_control_in_pattern(tmp_path: Path) -> None:
    line = json.dumps({"pattern": CONTROL + BIDI}).encode("utf-8") + b"\n"
    _plant(tmp_path, ERROR_MEMORY_FILE, line)
    _no_raw_control(ErrorMemory(tmp_path).summarize())


# ----------------------------------------------------------- session_listing

SESSION_FILE = ("sessions", "s-1.json")


def test_session_listing_oversize_session_is_unreadable(tmp_path: Path) -> None:
    _plant(tmp_path, SESSION_FILE, b"x" * (10 * MIB + 1))
    rows, total = session_listing.list_rows(tmp_path / "sessions")
    assert total == 1 and rows[0].unreadable == "too large"


def test_session_listing_not_json_is_unreadable(tmp_path: Path) -> None:
    _plant(tmp_path, SESSION_FILE, b"not json {")
    rows, _ = session_listing.list_rows(tmp_path / "sessions")
    assert rows[0].unreadable == "unreadable"


@pytest.mark.parametrize("body", [b"[1, 2]", b"42", b'{"intent": 42}'])
def test_session_listing_wrong_type_is_unreadable(tmp_path: Path, body: bytes) -> None:
    _plant(tmp_path, SESSION_FILE, body)
    rows, _ = session_listing.list_rows(tmp_path / "sessions")
    assert rows[0].unreadable == "unreadable"


def test_session_listing_directory_where_file_is_expected(tmp_path: Path) -> None:
    _plant_dir(tmp_path, SESSION_FILE)
    rows, total = session_listing.list_rows(tmp_path / "sessions")
    assert rows == [] and total == 0


def test_session_listing_control_in_intent(tmp_path: Path) -> None:
    _plant(tmp_path, SESSION_FILE, json.dumps({"intent": CONTROL + BIDI}).encode())
    rows, _ = session_listing.list_rows(tmp_path / "sessions")
    _no_raw_control(rows[0].request)


# ----------------------------------------------------------- sandbox_env allowlist

ALLOWLIST_FILE = (".ract", "sandbox_env.allowlist")


def test_allowlist_oversize_line_is_refused(tmp_path: Path) -> None:
    path = _plant(tmp_path, ALLOWLIST_FILE, b"x" * (10 * MIB + 1))
    with pytest.raises(AllowlistFileMalformed):
        load_allowlist_file(path)


@pytest.mark.parametrize("body", [b"not json\n", b"42\n", b'["a"]\n'])
def test_allowlist_wrong_content_is_refused(tmp_path: Path, body: bytes) -> None:
    path = _plant(tmp_path, ALLOWLIST_FILE, body)
    with pytest.raises(AllowlistFileMalformed):
        load_allowlist_file(path)


def test_allowlist_directory_where_file_is_expected(tmp_path: Path) -> None:
    path = _plant_dir(tmp_path, ALLOWLIST_FILE)
    try:
        load_allowlist_file(path)
    except AllowlistFileMalformed:
        return
    except Exception as exc:
        pytest.fail(f"allowlist escaped {type(exc).__name__}")


# ----------------------------------------------------------- ract_runner token_budget config read


def test_budget_config_oversize_is_none(tmp_path: Path) -> None:
    path = _plant(tmp_path, CONFIG_FILE, b"a: " + b"x" * (10 * MIB))
    assert _configured_budget(path) is None


@pytest.mark.parametrize("body", [b"providers: [", b"[1, 2]", b"42"])
def test_budget_config_wrong_shape_is_none(tmp_path: Path, body: bytes) -> None:
    path = _plant(tmp_path, CONFIG_FILE, body)
    assert _configured_budget(path) is None


def test_budget_config_directory_where_file_is_expected(tmp_path: Path) -> None:
    _plant_dir(tmp_path, CONFIG_FILE)
    assert _configured_budget(tmp_path / CONFIG_FILE[0]) is None


# ----------------------------------------------------------- assumptions_wal

WAL_DIR = (".ract", "wal")


@pytest.mark.parametrize(
    "body",
    [
        pytest.param(b"not json\nnot json\n", id="two_bad_lines"),
        pytest.param(b"x" * (10 * MIB + 1), id="oversize"),
    ],
)
def test_assumptions_wal_garbage_is_refused_or_skipped(
    tmp_path: Path, body: bytes
) -> None:
    _plant(tmp_path, WAL_DIR + ("assumptions.wal",), body)
    wal = AssumptionWal(tmp_path.joinpath(*WAL_DIR))
    try:
        wal.load_all()
    except WalCorruptError:
        return
    except Exception as exc:
        pytest.fail(f"assumptions_wal escaped {type(exc).__name__}: {exc}")


@pytest.mark.xfail(
    strict=True,
    reason="B-075 FOUND: AssumptionWal.load_all lets PermissionError escape on a directory named assumptions.wal",
)
def test_assumptions_wal_directory_where_file_is_expected(tmp_path: Path) -> None:
    _plant_dir(tmp_path, WAL_DIR + ("assumptions.wal",))
    wal = AssumptionWal(tmp_path.joinpath(*WAL_DIR))
    try:
        wal.load_all()
    except WalCorruptError:
        return
    except Exception as exc:
        pytest.fail(f"assumptions_wal escaped {type(exc).__name__}: {exc}")


# ----------------------------------------------------------- handshake_registry

HANDSHAKE_FILE = (".ract", "handshakes.json")


@pytest.mark.parametrize("body", [b"not json", b"42", b'{"id": "h1"}'])
def test_handshake_non_list_root_is_empty(tmp_path: Path, body: bytes) -> None:
    _plant(tmp_path, HANDSHAKE_FILE, body)
    assert HandshakeRegistry(tmp_path).entries() == []


def test_handshake_oversize_file_is_empty(tmp_path: Path) -> None:
    _plant(tmp_path, HANDSHAKE_FILE, b"x" * (10 * MIB + 1))
    assert HandshakeRegistry(tmp_path).blocks_commit(["h1"]) == []


def test_handshake_directory_where_file_is_expected(tmp_path: Path) -> None:
    _plant_dir(tmp_path, HANDSHAKE_FILE)
    assert HandshakeRegistry(tmp_path).entries() == []


@pytest.mark.xfail(
    strict=True,
    reason="B-075 FOUND: HandshakeRegistry.entries raises TypeError on a non-object item or an unknown key",
)
@pytest.mark.parametrize("body", [b"[1, 2]", b'[{"id": "h1", "zzz": 1}]'])
def test_handshake_wrong_item_is_refused_or_ignored(
    tmp_path: Path, body: bytes
) -> None:
    _plant(tmp_path, HANDSHAKE_FILE, body)
    try:
        HandshakeRegistry(tmp_path).entries()
    except TypeError as exc:
        pytest.fail(f"handshake_registry escaped TypeError: {exc}")


def _widen_base() -> CapabilityManifest:
    return CapabilityManifest(
        run_id="widen-run",
        filesystem=FilesystemPolicy(write=("/workspace/*",)),
        network=NetworkPolicy(allow_hosts=("staging.example.com",), deny_default=True),
        yolo_widen=YoloWiden(
            extra_write=("/tmp/build/*",), extra_hosts=("cdn.example.com",)
        ),
    )


@pytest.mark.xfail(
    strict=True,
    reason="B-075 FOUND: a shipped handshakes.json with status approved widens the manifest (widen_manifest_for reads entries())",
)
def test_shipped_approved_handshake_does_not_widen(tmp_path: Path) -> None:
    source = tmp_path / "source"
    registry = HandshakeRegistry(source)
    registry.add("m1", "risky write", "operator approves")
    registry.update_status("m1", "approved")
    project = tmp_path / "project"
    (project / ".ract").mkdir(parents=True)
    shutil.copy(
        source / ".ract" / "handshakes.json", project / ".ract" / "handshakes.json"
    )
    base = _widen_base()
    assert HandshakeRegistry(project).widen_manifest_for(base, "m1") == base


# ----------------------------------------------------------- session_config

SESSION_JSON = ("session.json",)


@pytest.mark.xfail(
    strict=True,
    reason="B-075 FOUND: SessionConfig.from_file lets JSONDecodeError and TypeError escape on a wrong shape",
)
@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b"42"])
def test_session_config_wrong_shape_is_refused(tmp_path: Path, body: bytes) -> None:
    path = _plant(tmp_path, SESSION_JSON, body)
    try:
        SessionConfig.from_file(path)
    except (ValueError, TypeError, AttributeError) as exc:
        pytest.fail(f"session_config escaped {type(exc).__name__}: {exc}")
    except Exception:  # a documented refusal of the reader is not a failure
        return


def test_session_config_directory_where_file_is_expected(tmp_path: Path) -> None:
    path = _plant_dir(tmp_path, SESSION_JSON)
    try:
        SessionConfig.from_file(path)
    except OSError:
        return
    except Exception as exc:
        pytest.fail(f"session_config escaped {type(exc).__name__}: {exc}")


# ----------------------------------------------------------- trust_items

HOOK_FILE = (".ract", "hooks", "h.json")


@pytest.mark.parametrize("body", [b"not json", b"[1, 2]", b"42"])
def test_trust_items_bad_hook_is_listed_unreadable(tmp_path: Path, body: bytes) -> None:
    _plant(tmp_path, HOOK_FILE, body)
    items = trust_items(tmp_path)
    assert any(item.detail == "(unreadable hook file)" for item in items)


def test_trust_items_directory_where_hook_file_is_expected(tmp_path: Path) -> None:
    _plant_dir(tmp_path, HOOK_FILE)
    assert trust_items(tmp_path) is not None


def test_trust_items_control_in_hook_command_is_shown_escaped(tmp_path: Path) -> None:
    # The raw detail is kept for the digest (S-034); the printed line is escaped.
    body = json.dumps({"command": CONTROL + BIDI}).encode("utf-8")
    _plant(tmp_path, HOOK_FILE, body)
    for item in trust_items(tmp_path):
        _no_raw_control(item.line())


# ----------------------------------------------------------- consistency


def test_readers_md_lists_every_reader_this_file_covers() -> None:
    table = Path(__file__).with_name("READERS.md").read_text(encoding="utf-8")
    rows = [line for line in table.splitlines() if line.startswith("| `")]
    listed = {re.match(r"\| `([^`]+)`", row).group(1) for row in rows}
    assert listed == set(READERS)
    source = Path(__file__).read_text(encoding="utf-8")
    for reader in READERS:
        assert reader.split(".")[-1] in source
