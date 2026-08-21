"""Tests for :mod:`ract.memory.repo_fingerprint`."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.memory.graph_index import EdgeRow, GraphIndex
from ract.memory.repo_fingerprint import (
    FINGERPRINT_RECORD_PATH,
    FINGERPRINT_SCHEMA_VERSION,
    NO_SIGNAL_SENTINEL,
    RepoFingerprint,
    RetrievalDefaults,
    compute,
    read,
    retrieval_defaults_from_fingerprint,
    write,
)
from ract.memory.symbol_index import SymbolIndex, SymbolRow


def _seat_symbol(
    idx: SymbolIndex,
    *,
    name: str,
    kind: str,
    file_path: str,
    token_count: int | None,
) -> int:
    return idx.insert_or_update(
        SymbolRow(
            id=None,
            name=name,
            kind=kind,
            file_path=file_path,
            start_line=1,
            end_line=2,
            signature=None,
            docstring=None,
            visibility=None,
            parent_symbol_id=None,
            language="python",
            content_hash=f"h_{name}",
            token_count=token_count,
            updated_at=None,
        )
    )


def test_compute_fresh_repo_returns_sentinels(tmp_path: Path) -> None:
    fp = compute(tmp_path, now=1234)
    assert fp.avg_function_tokens == 0.0
    assert fp.avg_import_depth == 0.0
    assert fp.lsp_response_time_p50_ms == NO_SIGNAL_SENTINEL
    assert fp.lsp_response_time_p95_ms == NO_SIGNAL_SENTINEL
    assert fp.test_suite_runtime_seconds == NO_SIGNAL_SENTINEL
    assert fp.commit_frequency_per_week == 0.0
    assert fp.recorded_at == 1234


def test_compute_avg_function_tokens_over_functions_and_methods(tmp_path: Path) -> None:
    with SymbolIndex(":memory:") as symbols:
        _seat_symbol(
            symbols, name="f1", kind="function", file_path="a.py", token_count=100
        )
        _seat_symbol(
            symbols, name="f2", kind="function", file_path="a.py", token_count=300
        )
        _seat_symbol(
            symbols, name="m1", kind="method", file_path="b.py", token_count=200
        )
        # Non-function kind is excluded from the mean.
        _seat_symbol(
            symbols, name="C1", kind="class", file_path="b.py", token_count=1000
        )
        fp = compute(tmp_path, symbols=symbols, now=1)
        assert fp.avg_function_tokens == pytest.approx((100 + 300 + 200) / 3.0)


def test_compute_avg_import_depth_counts_imports_per_file(tmp_path: Path) -> None:
    with GraphIndex(":memory:") as graph:
        for i, target in enumerate((10, 20, 30)):
            graph.insert_edge(
                EdgeRow(
                    id=None,
                    source_symbol_id=1,
                    target_symbol_id=target,
                    edge_type="imports",
                    location_file="a.py",
                    location_line=i + 1,
                    strength=1,
                    neighborhood_source="lsp",
                )
            )
        graph.insert_edge(
            EdgeRow(
                id=None,
                source_symbol_id=1,
                target_symbol_id=99,
                edge_type="imports",
                location_file="b.py",
                location_line=1,
                strength=1,
                neighborhood_source="lsp",
            )
        )
        # Non-imports edge is excluded.
        graph.insert_edge(
            EdgeRow(
                id=None,
                source_symbol_id=1,
                target_symbol_id=2,
                edge_type="calls",
                location_file="a.py",
                location_line=5,
                strength=1,
                neighborhood_source="lsp",
            )
        )
        fp = compute(tmp_path, graph=graph, now=1)
        # 3 imports on a.py + 1 on b.py = 4 imports across 2 files → 2.0.
        assert fp.avg_import_depth == pytest.approx(2.0)


def test_compute_lsp_percentiles_present() -> None:
    samples = [10, 20, 30, 40, 50, 60, 70, 80, 90, 100]
    fp = compute(
        Path("."),
        lsp_response_times_ms=samples,
        commit_timestamps=[],
        now=1,
    )
    assert fp.lsp_response_time_p50_ms > 0
    assert fp.lsp_response_time_p95_ms >= fp.lsp_response_time_p50_ms


def test_compute_lsp_percentiles_empty_uses_sentinel() -> None:
    fp = compute(
        Path("."),
        lsp_response_times_ms=[],
        commit_timestamps=[],
        now=1,
    )
    assert fp.lsp_response_time_p50_ms == NO_SIGNAL_SENTINEL
    assert fp.lsp_response_time_p95_ms == NO_SIGNAL_SENTINEL


def test_compute_test_suite_runtime_passthrough() -> None:
    fp = compute(
        Path("."),
        test_suite_runtime_seconds=42,
        commit_timestamps=[],
        now=1,
    )
    assert fp.test_suite_runtime_seconds == 42


def test_compute_commit_frequency_from_explicit_timestamps() -> None:
    fp = compute(
        Path("."),
        commit_timestamps=[1, 2, 3, 4, 5, 6, 7, 8],
        now=1,
    )
    # 8 commits over 4 weeks = 2 per week.
    assert fp.commit_frequency_per_week == pytest.approx(2.0)


def test_compute_commit_frequency_empty_list_returns_zero() -> None:
    fp = compute(Path("."), commit_timestamps=[], now=1)
    assert fp.commit_frequency_per_week == 0.0


def test_compute_commit_frequency_no_git_returns_zero(tmp_path: Path) -> None:
    fp = compute(tmp_path, now=1)
    # No .git dir at tmp_path.
    assert fp.commit_frequency_per_week == 0.0


def test_write_and_read_roundtrip(tmp_path: Path) -> None:
    fp = RepoFingerprint(
        avg_function_tokens=150.0,
        avg_import_depth=5.5,
        lsp_response_time_p50_ms=100,
        lsp_response_time_p95_ms=300,
        test_suite_runtime_seconds=60,
        commit_frequency_per_week=3.5,
        recorded_at=1234,
    )
    target = write(fp, tmp_path)
    assert target == tmp_path / FINGERPRINT_RECORD_PATH
    loaded = read(tmp_path)
    assert loaded == fp


def test_read_missing_returns_none(tmp_path: Path) -> None:
    assert read(tmp_path) is None


def test_read_wrong_schema_version_raises(tmp_path: Path) -> None:
    target = tmp_path / FINGERPRINT_RECORD_PATH
    target.parent.mkdir(parents=True)
    payload = {
        "schema_version": 99,
        "avg_function_tokens": 0.0,
        "avg_import_depth": 0.0,
        "lsp_response_time_p50_ms": -1,
        "lsp_response_time_p95_ms": -1,
        "test_suite_runtime_seconds": -1,
        "commit_frequency_per_week": 0.0,
        "recorded_at": 1,
    }
    target.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="unsupported schema_version"):
        read(tmp_path)


def test_read_malformed_json_raises(tmp_path: Path) -> None:
    target = tmp_path / FINGERPRINT_RECORD_PATH
    target.parent.mkdir(parents=True)
    target.write_text("not json", encoding="utf-8")
    with pytest.raises(ValueError, match="not valid JSON"):
        read(tmp_path)


def test_write_atomic_no_leftover_tmp(tmp_path: Path) -> None:
    fp = RepoFingerprint(
        avg_function_tokens=0.0,
        avg_import_depth=0.0,
        lsp_response_time_p50_ms=NO_SIGNAL_SENTINEL,
        lsp_response_time_p95_ms=NO_SIGNAL_SENTINEL,
        test_suite_runtime_seconds=NO_SIGNAL_SENTINEL,
        commit_frequency_per_week=0.0,
        recorded_at=0,
    )
    write(fp, tmp_path)
    # v0.5.1 wiring module_10 (Lens A C2): state dir unified on ``.ract/``.
    leftover = list((tmp_path / ".ract" / "fingerprint").glob("*.tmp"))
    assert leftover == []


# ---------------------------------------------------------------------------
# Mapper
# ---------------------------------------------------------------------------


def _make_fingerprint(**overrides: object) -> RepoFingerprint:
    base = dict(
        avg_function_tokens=0.0,
        avg_import_depth=0.0,
        lsp_response_time_p50_ms=NO_SIGNAL_SENTINEL,
        lsp_response_time_p95_ms=NO_SIGNAL_SENTINEL,
        test_suite_runtime_seconds=NO_SIGNAL_SENTINEL,
        commit_frequency_per_week=0.0,
        recorded_at=0,
        schema_version=FINGERPRINT_SCHEMA_VERSION,
    )
    base.update(overrides)
    return RepoFingerprint(**base)  # type: ignore[arg-type]


def test_mapper_no_signal_returns_all_none() -> None:
    defaults = retrieval_defaults_from_fingerprint(_make_fingerprint())
    assert defaults == RetrievalDefaults(
        cache_ttl_seconds=None,
        neighborhood_max_symbols=None,
        per_symbol_target_tokens=None,
    )


def test_mapper_slow_lsp_raises_cache_ttl() -> None:
    fp = _make_fingerprint(
        lsp_response_time_p50_ms=200,
        lsp_response_time_p95_ms=500,
    )
    defaults = retrieval_defaults_from_fingerprint(fp)
    assert defaults.cache_ttl_seconds == 600


def test_mapper_fast_lsp_short_cache_ttl() -> None:
    fp = _make_fingerprint(
        lsp_response_time_p50_ms=50,
        lsp_response_time_p95_ms=100,
    )
    defaults = retrieval_defaults_from_fingerprint(fp)
    assert defaults.cache_ttl_seconds == 60


def test_mapper_large_functions_bump_per_symbol_target() -> None:
    fp = _make_fingerprint(avg_function_tokens=500.0)
    defaults = retrieval_defaults_from_fingerprint(fp)
    assert defaults.per_symbol_target_tokens == 800


def test_mapper_high_import_depth_caps_neighborhood() -> None:
    fp = _make_fingerprint(avg_import_depth=15.0)
    defaults = retrieval_defaults_from_fingerprint(fp)
    assert defaults.neighborhood_max_symbols == 15


def test_mapper_is_pure_same_input_same_output() -> None:
    fp = _make_fingerprint(
        avg_function_tokens=500.0,
        lsp_response_time_p95_ms=300,
        avg_import_depth=12.0,
    )
    d1 = retrieval_defaults_from_fingerprint(fp)
    d2 = retrieval_defaults_from_fingerprint(fp)
    assert d1 == d2
