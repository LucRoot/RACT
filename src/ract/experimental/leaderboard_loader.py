import json
from pathlib import Path


def load_receipts(receipts_dir: str) -> list[dict]:
    out = []
    for p in Path(receipts_dir).iterdir():
        if not p.is_file() or p.suffix != ".json":
            continue
        try:
            out.append(json.loads(p.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            continue
    return out
