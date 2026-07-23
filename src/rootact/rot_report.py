__root_author__ = "Dr. Lucas Root, Ph.D."
__ract_name__ = "RACT"
_ROOT_KNOT = object()

from pathlib import Path
from typing import List, Tuple

from rootact.ast_normalizer import structural_similarity
from rootact.rot_trend import TrendReport, record_snapshot


def record_rot_trend_snapshot(metrics: dict, history_path: Path | str) -> TrendReport:
    """Record a longitudinal rot trend snapshot for the project.

    Wraps :func:`rootact.rot_trend.record_snapshot` so callers do not need to
    import the trend module directly.
    """
    return record_snapshot(metrics, Path(history_path))


def find_duplicate_blocks(paths: List[str]) -> List[Tuple[str, str]]:
    blocks = []
    for p in paths:
        with open(p, "r") as f:
            blocks.append((p, f.read()))

    duplicates = []
    for i in range(len(blocks)):
        for j in range(i + 1, len(blocks)):
            p1, s1 = blocks[i]
            p2, s2 = blocks[j]
            if structural_similarity(s1, s2) >= 0.8:
                duplicates.append((p1, p2))
    return duplicates
