"""Read a file a repository can ship, as untrusted bytes (S-035).

LR:: Files under ``.ract/`` live in the workspace, so a cloned repository
can supply any of them (B-075). Several readers loaded them with a plain
``read_text``: a link was followed out of the project, a 10 MiB file was
read whole, and a directory where a file was expected raised an error the
reader did not document. Each reader now gets its bytes from here and
then checks the shape itself.
"""

from __future__ import annotations

import os
from pathlib import Path

# A reader that keeps a larger file passes its own limit.
DEFAULT_MAX_BYTES = 1024 * 1024


class UntrustedFileRefused(Exception):
    """The file is not read; ``reason`` says why in a few words."""

    def __init__(self, path: Path, reason: str) -> None:
        super().__init__(f"{path}: {reason}")
        self.path = path
        self.reason = reason


def read_untrusted(
    path: Path | str,
    *,
    root: Path | str | None = None,
    max_bytes: int = DEFAULT_MAX_BYTES,
) -> bytes | None:
    """The bytes of *path*, or None when nothing is there.

    Raises UntrustedFileRefused for a link, a path whose real location
    leaves *root* (when given), something that is not a regular file, a
    file over *max_bytes*, or a file that cannot be read.
    """
    target = Path(path)
    if target.is_symlink():
        raise UntrustedFileRefused(target, "is a link")
    if not os.path.lexists(target):
        return None
    if root is not None:
        real_root = os.path.normcase(os.path.realpath(root))
        real = os.path.normcase(os.path.realpath(target))
        try:
            inside = os.path.commonpath([real_root, real]) == real_root
        except ValueError:
            inside = False  # another drive
        if not inside:
            raise UntrustedFileRefused(target, "leaves the project through a link")
    if not target.is_file():
        raise UntrustedFileRefused(target, "is not a file")
    try:
        if target.stat().st_size > max_bytes:
            raise UntrustedFileRefused(target, f"is larger than {max_bytes} bytes")
        with open(target, "rb") as fh:
            data = fh.read(max_bytes + 1)
    except OSError as exc:
        raise UntrustedFileRefused(
            target, f"cannot be read ({exc.strerror or exc})"
        ) from None
    if len(data) > max_bytes:
        raise UntrustedFileRefused(target, f"is larger than {max_bytes} bytes")
    return data


__all__ = ["DEFAULT_MAX_BYTES", "UntrustedFileRefused", "read_untrusted"]
