"""B-092 (D-100): a rewrite keeps a leading BOM; a new file gets none; it is never doubled.

H3 in docs/ux/windows_files.md: a full rewrite of a file that started with a
byte order mark dropped it.
"""

from __future__ import annotations

from pathlib import Path

from ract.diff_applier import DiffApplier
from ract.executor.steps import Executor
from ract.write_gate import with_bom_of
from tests.test_reasoning_model_handling import _Adapter, _plan, _response, _Router

BOM = b"\xef\xbb\xbf"
NEW = 'def greet(name):\n    return f"hi {name}"\n'


def _rewrite(tmp_path: Path, before: bytes | None, reply: str) -> bytes:
    target = tmp_path / "hello.py"
    if before is not None:
        target.write_bytes(before)
    result = Executor(
        _Router(_Adapter(_response(reply))), project_dir=tmp_path
    ).execute(intent="i", plan=_plan())
    assert result.is_ok(), result.error
    return target.read_bytes()


def test_a_rewrite_keeps_the_bom(tmp_path: Path) -> None:
    after = _rewrite(tmp_path, BOM + b"def greet(name):\n    return name\n", NEW)
    assert after.startswith(BOM) and not after.startswith(BOM + BOM)
    assert after[3:].replace(b"\r\n", b"\n") == NEW.encode()


def test_no_bom_stays_no_bom(tmp_path: Path) -> None:
    after = _rewrite(tmp_path, b"def greet(name):\n    return name\n", "﻿" + NEW)
    assert not after.startswith(BOM)


def test_a_reply_with_its_own_bom_is_not_doubled(tmp_path: Path) -> None:
    after = _rewrite(tmp_path, BOM + b"def greet(name):\n    return name\n", "﻿" + NEW)
    assert after.startswith(BOM) and not after[3:].startswith(BOM)


def test_a_new_file_gets_no_bom(tmp_path: Path) -> None:
    after = _rewrite(tmp_path, None, "﻿" + NEW)
    assert not after.startswith(BOM)


def test_the_rule() -> None:
    assert with_bom_of(BOM + b"x", "y") == "﻿y"
    assert with_bom_of(BOM + b"x", "﻿﻿y") == "﻿y"
    assert with_bom_of(b"x", "﻿y") == "y"
    assert with_bom_of(None, "﻿y") == "y"


def test_a_diff_keeps_every_byte_outside_the_edit(tmp_path: Path) -> None:
    original = BOM + b"def greet(name):\r\n    return name\r\n\r\n\r\nX = 1\r\n"
    target = tmp_path / "hello.py"
    target.write_bytes(original)
    diff = (
        "--- a/hello.py\n+++ b/hello.py\n@@ -1,2 +1,2 @@\n"
        " def greet(name):\n-    return name\n+    return name.upper()\n"
    )
    [result] = DiffApplier(tmp_path).apply_diff(diff)
    assert result.applied, result.message
    after = target.read_bytes()
    assert after == original.replace(b"return name\r", b"return name.upper()\r")


def test_a_binary_file_is_untouched(tmp_path: Path) -> None:
    blob = tmp_path / "logo.bin"
    data = BOM + bytes(range(256))
    blob.write_bytes(data)
    _rewrite(tmp_path, BOM + b"def greet(name):\n    return name\n", NEW)
    assert blob.read_bytes() == data
