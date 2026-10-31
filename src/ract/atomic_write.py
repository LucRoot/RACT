"""Write a file whole, through a temporary file nobody else can have prepared (B-212).

LR:: A write through a predictable temporary name (``.NAME.ract-tmp``) could be
redirected: a hard link planted at that name made the bytes land in a file
outside the workspace, and a link there was followed. The temporary file here
is created by ``tempfile.mkstemp`` in the same folder: a random name, opened
with exclusive create, so an existing name is never opened. The final rename
replaces the directory entry and does not write through a link at the target.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def write_atomic(path: Path | str, data: bytes) -> None:
    """Write *data* to *path* whole: a fresh temporary file, then one rename."""
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temp_name = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".ract-tmp", dir=target.parent
    )
    temp = Path(temp_name)
    try:
        with os.fdopen(handle, "wb") as out:
            out.write(data)
        os.replace(temp, target)
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except OSError as exc:
            print(f"[atomic_write] the temporary file {temp} stays: {exc}", flush=True)
        raise


__all__ = ["write_atomic"]
