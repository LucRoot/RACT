"""Embedding model wrappers for the v0.5.0 semantic index.

Master spec: ``docs/RACT_v0.5.0_MEMORY_DISCIPLINE_SPEC.md`` §Semantic
index. The semantic index in :mod:`ract.memory.semantic_index` reads
the model via the :class:`EmbeddingModel` protocol; two named models
ship (``bge-small-en-v1.5`` at 384-dim, ``nomic-embed-text-v1.5`` at
768-dim) plus a synthetic fallback for CI / offline tests.

The synthetic fallback (:class:`SyntheticHashEmbedding`) produces
deterministic vectors from an SHA-256 of the input text. It is NOT a
semantic embedding; its job is to let the schema + store surface
under test without a real model on disk. Tests that require a real
model gate on ``os.environ["RACT_EMBED_ONLINE"] == "1"`` and skip
otherwise (Second Pass Q2: offline-friendly install path).

Model wrappers lazy-import :mod:`sentence_transformers` inside
:meth:`~BgeSmallEmbedding.embed` so a caller that only wants the
synthetic path does not pay the ``torch`` import cost. The wrapper
caches the loaded model on the instance so repeat calls reuse the
same weights.
"""

from __future__ import annotations

import hashlib
import math
import os
import struct
import threading
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from ract.core.module_identity import _module_knot, register_module_knot


BGE_SMALL_NAME: str = "bge-small-en-v1.5"
BGE_SMALL_DIM: int = 384
BGE_SMALL_HF_ID: str = "BAAI/bge-small-en-v1.5"

NOMIC_NAME: str = "nomic-embed-text-v1.5"
NOMIC_DIM: int = 768
NOMIC_HF_ID: str = "nomic-ai/nomic-embed-text-v1.5"

SYNTHETIC_384_NAME: str = "synthetic-384"
SYNTHETIC_768_NAME: str = "synthetic-768"

DEFAULT_MODEL_NAME: str = BGE_SMALL_NAME
"""The default model the semantic index picks when the caller does not name one."""

ONLINE_ENV_VAR: str = "RACT_EMBED_ONLINE"
"""Env var whose ``"1"`` value gates real-model tests / weight download."""

LOCAL_MODEL_ROOT_ENV_VAR: str = "RACT_EMBED_MODEL_ROOT"
"""Env var pointing at a local model root (``.rack/models/embeddings/``)."""


class EmbeddingError(RuntimeError):
    """Raised when an embedding call cannot produce a vector."""


class UnknownEmbeddingError(EmbeddingError):
    """Raised when :func:`load_embedding` is asked for an unknown model name."""


class EmbeddingModelUnavailableError(EmbeddingError):
    """Raised when a real embedding model is asked for but its weights
    are missing and offline install is not configured.

    The message names the fallback path (either
    ``RACT_EMBED_ONLINE=1`` to allow download, or a local
    ``.rack/models/embeddings/<name>/`` weights directory) so the
    caller has a specific fix rather than an opaque HuggingFace
    stacktrace (Second Pass Q2).
    """


@runtime_checkable
class EmbeddingModel(Protocol):
    """Callable that returns deterministic vectors for text.

    The semantic index reads this protocol only; production models
    (BGE / Nomic) and the synthetic fallback all satisfy it. The
    ``name`` field lets the store record which model produced the
    stored vectors so a mismatch on later re-open surfaces an
    explicit :class:`~ract.memory.semantic_index.EmbeddingModelMismatchError`
    rather than a silent vector-space swap (Lateral Chain branch E).
    """

    name: str
    dim: int

    def embed(self, text: str) -> list[float]: ...

    def embed_batch(self, texts: list[str]) -> list[list[float]]: ...


# ---------------------------------------------------------------------------
# Synthetic (CI / offline) embedding
# ---------------------------------------------------------------------------


class SyntheticHashEmbedding:
    """Deterministic hash-based fallback embedding.

    Produces a vector of ``dim`` floats in ``[-1.0, 1.0]`` derived
    from the SHA-256 of the input text. Same text always maps to the
    same vector; single-embed and batch-embed produce identical
    vectors for the same input (invariant asserted in
    ``tests/memory/test_semantic_index_embedding.py``).

    NOT a semantic embedding. The vectors carry no meaning beyond
    identity: cosine similarity is high for the same string and near
    zero for any two different strings. Its purpose is to let the
    store + query API + budget-respect logic run under test without
    a real model on disk, and to give the shipped CI green even when
    ``sentence_transformers`` is not installed.
    """

    def __init__(self, dim: int = BGE_SMALL_DIM, name: str | None = None) -> None:
        if dim <= 0:
            raise ValueError(f"SyntheticHashEmbedding.dim must be positive; got {dim}")
        self.dim: int = dim
        self.name: str = name or f"synthetic-{dim}"

    def embed(self, text: str) -> list[float]:
        # SHA-256 gives 32 bytes = 8 floats via little-endian float32.
        # To fill ``dim`` floats we hash text, then hash the hash bytes,
        # until we have enough. Result is deterministic per text.
        needed_bytes = self.dim * 4
        buffer = bytearray()
        counter = 0
        while len(buffer) < needed_bytes:
            hasher = hashlib.sha256()
            hasher.update(text.encode("utf-8", errors="replace"))
            hasher.update(counter.to_bytes(4, "little"))
            buffer.extend(hasher.digest())
            counter += 1
        raw = bytes(buffer[:needed_bytes])
        # Interpret as float32 then map through tanh to [-1, 1]. Some
        # bit patterns land on NaN / Inf under float32 so we mask those
        # out to zero for a stable numeric surface.
        floats: list[float] = []
        for offset in range(0, needed_bytes, 4):
            (value,) = struct.unpack_from("<f", raw, offset)
            if not math.isfinite(value):
                floats.append(0.0)
                continue
            # tanh compresses the wildly varied float32 magnitudes into
            # a bounded range so downstream cosine + L2 metrics do not
            # underflow / overflow.
            floats.append(math.tanh(value))
        # Normalise to unit length so cosine similarity is well defined.
        norm = math.sqrt(sum(v * v for v in floats))
        if norm == 0.0:
            floats[0] = 1.0
            norm = 1.0
        return [v / norm for v in floats]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        return [self.embed(text) for text in texts]


# ---------------------------------------------------------------------------
# Real embedding wrappers (lazy sentence-transformers import)
# ---------------------------------------------------------------------------


class _SentenceTransformerBase:
    """Shared machinery for the two shipped real embedders."""

    hf_id: str
    name: str
    dim: int

    def __init__(self) -> None:
        self._model: Any = None
        self._load_lock = threading.Lock()

    def _local_model_dir(self) -> Path | None:
        """Return the local weights dir for this model, if configured.

        The installer's ``ract memory init`` (module_09) drops the
        weights at ``.rack/models/embeddings/<name>/``. The env var
        ``RACT_EMBED_MODEL_ROOT`` names the parent directory so tests
        and non-standard installs can point elsewhere.
        """
        root = os.environ.get(LOCAL_MODEL_ROOT_ENV_VAR)
        if not root:
            return None
        candidate = Path(root) / self.name
        if candidate.is_dir():
            return candidate
        return None

    def _ensure_loaded(self) -> Any:
        if self._model is not None:
            return self._model
        with self._load_lock:
            if self._model is not None:
                return self._model
            local_dir = self._local_model_dir()
            online = os.environ.get(ONLINE_ENV_VAR) == "1"
            if local_dir is None and not online:
                raise EmbeddingModelUnavailableError(
                    f"Embedding model {self.name!r} has no local weights and "
                    f"online download is not enabled. Fix either:\n"
                    f"  1. Set {LOCAL_MODEL_ROOT_ENV_VAR!s}=<dir> where "
                    f"<dir>/{self.name!s}/ contains the model files, OR\n"
                    f"  2. Set {ONLINE_ENV_VAR!s}=1 to allow HuggingFace "
                    f"download from {self.hf_id!s}."
                )
            try:
                import sentence_transformers  # type: ignore[import-not-found]
            except ModuleNotFoundError as exc:
                raise EmbeddingModelUnavailableError(
                    f"sentence-transformers is not installed; cannot load "
                    f"embedding {self.name!r}. Install it (``pip install "
                    f"'sentence-transformers>=3.0'``) or use "
                    f"SyntheticHashEmbedding for offline / CI runs."
                ) from exc
            model_path = str(local_dir) if local_dir is not None else self.hf_id
            try:
                self._model = sentence_transformers.SentenceTransformer(model_path)
            except Exception as exc:
                raise EmbeddingModelUnavailableError(
                    f"Failed to load embedding {self.name!r} from "
                    f"{model_path!r}. If this was a download attempt, verify "
                    f"network access; if a local path, verify the model files "
                    f"are complete. Underlying error: {exc}"
                ) from exc
            return self._model

    def embed(self, text: str) -> list[float]:
        return self.embed_batch([text])[0]

    def embed_batch(self, texts: list[str]) -> list[list[float]]:
        if not texts:
            return []
        model = self._ensure_loaded()
        # ``encode`` returns a numpy array; ``.tolist()`` gives Python lists.
        # ``normalize_embeddings=True`` matches BGE + Nomic recommended usage
        # for cosine similarity retrieval.
        vectors = model.encode(
            texts,
            normalize_embeddings=True,
            convert_to_numpy=True,
            show_progress_bar=False,
        )
        result: list[list[float]] = [[float(x) for x in vector] for vector in vectors]
        for row in result:
            if len(row) != self.dim:
                raise EmbeddingError(
                    f"Embedding model {self.name!r} produced a vector of "
                    f"length {len(row)}; expected {self.dim}"
                )
        return result


class BgeSmallEmbedding(_SentenceTransformerBase):
    """``bge-small-en-v1.5`` — 384-dim, MIT license, CPU-friendly."""

    hf_id: str = BGE_SMALL_HF_ID
    name: str = BGE_SMALL_NAME
    dim: int = BGE_SMALL_DIM


class NomicEmbedTextEmbedding(_SentenceTransformerBase):
    """``nomic-embed-text-v1.5`` — 768-dim, Apache-2.0."""

    hf_id: str = NOMIC_HF_ID
    name: str = NOMIC_NAME
    dim: int = NOMIC_DIM


# ---------------------------------------------------------------------------
# Dispatch
# ---------------------------------------------------------------------------


_KNOWN_MODELS: dict[str, type[Any]] = {
    BGE_SMALL_NAME: BgeSmallEmbedding,
    NOMIC_NAME: NomicEmbedTextEmbedding,
}


def load_embedding(name: str = DEFAULT_MODEL_NAME) -> EmbeddingModel:
    """Return the :class:`EmbeddingModel` implementation named ``name``.

    Known names:

    - ``bge-small-en-v1.5`` — :class:`BgeSmallEmbedding` (default).
    - ``nomic-embed-text-v1.5`` — :class:`NomicEmbedTextEmbedding`.
    - ``synthetic-384`` — :class:`SyntheticHashEmbedding` at 384-dim.
    - ``synthetic-768`` — :class:`SyntheticHashEmbedding` at 768-dim.

    Any other name raises :class:`UnknownEmbeddingError`. The
    dispatch does not touch the model weights; :meth:`embed` triggers
    the lazy load.
    """
    if name == SYNTHETIC_384_NAME:
        return SyntheticHashEmbedding(dim=384, name=name)
    if name == SYNTHETIC_768_NAME:
        return SyntheticHashEmbedding(dim=768, name=name)
    cls = _KNOWN_MODELS.get(name)
    if cls is None:
        raise UnknownEmbeddingError(
            f"Unknown embedding {name!r}; known names are "
            f"{sorted(list(_KNOWN_MODELS) + [SYNTHETIC_384_NAME, SYNTHETIC_768_NAME])!r}"
        )
    return cls()  # type: ignore[no-any-return]


__all__ = [
    "BGE_SMALL_DIM",
    "BGE_SMALL_HF_ID",
    "BGE_SMALL_NAME",
    "BgeSmallEmbedding",
    "DEFAULT_MODEL_NAME",
    "EmbeddingError",
    "EmbeddingModel",
    "EmbeddingModelUnavailableError",
    "LOCAL_MODEL_ROOT_ENV_VAR",
    "NOMIC_DIM",
    "NOMIC_HF_ID",
    "NOMIC_NAME",
    "NomicEmbedTextEmbedding",
    "ONLINE_ENV_VAR",
    "SYNTHETIC_384_NAME",
    "SYNTHETIC_768_NAME",
    "SyntheticHashEmbedding",
    "UnknownEmbeddingError",
    "load_embedding",
]


_MODULE_KNOT = _module_knot()
register_module_knot(__name__, _MODULE_KNOT)


# RACT 0.5.0
