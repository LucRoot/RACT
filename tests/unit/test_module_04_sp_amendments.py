"""Regression -- module_04 SP amendment fixes.

v0.5.2 hardening module_04 SP amendment. Locks the SP DEFECT
verdicts from Ox Alpha (dispatches A + B) and cross-family
reviewer (dispatch A):

- **cross-family Q2 + Ox Alpha A Q2 (DEFECT):** legacy-fallback
  branch used to early-return, silently skipping the
  ``expected_run_id`` check AND the ``min_schema_version`` floor.
  Post-amendment: (i) if ``expected_run_id`` is passed, refuse;
  (ii) if ambient is bound + differs from synthetic, refuse;
  (iii) if ``min_schema_version`` > legacy floor, refuse. Only
  the pure-observability read (both None) accepts the legacy
  stamp silently.
- **cross-family Q3 (DEFECT):** ``SidecarUnknownSchema`` was
  raised at both write-time (synthetic path) and read-time.
  Post-amendment: ``SidecarUnknownSchemaAtWrite`` (no path) vs
  ``SidecarUnknownSchemaAtRead`` (real path). Both subclass
  ``SidecarSchemaError``. Backward-compat alias
  ``SidecarUnknownSchema = SidecarUnknownSchemaAtRead`` retained.
- **cross-family Q5 (DEFECT):** ``read_sidecar_header`` with
  ``sidecar_type=None`` + ``strict=False`` used to stamp a
  "unknown" sidecar_type into the returned header, which could
  route into a mis-parser downstream. Post-amendment: refuse
  the None + non-strict combination with a clear ``ValueError``.
- **cross-family Q6 (DEFECT):** registry mutability broke test
  isolation. Post-amendment: ``snapshot_registry`` +
  ``restore_registry`` helpers let test fixtures keep
  registrations hermetic.
- **Ox Alpha A Q4 (DEFECT sub-finding):** shape-misdeclaration
  hazard -- caller passing ``is_jsonl=True`` on an envelope
  file (or vice versa) would silently downgrade to legacy
  fallback in non-strict mode, skipping binding checks.
  Post-amendment: detect the envelope-parsed-as-JSONL case
  (parsed first-line dict has nested ``sidecar_header`` +
  no top-level ``kind``) and refuse with clear message.
- **Ox Alpha B Q3 supplemental S1 (DEFECT):** ``env=None`` path
  in ``_inject_ract_run_id_env`` used to skip the RACT_* strip,
  so a subprocess spawned with ``env=None`` inherited any
  attacker-set ``RACT_*`` keys from parent ``os.environ``.
  Post-amendment: even for ``env=None`` we strip RACT_* from
  a copy of ``os.environ`` before falling through.
- **Ox Alpha B Q6 (DEFECT minor):** the
  ``runtime.run_id.env_stripped_from_parent`` event carried a
  cosmetic ``stripped_value_hash`` field that only hashed
  ``"{key}="`` (not the raw value). Post-amendment: field
  dropped; payload carries only ``stripped_key``.
- **Ox Alpha B Q7 (DEFECT):** ``write_json_sidecar_with_header``
  now writes via tmp+rename atomicity, and
  ``loop_controller._persist_iteration_state`` delegates to it
  instead of hand-rolling the same logic.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.sidecar_header import (
    SidecarDowngradeRefused,
    SidecarHeaderError,
    SidecarHeaderMissing,
    SidecarRunIdMismatch,
    SidecarSchemaError,
    SidecarUnknownSchema,
    SidecarUnknownSchemaAtRead,
    SidecarUnknownSchemaAtWrite,
    build_sidecar_header,
    read_sidecar_header,
    register_sidecar_type,
    restore_registry,
    snapshot_registry,
    write_json_sidecar_with_header,
)


# ---- cross-family Q3: split exception subclasses --------------------------


def test_write_time_unknown_schema_raises_at_write_subclass() -> None:
    """build_sidecar_header with bad schema_version raises the
    WRITE-time subclass, not the READ-time one."""
    with pytest.raises(SidecarUnknownSchemaAtWrite) as exc_info:
        build_sidecar_header(
            sidecar_type="loop_state",
            schema_version=999,
            run_id="a" * 32,
        )
    # No .path attribute exposed at write time.
    assert not hasattr(exc_info.value, "path")
    assert exc_info.value.sidecar_type == "loop_state"


def test_backward_compat_alias_resolves_to_read_time() -> None:
    """SidecarUnknownSchema alias resolves to the READ-time subclass."""
    assert SidecarUnknownSchema is SidecarUnknownSchemaAtRead


def test_both_subclasses_share_schema_error_base() -> None:
    """Both write + read subclasses catchable via SidecarSchemaError."""
    assert issubclass(SidecarUnknownSchemaAtWrite, SidecarSchemaError)
    assert issubclass(SidecarUnknownSchemaAtRead, SidecarSchemaError)
    assert issubclass(SidecarSchemaError, SidecarHeaderError)


# ---- cross-family Q2 + Ox A Q2: legacy fallback binding refusal -----------


def test_legacy_fallback_with_expected_run_id_refuses(tmp_path: Path) -> None:
    """Ox Alpha A Q2 DEFECT: legacy branch used to skip
    expected_run_id check. Now refuses."""
    path = tmp_path / "loop_state.json"
    path.write_text(json.dumps({"counter": 1}), encoding="utf-8")
    with pytest.raises(SidecarRunIdMismatch):
        read_sidecar_header(
            path,
            sidecar_type="loop_state",
            expected_run_id="a" * 32,
            strict=False,
        )


def test_legacy_fallback_with_min_schema_floor_refuses(tmp_path: Path) -> None:
    """Ox Alpha A Q2 incidental: legacy branch used to skip
    min_schema_version. Now refuses when floor > legacy=3."""
    register_sidecar_type("_test_legacy_min", frozenset({4}))
    path = tmp_path / "min.json"
    path.write_text(json.dumps({"x": 1}), encoding="utf-8")
    with pytest.raises(SidecarDowngradeRefused):
        read_sidecar_header(
            path,
            sidecar_type="_test_legacy_min",
            min_schema_version=4,
            strict=False,
        )


def test_legacy_fallback_pure_observability_read_accepts(tmp_path: Path) -> None:
    """Pure observability read (no expected_run_id, no ambient,
    no min_schema) accepts legacy stamp silently."""
    path = tmp_path / "obs.json"
    path.write_text(json.dumps({"x": 1}), encoding="utf-8")
    # Ensure no ambient.
    from ract.runtime import set_current_run_id

    set_current_run_id(None)
    header = read_sidecar_header(path, sidecar_type="loop_state", strict=False)
    assert header.synthetic_legacy is True


# ---- cross-family Q5: require sidecar_type when strict=False --------------


def test_read_none_sidecar_type_non_strict_refused(tmp_path: Path) -> None:
    """sidecar_type=None + strict=False on headerless file raises
    ValueError (Q5 DEFECT: was silently stamping 'unknown')."""
    path = tmp_path / "no_type.json"
    path.write_text(json.dumps({"x": 1}), encoding="utf-8")
    with pytest.raises(ValueError, match="sidecar_type"):
        read_sidecar_header(path, sidecar_type=None, strict=False)


# ---- cross-family Q6: registry mutability isolation -----------------------


def test_registry_snapshot_restore_roundtrip() -> None:
    """snapshot_registry + restore_registry preserve registrations."""
    snap = snapshot_registry()
    register_sidecar_type("_test_snapshot_A", frozenset({1}))
    assert "_test_snapshot_A" in snapshot_registry()
    restore_registry(snap)
    assert "_test_snapshot_A" not in snapshot_registry()


# ---- Ox A Q4: shape-misdeclaration guard ---------------------------------


def test_envelope_read_with_is_jsonl_true_refuses(tmp_path: Path) -> None:
    """Envelope file (single JSON object) read with is_jsonl=True
    raises SidecarHeaderMissing with clear diagnostic (Ox A Q4)."""
    path = tmp_path / "envelope.json"
    write_json_sidecar_with_header(
        path,
        body={"counter": 1},
        sidecar_type="loop_state",
        schema_version=4,
        run_id="a" * 32,
    )
    with pytest.raises(SidecarHeaderMissing, match="envelope layout"):
        read_sidecar_header(path, sidecar_type="loop_state", is_jsonl=True)


# ---- Ox B Q3 supplemental S1: env=None strips inherited RACT_* ------------


def test_inject_env_none_strips_inherited_ract_keys(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """env=None + ambient bound: strip RACT_* from os.environ, then
    reinject ambient. Previously env=None fell through to
    Popen(env=None) which inherited attacker RACT_* keys wholesale."""
    from ract.executor.loop import _inject_ract_run_id_env
    from ract.runtime import (
        RACT_RUN_ID_ENV_KEY,
        bind_run_id,
        set_current_run_id,
    )

    monkeypatch.setenv(RACT_RUN_ID_ENV_KEY, "victim_run")
    monkeypatch.setenv("RACT_UNKNOWN_FUTURE_KEY", "poison")
    rid = "b" * 32
    with bind_run_id(rid):
        out = _inject_ract_run_id_env(None, rid)
    set_current_run_id(None)
    assert out is not None
    # RACT_* keys stripped, ambient re-injected under RACT control.
    assert out[RACT_RUN_ID_ENV_KEY] == rid
    assert "RACT_UNKNOWN_FUTURE_KEY" not in out


# ---- Ox B Q6: cosmetic hash dropped --------------------------------------


def test_env_stripped_event_payload_only_carries_key_name() -> None:
    """runtime.run_id.env_stripped_from_parent event no longer
    carries stripped_value_hash (Ox B Q6 DEFECT: cosmetic field)."""
    from ract.executor.loop import _emit_env_stripped_from_parent

    captured: list[tuple[str, dict[str, object]]] = []

    class _StubSink:
        @staticmethod
        def emit(kind: str, payload: dict[str, object]) -> None:
            captured.append((kind, payload))

    import ract.trace.sink as sink_mod

    original_emit = sink_mod.emit
    sink_mod.emit = _StubSink.emit  # type: ignore[assignment]
    try:
        _emit_env_stripped_from_parent(["RACT_RUN_ID", "RACT_FUTURE"])
    finally:
        sink_mod.emit = original_emit  # type: ignore[assignment]
    # Every captured payload has stripped_key + NO stripped_value_hash.
    assert len(captured) == 2
    for kind, payload in captured:
        assert kind == "runtime.run_id.env_stripped_from_parent"
        assert "stripped_key" in payload
        assert "stripped_value_hash" not in payload


# ---- Ox B Q7: tmp+rename atomicity in write helper -----------------------


def test_write_helper_leaves_no_tmp_litter_on_success(tmp_path: Path) -> None:
    """write_json_sidecar_with_header cleans up its .tmp file on
    success (tmp+rename atomicity fold from Ox B Q7)."""
    path = tmp_path / "atomic.json"
    write_json_sidecar_with_header(
        path,
        body={"x": 1},
        sidecar_type="loop_state",
        schema_version=4,
        run_id="a" * 32,
    )
    # Only the final file exists; no .tmp litter.
    assert path.exists()
    assert not (tmp_path / (path.name + ".tmp")).exists()


def test_write_helper_cleans_tmp_on_serialization_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """When os.replace fails, the .tmp file is cleaned up."""
    path = tmp_path / "fail.json"

    def _boom(*args: object, **kwargs: object) -> None:
        raise OSError("simulated failure")

    monkeypatch.setattr("os.replace", _boom)
    with pytest.raises(OSError):
        write_json_sidecar_with_header(
            path,
            body={"x": 1},
            sidecar_type="loop_state",
            schema_version=4,
            run_id="a" * 32,
        )
    # .tmp file cleaned up.
    assert not (tmp_path / (path.name + ".tmp")).exists()
