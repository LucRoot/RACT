"""Write a file whole, through a temporary file nobody else can have prepared (B-212).

LR:: A write through a predictable temporary name (``.NAME.ract-tmp``) could be
redirected: a hard link planted at that name made the bytes land in a file
outside the workspace, and a link there was followed. The temporary file here
is created by ``tempfile.mkstemp`` in the same folder: a random name, opened
with exclusive create, so an existing name is never opened. The final rename
replaces the directory entry and does not write through a link at the target.

``mkstemp`` creates the file with mode 0600, so on POSIX the written file
takes the mode the target had (a script keeps its executable bit), or for a
new file the mode a plain create would give under the process umask (G-289).
"""

from __future__ import annotations

import os
import stat
import tempfile
import threading
from pathlib import Path

_UMASK_LOCK = threading.Lock()


def _umask() -> int:
    """The process umask, read without leaving it changed."""
    try:
        for line in Path("/proc/self/status").read_text(encoding="ascii").splitlines():
            if line.startswith("Umask:"):
                return int(line.split()[1], 8)
    except (OSError, ValueError) as exc:
        print(f"[atomic_write] umask read the slow way: {exc}", flush=True)
    with _UMASK_LOCK:
        mask = os.umask(0o022)
        os.umask(mask)
    return mask


def _mode_for(target: Path) -> int:
    """The mode the written file gets: the target's own, else a new file's."""
    try:
        info = os.stat(target, follow_symlinks=False)
    except FileNotFoundError:
        return 0o666 & ~_umask()
    if stat.S_ISREG(info.st_mode):
        return stat.S_IMODE(info.st_mode)
    return 0o666 & ~_umask()


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
            if os.name != "nt":
                os.fchmod(out.fileno(), _mode_for(target))
            out.write(data)
        os.replace(temp, target)
    except BaseException:
        try:
            temp.unlink(missing_ok=True)
        except OSError as exc:
            print(f"[atomic_write] the temporary file {temp} stays: {exc}", flush=True)
        raise


__all__ = ["write_atomic"]
