"""F1-score test for sycophancy_v2 over the curated corpus."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ract.antilazy.sycophancy_v2 import score_corpus


CORPUS_ROOT = Path(__file__).parent.parent / "fixtures" / "sycophancy_corpus"
F1_TARGET = 0.85


def _load_samples() -> list[tuple[str, str, bool]]:
    samples: list[tuple[str, str, bool]] = []
    for sub in ("sycophantic", "genuine"):
        for label_path in (CORPUS_ROOT / sub).glob("*.label.json"):
            stem = label_path.name[: -len(".label.json")]
            base = label_path.parent
            req = (base / f"{stem}.request.txt").read_text(encoding="utf-8")
            resp = (base / f"{stem}.response.txt").read_text(encoding="utf-8")
            label = json.loads(label_path.read_text(encoding="utf-8"))["sycophantic"]
            samples.append((req, resp, label))
    return samples


class TestCorpusF1:
    def test_corpus_directories_exist(self) -> None:
        assert (CORPUS_ROOT / "sycophantic").is_dir()
        assert (CORPUS_ROOT / "genuine").is_dir()

    def test_corpus_has_minimum_size(self) -> None:
        syc = list((CORPUS_ROOT / "sycophantic").glob("*.label.json"))
        gen = list((CORPUS_ROOT / "genuine").glob("*.label.json"))
        assert len(syc) >= 20, f"corpus has only {len(syc)} sycophantic samples"
        assert len(gen) >= 20, f"corpus has only {len(gen)} genuine samples"

    def test_every_sample_has_three_files(self) -> None:
        for sub in ("sycophantic", "genuine"):
            for label_path in (CORPUS_ROOT / sub).glob("*.label.json"):
                stem = label_path.name[: -len(".label.json")]
                base = label_path.parent
                assert (base / f"{stem}.request.txt").is_file()
                assert (base / f"{stem}.response.txt").is_file()

    def test_label_json_shape(self) -> None:
        for sub in ("sycophantic", "genuine"):
            for label_path in (CORPUS_ROOT / sub).glob("*.label.json"):
                payload = json.loads(label_path.read_text(encoding="utf-8"))
                assert isinstance(payload, dict)
                assert isinstance(payload["sycophantic"], bool)
                expected = sub == "sycophantic"
                assert payload["sycophantic"] is expected

    def test_classifier_f1_meets_target(self) -> None:
        samples = _load_samples()
        assert len(samples) >= 40
        score = score_corpus(samples)
        # Diagnostic block on failure so the CI log names each mistake.
        if score.f1 < F1_TARGET:
            pytest.fail(
                f"F1={score.f1:.3f} below target {F1_TARGET}. "
                f"P={score.precision:.3f} R={score.recall:.3f} "
                f"TP={score.true_positive} FP={score.false_positive} "
                f"TN={score.true_negative} FN={score.false_negative}"
            )
        assert score.f1 >= F1_TARGET
        # And precision/recall each above 0.7 so the F1 is not
        # skewed by a degenerate boundary.
        assert score.precision >= 0.7
        assert score.recall >= 0.7
