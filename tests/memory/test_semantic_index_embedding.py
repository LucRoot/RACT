"""Tests for :mod:`ract.memory.embedding` — the embedder wrappers."""

from __future__ import annotations

import os

import pytest

from ract.memory.embedding import (
    BGE_SMALL_DIM,
    BGE_SMALL_NAME,
    NOMIC_DIM,
    NOMIC_NAME,
    ONLINE_ENV_VAR,
    SYNTHETIC_384_NAME,
    SYNTHETIC_768_NAME,
    BgeSmallEmbedding,
    EmbeddingModel,
    EmbeddingModelUnavailableError,
    NomicEmbedTextEmbedding,
    SyntheticHashEmbedding,
    UnknownEmbeddingError,
    load_embedding,
)


# ---------------------------------------------------------------------------
# Protocol / dispatch
# ---------------------------------------------------------------------------


def test_load_embedding_synthetic_384_returns_synthetic_hash():
    embedder = load_embedding(SYNTHETIC_384_NAME)
    assert isinstance(embedder, SyntheticHashEmbedding)
    assert embedder.dim == 384
    assert embedder.name == SYNTHETIC_384_NAME


def test_load_embedding_synthetic_768_returns_synthetic_hash():
    embedder = load_embedding(SYNTHETIC_768_NAME)
    assert isinstance(embedder, SyntheticHashEmbedding)
    assert embedder.dim == 768
    assert embedder.name == SYNTHETIC_768_NAME


def test_load_embedding_bge_small_returns_bge_class():
    embedder = load_embedding(BGE_SMALL_NAME)
    assert isinstance(embedder, BgeSmallEmbedding)
    assert embedder.name == BGE_SMALL_NAME
    assert embedder.dim == BGE_SMALL_DIM


def test_load_embedding_nomic_returns_nomic_class():
    embedder = load_embedding(NOMIC_NAME)
    assert isinstance(embedder, NomicEmbedTextEmbedding)
    assert embedder.name == NOMIC_NAME
    assert embedder.dim == NOMIC_DIM


def test_load_embedding_unknown_name_raises():
    with pytest.raises(UnknownEmbeddingError):
        load_embedding("no-such-model")


def test_synthetic_embedder_satisfies_protocol():
    embedder = SyntheticHashEmbedding(dim=384)
    assert isinstance(embedder, EmbeddingModel)


def test_bge_embedder_satisfies_protocol():
    embedder = BgeSmallEmbedding()
    assert isinstance(embedder, EmbeddingModel)


# ---------------------------------------------------------------------------
# Synthetic-embedder guarantees
# ---------------------------------------------------------------------------


def test_synthetic_embedding_dim_matches_configured():
    embedder = SyntheticHashEmbedding(dim=384)
    vec = embedder.embed("hello world")
    assert len(vec) == 384


def test_synthetic_embedding_is_deterministic():
    embedder = SyntheticHashEmbedding(dim=64)
    a = embedder.embed("hello")
    b = embedder.embed("hello")
    assert a == b


def test_synthetic_embedding_different_texts_produce_different_vectors():
    embedder = SyntheticHashEmbedding(dim=64)
    a = embedder.embed("hello")
    b = embedder.embed("goodbye")
    assert a != b


def test_synthetic_embedding_normalised_to_unit_length():
    embedder = SyntheticHashEmbedding(dim=384)
    vec = embedder.embed("normalise me")
    magnitude = sum(v * v for v in vec) ** 0.5
    assert abs(magnitude - 1.0) < 1e-6


def test_synthetic_embedding_batch_matches_single():
    embedder = SyntheticHashEmbedding(dim=384)
    texts = ["one", "two", "three"]
    single = [embedder.embed(t) for t in texts]
    batch = embedder.embed_batch(texts)
    assert single == batch


def test_synthetic_embedding_rejects_non_positive_dim():
    with pytest.raises(ValueError):
        SyntheticHashEmbedding(dim=0)
    with pytest.raises(ValueError):
        SyntheticHashEmbedding(dim=-4)


def test_synthetic_embedding_empty_string_still_produces_vector():
    embedder = SyntheticHashEmbedding(dim=64)
    vec = embedder.embed("")
    assert len(vec) == 64
    magnitude = sum(v * v for v in vec) ** 0.5
    assert abs(magnitude - 1.0) < 1e-6


# ---------------------------------------------------------------------------
# Real-embedder unavailable-path
# ---------------------------------------------------------------------------


def test_bge_embedder_offline_without_local_dir_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Second Pass Q2: error message must name the fallback path."""
    monkeypatch.delenv(ONLINE_ENV_VAR, raising=False)
    monkeypatch.delenv("RACT_EMBED_MODEL_ROOT", raising=False)
    embedder = BgeSmallEmbedding()
    with pytest.raises(EmbeddingModelUnavailableError) as exc_info:
        embedder.embed("hello")
    message = str(exc_info.value)
    assert "RACT_EMBED_ONLINE" in message
    assert "RACT_EMBED_MODEL_ROOT" in message


def test_nomic_embedder_offline_without_local_dir_raises_actionable_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.delenv(ONLINE_ENV_VAR, raising=False)
    monkeypatch.delenv("RACT_EMBED_MODEL_ROOT", raising=False)
    embedder = NomicEmbedTextEmbedding()
    with pytest.raises(EmbeddingModelUnavailableError) as exc_info:
        embedder.embed("hello")
    message = str(exc_info.value)
    assert "RACT_EMBED_ONLINE" in message


# ---------------------------------------------------------------------------
# GPU-only real-model path (skipped in default CI)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    os.environ.get(ONLINE_ENV_VAR) != "1",
    reason="Requires RACT_EMBED_ONLINE=1 and a working HuggingFace download",
)
def test_bge_embedder_online_returns_384_dim_vectors():
    embedder = BgeSmallEmbedding()
    vecs = embedder.embed_batch(["a", "b"])
    assert len(vecs) == 2
    assert all(len(v) == BGE_SMALL_DIM for v in vecs)


@pytest.mark.skipif(
    os.environ.get(ONLINE_ENV_VAR) != "1",
    reason="Requires RACT_EMBED_ONLINE=1 and a working HuggingFace download",
)
def test_nomic_embedder_online_returns_768_dim_vectors():
    embedder = NomicEmbedTextEmbedding()
    vecs = embedder.embed_batch(["a", "b"])
    assert len(vecs) == 2
    assert all(len(v) == NOMIC_DIM for v in vecs)


# RACT 0.5.0
