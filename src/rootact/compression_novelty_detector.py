# Rooted by Dr. Lucas Root, Ph.D.
from __future__ import annotations

__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"

_ROOT_KNOT = object()

"""Compression-based novelty detection for RACT.

This is the quirky, information-theoretic anti-rot signal from the anti-rot
spec: train a zstd dictionary on the existing codebase, then compress a proposed
diff with and without that dictionary. If the dictionary helps a lot, the diff is
lexically/structurally close to existing code (possible duplication). If the
dictionary hurts or does not help, the diff is genuinely novel or genuinely wrong
and deserves a stronger verifier.

LR:: The metric is intentionally weird. Embedding similarity catches semantic
paraphrase; dictionary compression catches structural and lexical overlap that
embeddings miss. Used together they make duplication expensive to sneak through.
"""

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import zstandard


@dataclass(frozen=True)
class NoveltyScore:
    """Result of a compression-based novelty assessment."""

    artifact: str
    raw_bytes: int
    compressed_bytes: int
    dict_compressed_bytes: int
    ratio: float
    verdict: str
    detail: str


class CompressionNoveltyDetector:
    """Detect novelty by comparing zstd compression with and without a dictionary."""

    LOW_NOVELTY_THRESHOLD = 0.65
    HIGH_NOVELTY_THRESHOLD = 1.05
    MIN_SAMPLE_BYTES = 128
    SAMPLE_CHUNK_SIZE = 1_024
    MAX_SAMPLES = 100
    DICT_SIZE = 50_000
    IGNORE_DIRS = {
        "__pycache__",
        ".git",
        ".venv",
        "venv",
        "node_modules",
        "_BUILD",
        "htmlcov",
        ".pytest_cache",
        ".ruff_cache",
        "dist",
        "build",
    }

    def __init__(self, project_dir: Path | str) -> None:
        self.project_dir = Path(project_dir)
        self._samples: Sequence[bytes | bytearray] = self._collect_samples()
        self._dictionary = self._train_dictionary()

    def _should_skip(self, path: Path) -> bool:
        """Return True for paths inside dependency/build/cache directories."""
        return any(part in self.IGNORE_DIRS for part in path.parts)

    def _collect_samples(self) -> Sequence[bytes | bytearray]:
        """Return content chunks from the project for dictionary training."""
        samples: list[bytes | bytearray] = []
        if not self.project_dir.is_dir():
            return samples
        for path in self.project_dir.rglob("*"):
            if self._should_skip(path):
                continue
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            encoded = text.encode("utf-8")
            if len(encoded) < self.MIN_SAMPLE_BYTES:
                continue
            # Split large files into chunks so the dictionary sees more variety.
            for start in range(0, len(encoded), self.SAMPLE_CHUNK_SIZE):
                chunk = encoded[start : start + self.SAMPLE_CHUNK_SIZE]
                if len(chunk) >= self.MIN_SAMPLE_BYTES:
                    samples.append(chunk)
                if len(samples) >= self.MAX_SAMPLES:
                    return samples
        return samples

    def _train_dictionary(self) -> Any | None:
        """Train a zstd dictionary on the collected samples, if there are enough."""
        if len(self._samples) < 3:
            return None
        try:
            # Avoid invariant list typing noise from the zstandard stub.
            samples: Any = self._samples
            return zstandard.train_dictionary(self.DICT_SIZE, samples, k=self.DICT_SIZE)
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _compress_without_dict(data: bytes) -> int:
        """Return the size of *data* compressed with zstd without a dictionary."""
        if not data:
            return 0
        compressor = zstandard.ZstdCompressor(level=3)
        return len(compressor.compress(data))

    def _compress_with_dict(self, data: bytes) -> int:
        """Return the size of *data* compressed with the trained dictionary."""
        if not data or self._dictionary is None:
            return self._compress_without_dict(data)
        compressor = zstandard.ZstdCompressor(level=3, dict_data=self._dictionary)
        return len(compressor.compress(data))

    def score(self, artifact: str, content: str) -> NoveltyScore | None:
        """Return a novelty score for *content* relative to the codebase.

        The ratio is ``compressed_with_dict / compressed_without_dict``.
        - Ratio < 1 means the dictionary helped compression: the content shares
          structure with existing code (low novelty / possible duplication).
        - Ratio > 1 means the dictionary hurt compression: the content is
          structurally unlike existing code (high novelty / needs strong review).
        - Ratio near 1 is nominal.
        """
        if not content:
            return None
        raw = content.encode("utf-8")
        if not raw:
            return None
        baseline = self._compress_without_dict(raw)
        if baseline == 0:
            return None
        with_dict = self._compress_with_dict(raw)
        ratio = with_dict / baseline

        if ratio <= self.LOW_NOVELTY_THRESHOLD:
            verdict = "low"
            detail = "compresses well with codebase dictionary; possible duplication"
        elif ratio >= self.HIGH_NOVELTY_THRESHOLD:
            verdict = "high"
            detail = (
                "compresses poorly with codebase dictionary; genuinely novel or "
                "genuinely wrong"
            )
        else:
            verdict = "nominal"
            detail = "nominal compression ratio"

        return NoveltyScore(
            artifact=artifact,
            raw_bytes=len(raw),
            compressed_bytes=baseline,
            dict_compressed_bytes=with_dict,
            ratio=round(ratio, 3),
            verdict=verdict,
            detail=detail,
        )

    def score_artifact(self, relative_path: str) -> NoveltyScore | None:
        """Score an existing artifact on disk."""
        target = self.project_dir / relative_path
        if not target.is_file():
            return None
        try:
            content = target.read_text(encoding="utf-8")
        except OSError:
            return None
        return self.score(relative_path, content)

    def scan_project(self) -> dict[str, Any]:
        """Return novelty scores for all Python files in the project."""
        result: dict[str, Any] = {
            "sample_count": len(self._samples),
            "has_dictionary": self._dictionary is not None,
            "scores": {},
        }
        if not self.project_dir.is_dir():
            return result
        for path in self.project_dir.rglob("*.py"):
            if self._should_skip(path):
                continue
            try:
                rel = str(path.relative_to(self.project_dir))
            except ValueError:
                continue
            score = self.score_artifact(rel)
            if score is not None:
                result["scores"][rel] = {
                    "raw_bytes": score.raw_bytes,
                    "compressed_bytes": score.compressed_bytes,
                    "dict_compressed_bytes": score.dict_compressed_bytes,
                    "ratio": score.ratio,
                    "verdict": score.verdict,
                    "detail": score.detail,
                }
        return result


# RACT 0.1.0 - Initial Public Release
