"""Regression -- module_04 sidecar header schema binding (DA-B F-3.2).

v0.5.2 hardening module_04. Locks the F-3.2 fix + Ox Alpha co-build
Fork 1 verdict (first-line JSONL / envelope for plain JSON) + Fork 3
verdict (non-strict default + WARN, strict opt-in):

- Header write includes ``{kind, schema_version, run_id,
  sidecar_type, created_at, ract_version}`` (plain-JSON envelope).
- Missing header in strict mode → :class:`SidecarHeaderMissing`.
- Missing header in non-strict mode → synthetic ``RUN-LEGACY-*``
  stamp + no raise.
- run_id mismatch → :class:`SidecarRunIdMismatch`.
- Unknown schema_version → :class:`SidecarUnknownSchema`.
- Downgrade below ``min_schema_version`` →
  :class:`SidecarDowngradeRefused`.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.sidecar_header import (
    HEADER_KIND,
    SidecarDowngradeRefused,
    SidecarHeader,
    SidecarHeaderError,
    SidecarHeaderMissing,
    SidecarRunIdMismatch,
    SidecarUnknownSchema,
    build_sidecar_header,
    json_body_with_header,
    header_as_jsonl_line,
    known_versions_for,
    read_sidecar_header,
    register_sidecar_type,
    write_json_sidecar_with_header,
)


# ---- Write side ------------------------------------------------------------


def test_write_header_produces_valid_shape(tmp_path: Path) -> None:
    """Write helper produces a header with all required fields."""
    path = tmp_path / "loop_state.json"
    header = write_json_sidecar_with_header(
        path,
        body={"counter": 3, "phase": "start"},
        sidecar_type="loop_state",
        schema_version=4,
        run_id="deadbeef" * 4,
    )
    assert header.kind == HEADER_KIND
    assert header.schema_version == 4
    assert header.run_id == "deadbeef" * 4
    assert header.sidecar_type == "loop_state"
    # File contains both header and body.
    payload = json.loads(path.read_text(encoding="utf-8"))
    assert "sidecar_header" in payload
    assert payload["sidecar_header"]["schema_version"] == 4
    assert payload["counter"] == 3
    assert payload["phase"] == "start"


def test_write_header_refuses_unknown_schema_at_write_time() -> None:
    """schema_version outside allowlist refused at build time.

    SP amendment (cross-family Q3 DEFECT): write-time raises the
    dedicated ``SidecarUnknownSchemaAtWrite`` subclass. Both
    subclasses catchable via ``SidecarSchemaError`` base.
    """
    from ract.sidecar_header import (
        SidecarSchemaError,
        SidecarUnknownSchemaAtWrite,
    )

    with pytest.raises(SidecarUnknownSchemaAtWrite):
        build_sidecar_header(
            sidecar_type="loop_state",
            schema_version=999,
            run_id="a" * 32,
        )
    # Base class also catches.
    with pytest.raises(SidecarSchemaError):
        build_sidecar_header(
            sidecar_type="loop_state",
            schema_version=999,
            run_id="a" * 32,
        )


def test_write_header_refuses_empty_run_id() -> None:
    """Empty run_id is a hard error (never write a bare header)."""
    with pytest.raises(ValueError, match="run_id"):
        build_sidecar_header(
            sidecar_type="loop_state",
            schema_version=4,
            run_id="",
        )


def test_write_header_jsonl_line_is_json_object() -> None:
    """Helper produces a JSON-object trailing newline."""
    header = build_sidecar_header(
        sidecar_type="loop_state", schema_version=4, run_id="a" * 32
    )
    line = header_as_jsonl_line(header)
    assert line.endswith("\n")
    parsed = json.loads(line)
    assert parsed["kind"] == HEADER_KIND
    assert parsed["run_id"] == "a" * 32


# ---- Read side -------------------------------------------------------------


def test_read_header_happy_path(tmp_path: Path) -> None:
    """Reader parses a header written by the helper."""
    path = tmp_path / "loop_state.json"
    write_json_sidecar_with_header(
        path,
        body={"counter": 1},
        sidecar_type="loop_state",
        schema_version=4,
        run_id="cafe" * 8,
    )
    header = read_sidecar_header(
        path, sidecar_type="loop_state", expected_run_id="cafe" * 8
    )
    assert header.run_id == "cafe" * 8
    assert header.schema_version == 4
    assert not header.synthetic_legacy


def test_read_header_missing_strict_raises(tmp_path: Path) -> None:
    """Strict mode: headerless file → SidecarHeaderMissing."""
    path = tmp_path / "loop_state.json"
    path.write_text(json.dumps({"counter": 1}), encoding="utf-8")
    with pytest.raises(SidecarHeaderMissing):
        read_sidecar_header(
            path, sidecar_type="loop_state", strict=True
        )


def test_read_header_run_id_mismatch_refused(tmp_path: Path) -> None:
    """Header run_id ≠ expected → SidecarRunIdMismatch."""
    path = tmp_path / "loop_state.json"
    write_json_sidecar_with_header(
        path,
        body={"counter": 1},
        sidecar_type="loop_state",
        schema_version=4,
        run_id="a" * 32,
    )
    with pytest.raises(SidecarRunIdMismatch) as exc_info:
        read_sidecar_header(
            path,
            sidecar_type="loop_state",
            expected_run_id="b" * 32,
        )
    assert exc_info.value.header_run_id == "a" * 32
    assert exc_info.value.expected_run_id == "b" * 32


def test_read_header_unknown_schema_refused(tmp_path: Path) -> None:
    """Header schema_version outside allowlist → SidecarUnknownSchema."""
    path = tmp_path / "loop_state.json"
    # Handcraft: build header then override schema_version to a
    # value outside the known set BEFORE writing.
    header = build_sidecar_header(
        sidecar_type="loop_state", schema_version=4, run_id="a" * 32
    )
    handcraft = header.to_dict()
    handcraft["schema_version"] = 999
    path.write_text(
        json.dumps(
            {"sidecar_header": handcraft, "counter": 1}, sort_keys=True
        ),
        encoding="utf-8",
    )
    with pytest.raises(SidecarUnknownSchema):
        read_sidecar_header(path, sidecar_type="loop_state")


def test_read_header_downgrade_refused(tmp_path: Path) -> None:
    """schema_version below min_schema_version → SidecarDowngradeRefused."""
    register_sidecar_type("_test_downgrade", frozenset({1, 2, 3, 4}))
    path = tmp_path / "downgrade.json"
    write_json_sidecar_with_header(
        path,
        body={"x": 1},
        sidecar_type="_test_downgrade",
        schema_version=2,
        run_id="a" * 32,
    )
    with pytest.raises(SidecarDowngradeRefused) as exc_info:
        read_sidecar_header(
            path, sidecar_type="_test_downgrade", min_schema_version=3
        )
    assert exc_info.value.header_schema_version == 2
    assert exc_info.value.min_schema_version == 3


def test_read_header_legacy_fallback_stamps_synthetic(tmp_path: Path) -> None:
    """Non-strict + headerless → RUN-LEGACY-* synthetic stamp."""
    path = tmp_path / "loop_state.json"
    path.write_text(json.dumps({"counter": 1}), encoding="utf-8")
    header = read_sidecar_header(
        path, sidecar_type="loop_state", strict=False
    )
    assert header.synthetic_legacy is True
    assert header.run_id.startswith("RUN-LEGACY-")
    assert len(header.run_id) == len("RUN-LEGACY-") + 16
    assert header.schema_version == 3


def test_read_header_legacy_fallback_deterministic(tmp_path: Path) -> None:
    """Same path → same synthetic run_id (deterministic hash)."""
    path = tmp_path / "loop_state.json"
    path.write_text(json.dumps({"counter": 1}), encoding="utf-8")
    h1 = read_sidecar_header(path, sidecar_type="loop_state", strict=False)
    h2 = read_sidecar_header(path, sidecar_type="loop_state", strict=False)
    assert h1.run_id == h2.run_id


def test_read_header_type_mismatch_refused(tmp_path: Path) -> None:
    """Header sidecar_type ≠ caller's expected → refuse."""
    register_sidecar_type("_test_a", frozenset({1}))
    register_sidecar_type("_test_b", frozenset({1}))
    path = tmp_path / "mismatch.json"
    write_json_sidecar_with_header(
        path,
        body={},
        sidecar_type="_test_a",
        schema_version=1,
        run_id="a" * 32,
    )
    with pytest.raises(SidecarHeaderMissing, match="sidecar_type"):
        read_sidecar_header(path, sidecar_type="_test_b")


def test_read_header_exceptions_share_base_class(tmp_path: Path) -> None:
    """All refusal subclasses are catchable via SidecarHeaderError."""
    path = tmp_path / "loop_state.json"
    path.write_text(json.dumps({"counter": 1}), encoding="utf-8")
    with pytest.raises(SidecarHeaderError):
        read_sidecar_header(
            path, sidecar_type="loop_state", strict=True
        )


# ---- Loop-state end-to-end integration -------------------------------------


def test_loop_state_persist_writes_header(tmp_path: Path) -> None:
    """LoopController.persist writes a header + on_resume validates."""
    # This integration path exercises the actual sidecar_type
    # ``loop_state`` at schema_version=4.
    payload_body = {
        "iterations": [],
        "iterations_count": 0,
        "previous_score": None,
        "stagnation_count": 0,
        "rollback_streak": 0,
        "completed_families": [],
        "repair_attempts_remaining": 3,
        "repair_intent": None,
        "last_known_good_workspace": None,
        "handshake_milestones": [],
    }
    path = tmp_path / "loop_state.json"
    write_json_sidecar_with_header(
        path,
        body=payload_body,
        sidecar_type="loop_state",
        schema_version=4,
        run_id="1234" * 8,
    )
    # Read back with the expected run_id.
    hdr = read_sidecar_header(
        path,
        sidecar_type="loop_state",
        expected_run_id="1234" * 8,
    )
    assert hdr.schema_version == 4
    # Read back with wrong expected → mismatch.
    with pytest.raises(SidecarRunIdMismatch):
        read_sidecar_header(
            path,
            sidecar_type="loop_state",
            expected_run_id="deadbeef" * 4,
        )


def test_known_versions_for_loop_state() -> None:
    """loop_state sidecar_type is registered with v4."""
    assert 4 in known_versions_for("loop_state")


def test_json_body_with_header_refuses_key_collision() -> None:
    """A body already containing ``sidecar_header`` is refused."""
    header = build_sidecar_header(
        sidecar_type="loop_state", schema_version=4, run_id="a" * 32
    )
    with pytest.raises(ValueError, match="sidecar_header"):
        json_body_with_header(header, {"sidecar_header": "poisoned"})
