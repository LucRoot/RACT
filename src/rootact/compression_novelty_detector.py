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

import io
import tokenize

import zstandard

from rootact.ast_normalizer import structural_hash


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
    nearest: str | None = None


class CompressionNoveltyDetector:
    """Detect novelty by comparing zstd compression with and without a dictionary."""

    LOW_NOVELTY_THRESHOLD = 0.75
    HIGH_NOVELTY_THRESHOLD = 1.05
    LOW_NEIGHBOR_THRESHOLD = 0.15
    HIGH_NEIGHBOR_THRESHOLD = 0.75
    STRUCTURAL_DUPLICATE_THRESHOLD = 0.85
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
        self._samples_by_path: dict[Path, list[bytes | bytearray]] = {}
        self._samples: Sequence[bytes | bytearray] = self._collect_samples()
        self._dictionary = self._train_dictionary()
        self._structural_hashes: dict[str, str | None] = {}
        self._structural_lengths: dict[str, int] = {}
        self._preload_structural_hashes()

    def _preload_structural_hashes(self) -> None:
        """Precompute AST-normalized hashes for all project Python files.

        Caching avoids re-parsing and re-normalizing the same files on every
        novelty assessment. Invalid or unreadable files are cached as None.
        """
        if not self.project_dir.is_dir():
            return
        for path in self.project_dir.rglob("*.py"):
            if self._should_skip(path):
                continue
            try:
                rel = str(path.relative_to(self.project_dir))
                content = path.read_text(encoding="utf-8")
            except (OSError, ValueError):
                continue
            self._structural_hashes[rel] = structural_hash(content)
            self._structural_lengths[rel] = len(content)

    def _should_skip(self, path: Path) -> bool:
        """Return True for paths inside dependency/build/cache directories."""
        return any(part in self.IGNORE_DIRS for part in path.parts)

    @staticmethod
    def _strip_prose(source: str) -> str:
        """Remove comments and string literals from Python source.

        LR:: Docstrings, inline comments, and string literals carry prose-like
        patterns. If they are included in dictionary training, the dictionary
        learns generic text sequences and starts to classify prose and data as
        familiar code. Stripping them focuses the dictionary on Python syntax
        and structure, widening the gap between genuinely novel Python and
        non-Python content.

        The stripped source does not need to remain syntactically valid; it
        only needs to expose the lexical and structural patterns that help
        zstd distinguish Python from prose.
        """
        try:
            ranges: list[tuple[int, int]] = []
            readline = io.StringIO(source).readline
            for tok in tokenize.generate_tokens(readline):
                if tok.type in {tokenize.COMMENT, tokenize.STRING}:
                    ranges.append((tok.start[0], tok.end[0]))
            if not ranges:
                return source
            drop_lines: set[int] = set()
            for start_line, end_line in ranges:
                for ln in range(start_line, end_line + 1):
                    drop_lines.add(ln)
            # Preserve line count by replacing dropped lines with blank lines.
            return "".join(
                "\n" if (i + 1) in drop_lines else line
                for i, line in enumerate(source.splitlines(keepends=True))
            )
        except (SyntaxError, tokenize.TokenError):
            # If tokenization fails, fall back to the raw source. This keeps
            # the detector robust against unusual or partial Python files.
            return source

    def _collect_samples(self) -> Sequence[bytes | bytearray]:
        """Return Python source chunks from the project for dictionary training.

        LR:: Training only on ``*.py`` keeps the dictionary focused on the
        project's lexical and structural patterns. Non-Python files (docs,
        data, fences) would dilute the signal and make genuinely novel Python
        look more familiar than it is.
        """
        samples: list[bytes | bytearray] = []
        self._samples_by_path = {}
        if not self.project_dir.is_dir():
            return samples
        # Sort paths for deterministic dictionary training across filesystems.
        for path in sorted(self.project_dir.rglob("*.py")):
            if self._should_skip(path):
                continue
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            stripped = self._strip_prose(text)
            encoded = stripped.encode("utf-8")
            if len(encoded) < self.MIN_SAMPLE_BYTES:
                # Fall back to the raw source so small files still contribute
                # samples when stripping removes too much content.
                encoded = text.encode("utf-8")
                if len(encoded) < self.MIN_SAMPLE_BYTES:
                    continue
            file_samples: list[bytes | bytearray] = []
            # Split large files into chunks so the dictionary sees more variety.
            for start in range(0, len(encoded), self.SAMPLE_CHUNK_SIZE):
                chunk = encoded[start : start + self.SAMPLE_CHUNK_SIZE]
                if len(chunk) >= self.MIN_SAMPLE_BYTES:
                    samples.append(chunk)
                    file_samples.append(chunk)
                if len(samples) >= self.MAX_SAMPLES:
                    self._samples_by_path[path] = file_samples
                    return samples
            self._samples_by_path[path] = file_samples
        return samples

    def _train_dictionary(self, exclude_path: Path | None = None) -> Any | None:
        """Train a zstd dictionary on the collected samples.

        If *exclude_path* is given, omit any chunks collected from that file so
        scoring the file itself does not benefit from its own content. This is
        the leave-one-out correction for ``scan_project``.
        """
        if exclude_path is None:
            samples = self._samples
        else:
            excluded = set()
            try:
                excluded = {
                    id(chunk) for chunk in self._samples_by_path.get(exclude_path, [])
                }
            except TypeError:
                pass
            samples = [chunk for chunk in self._samples if id(chunk) not in excluded]
        if len(samples) < 3:
            return None
        try:
            # Avoid invariant list typing noise from the zstandard stub.
            samples_any: Any = samples
            return zstandard.train_dictionary(
                self.DICT_SIZE, samples_any, k=self.DICT_SIZE
            )
        except Exception:  # noqa: BLE001
            return None

    @staticmethod
    def _compress_without_dict(data: bytes) -> int:
        """Return the size of *data* compressed with zstd without a dictionary."""
        if not data:
            return 0
        compressor = zstandard.ZstdCompressor(level=3)
        return len(compressor.compress(data))

    def _compress_with_dict(self, data: bytes, dictionary: Any | None = None) -> int:
        """Return the size of *data* compressed with the given dictionary."""
        if not data:
            return self._compress_without_dict(data)
        dictionary = dictionary if dictionary is not None else self._dictionary
        if dictionary is None:
            return self._compress_without_dict(data)
        compressor = zstandard.ZstdCompressor(level=3, dict_data=dictionary)
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

    def _score_with_dict(
        self, artifact: str, content: str, dictionary: Any | None
    ) -> NoveltyScore | None:
        """Return a novelty score using *dictionary* instead of the default."""
        if not content:
            return None
        raw = content.encode("utf-8")
        if not raw:
            return None
        baseline = self._compress_without_dict(raw)
        if baseline == 0:
            return None
        with_dict = self._compress_with_dict(raw, dictionary=dictionary)
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

    def assess_new_artifact(self, artifact: str, content: str) -> NoveltyScore | None:
        """Score a proposed new artifact and identify the nearest existing one.

        Uses the project-wide dictionary trained on the whole codebase.
        """
        return self._assess_with_dict(artifact, content, self._dictionary)

    def _assess_with_dict(
        self, artifact: str, content: str, dictionary: Any | None
    ) -> NoveltyScore | None:
        """Score a proposed new artifact and identify the nearest existing one.

        The final novelty ratio blends the dictionary ratio with the nearest-
        neighbor conditional ratio and AST-normalized structural similarity.
        A verbatim copy of an existing module scores very low on all three,
        while a copy whose identifiers have all been renamed still scores high
        on structural similarity and is caught.
        """
        score = self._score_with_dict(artifact, content, dictionary)
        if score is None:
            return None

        exclude: set[str] = {artifact}
        target = self.project_dir / artifact
        try:
            if target.is_file():
                exclude.add(str(target.relative_to(self.project_dir)))
        except ValueError:
            pass

        nearest, nn_ratio = self._nearest_similar_artifact_with_ratio(
            content, exclude=exclude, dictionary=dictionary
        )
        struct_nearest, struct_sim = self._nearest_structural_similarity(
            content, exclude=exclude
        )

        # AST-normalized structural similarity catches copy-and-rename clones
        # that compression-based signals miss entirely.
        if struct_sim is not None and struct_sim >= self.STRUCTURAL_DUPLICATE_THRESHOLD:
            return NoveltyScore(
                artifact=score.artifact,
                raw_bytes=score.raw_bytes,
                compressed_bytes=score.compressed_bytes,
                dict_compressed_bytes=score.dict_compressed_bytes,
                ratio=round(1.0 - struct_sim, 3),
                verdict="low",
                detail="structural duplicate of an existing module; possible copy-and-rename",
                nearest=struct_nearest,
            )

        # Without a nearest-neighbor signal there is nothing to blend; fall back
        # to the dictionary-only score.
        if nn_ratio is None:
            return NoveltyScore(
                artifact=score.artifact,
                raw_bytes=score.raw_bytes,
                compressed_bytes=score.compressed_bytes,
                dict_compressed_bytes=score.dict_compressed_bytes,
                ratio=score.ratio,
                verdict=score.verdict,
                detail=score.detail,
                nearest=nearest,
            )

        # Nearest-neighbor conditional ratio is the strongest duplication
        # signal: it measures how cheaply the new content encodes when appended
        # to the most similar existing file. A verbatim copy approaches zero;
        # genuinely novel Python is structurally unlike every existing file.
        # We use it as the primary signal and fall back to the dictionary ratio
        # only when the nearest-neighbor signal is ambiguous.
        if nn_ratio is not None and nn_ratio <= self.LOW_NEIGHBOR_THRESHOLD:
            verdict = "low"
            detail = (
                "matches an existing module's structure closely; possible duplication"
            )
            final_ratio = nn_ratio
        elif nn_ratio is not None and nn_ratio >= self.HIGH_NEIGHBOR_THRESHOLD:
            verdict = "high"
            detail = "structurally unlike any existing module; genuinely novel or wrong"
            final_ratio = nn_ratio
        elif score.ratio <= self.LOW_NOVELTY_THRESHOLD:
            verdict = "low"
            detail = "compresses well with codebase dictionary; possible duplication"
            final_ratio = score.ratio
        elif score.ratio >= self.HIGH_NOVELTY_THRESHOLD:
            verdict = "high"
            detail = (
                "compresses poorly with codebase dictionary; genuinely novel or wrong"
            )
            final_ratio = score.ratio
        else:
            verdict = "nominal"
            detail = "nominal compression ratio"
            final_ratio = score.ratio

        return NoveltyScore(
            artifact=score.artifact,
            raw_bytes=score.raw_bytes,
            compressed_bytes=score.compressed_bytes,
            dict_compressed_bytes=score.dict_compressed_bytes,
            ratio=round(final_ratio, 3),
            verdict=verdict,
            detail=detail,
            nearest=nearest,
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

    def score_artifact_leave_one_out(self, relative_path: str) -> NoveltyScore | None:
        """Score an existing artifact with a dictionary trained on the rest of the code.

        This prevents a file from being flagged as a near-duplicate of itself
        simply because the global dictionary was trained on its own content.
        """
        target = self.project_dir / relative_path
        if not target.is_file():
            return None
        try:
            content = target.read_text(encoding="utf-8")
        except OSError:
            return None
        loo_dict = self._train_dictionary(exclude_path=target)
        return self._assess_with_dict(relative_path, content, loo_dict)

    def _conditional_ratio(
        self,
        content: str,
        existing_path: Path,
        dictionary: Any | None = None,
    ) -> float | None:
        """Return the incremental cost of encoding *content* after *existing_path*.

        The ratio is ``(compress(Y + X with dict) - compress(Y with dict))
        / compress(X without dict)``. When X is a verbatim or near-verbatim
        continuation of Y, the incremental cost approaches zero. When X is
        structurally unlike Y, the cost approaches (or exceeds) the cost of
        compressing X from scratch.
        """
        try:
            existing = existing_path.read_text(encoding="utf-8")
        except OSError:
            return None
        existing_bytes = existing.encode("utf-8")
        content_bytes = content.encode("utf-8")
        if not content_bytes:
            return None
        existing_with_dict = self._compress_with_dict(existing_bytes, dictionary)
        combined_with_dict = self._compress_with_dict(
            existing_bytes + b"\n" + content_bytes, dictionary
        )
        content_without_dict = self._compress_without_dict(content_bytes)
        if content_without_dict == 0:
            return None
        incremental = combined_with_dict - existing_with_dict
        if incremental < 0:
            incremental = 0
        return incremental / content_without_dict

    def _nearest_similar_artifact_with_ratio(
        self,
        content: str,
        exclude: set[str] | None = None,
        dictionary: Any | None = None,
    ) -> tuple[str | None, float | None]:
        """Return the existing artifact most similar to *content* and its ratio.

        Similarity is measured by the conditional compression ratio: how
        cheaply the new content encodes when appended to each existing file.
        A low value means the new content is a natural continuation of that
        file (possible duplication).
        """
        if not content or not self.project_dir.is_dir():
            return None, None
        exclude = exclude or set()
        best_path: str | None = None
        best_ratio: float | None = None
        for path in self.project_dir.rglob("*.py"):
            if self._should_skip(path):
                continue
            try:
                rel = str(path.relative_to(self.project_dir))
            except ValueError:
                continue
            if rel in exclude:
                continue
            ratio = self._conditional_ratio(content, path, dictionary=dictionary)
            if ratio is None:
                continue
            if best_ratio is None or ratio < best_ratio:
                best_ratio = ratio
                best_path = rel
        return best_path, best_ratio

    def _nearest_structural_similarity(
        self,
        content: str,
        exclude: set[str] | None = None,
    ) -> tuple[str | None, float | None]:
        """Return the existing artifact that is an exact structural duplicate.

        Uses AST-normalized hashes so renamed clones with identical structure are
        detected instantly. Exact matching keeps the novelty scan fast enough to
        run on every write.
        """
        if not content or not self.project_dir.is_dir():
            return None, None
        exclude = exclude or set()
        content_hash = structural_hash(content)
        if content_hash is None:
            return None, None
        for rel, existing_hash in self._structural_hashes.items():
            if rel in exclude:
                continue
            if existing_hash == content_hash:
                return rel, 1.0
        return None, None

    def nearest_similar_artifact(
        self, content: str, exclude: set[str] | None = None
    ) -> str | None:
        """Return the existing artifact that compresses most like *content*.

        The lowest conditional compression ratio indicates the most lexical/
        structural overlap with existing code. This is used to tell the model
        which existing file to extend instead of creating a near-duplicate.
        """
        path, _ratio = self._nearest_similar_artifact_with_ratio(
            content, exclude=exclude
        )
        return path

    def scan_project(self) -> dict[str, Any]:
        """Return novelty scores for all Python files in the project."""
        return self._scan_project(fast=False)

    def scan_project_fast(self) -> dict[str, Any]:
        """Return dictionary-only novelty scores for all Python files.

        Skips the O(n^2) nearest-neighbor conditional ratio so the scan
        finishes quickly on large repos. The trade-off is that structural
        duplicates detected only by nearest-neighbor comparison may be missed.
        """
        return self._scan_project(fast=True)

    def _scan_project(self, fast: bool) -> dict[str, Any]:
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
            if fast:
                score = self.score_artifact(rel)
            else:
                score = self.score_artifact_leave_one_out(rel)
            if score is not None:
                result["scores"][rel] = {
                    "raw_bytes": score.raw_bytes,
                    "compressed_bytes": score.compressed_bytes,
                    "dict_compressed_bytes": score.dict_compressed_bytes,
                    "ratio": score.ratio,
                    "verdict": score.verdict,
                    "detail": score.detail,
                    "nearest": score.nearest,
                }
        return result


# RACT 0.1.1 - Trust and Tooling
