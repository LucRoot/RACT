"""A Ctrl-C pressed just before a console read starts is not held until Enter (S-027).

LR:: On Windows, ``input()`` writes its prompt and then calls ReadConsoleW.
A Ctrl-C that arrives in between is handled (Python's flag is set) but no
read is pending to abort, so the read that follows waits for Enter and the
interrupt shows only then. Measured with a 100 KB prompt to widen the window:
9 of 30 Ctrl-C presses were held; with ``read_line``, none of 30.

``read_line`` marks each read with a number. A console control handler
(Windows calls it on its own thread) notes a Ctrl-C; if the same read is
still blocked 30 ms later, it cancels the reading thread's synchronous I/O,
so ReadConsoleW returns and the interrupt arrives. A Ctrl-C with no read in
progress is left to Python, which raises it at its next check, before any
read starts. Elsewhere than Windows, ``read_line`` is ``input``.
"""

from __future__ import annotations

import builtins
import os
import threading
import time
from typing import Any

_STUCK_AFTER = 0.03
_lock = threading.Lock()
# The read in progress: its number and the reading thread's handle.
_reading: dict[str, Any] = {"n": 0, "thread": None}
_counter = 0
_installed = False
_handler: Any = None


def _install() -> None:
    """Register the console control handler once, on Windows."""
    global _installed, _handler
    if _installed or os.name != "nt":
        return
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    handler_type = ctypes.WINFUNCTYPE(  # type: ignore[attr-defined]
        wintypes.BOOL, wintypes.DWORD
    )
    kernel32.SetConsoleCtrlHandler.argtypes = [handler_type, wintypes.BOOL]

    def on_ctrl(kind: int) -> bool:
        if kind == 0:  # CTRL_C_EVENT
            _note_ctrl_c()
        return False  # Python's own handler still runs and sets its flag

    _handler = handler_type(on_ctrl)  # kept alive for the life of the process
    if not kernel32.SetConsoleCtrlHandler(_handler, True):
        err = ctypes.get_last_error()  # type: ignore[attr-defined]
        print(f"[console_interrupt] SetConsoleCtrlHandler failed: {err}", flush=True)
        return
    _installed = True


def _note_ctrl_c() -> None:
    """A Ctrl-C arrived: cancel the read in progress if it is still blocked a moment later."""
    with _lock:
        n = _reading["n"]
    if not n:
        return  # no read in progress: Python raises it at its next check
    threading.Thread(target=_cancel_if_stuck, args=(n,), daemon=True).start()


def _cancel_if_stuck(n: int) -> None:
    time.sleep(_STUCK_AFTER)
    with _lock:
        handle = _reading["thread"] if _reading["n"] == n else None
    if handle is not None:
        _cancel(handle)


def _cancel(handle: Any) -> None:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.CancelSynchronousIo.argtypes = [ctypes.c_void_p]
    kernel32.CancelSynchronousIo(
        handle
    )  # ERROR_NOT_FOUND when the read already returned


def _open_current_thread() -> Any:
    import ctypes
    from ctypes import wintypes

    kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)  # type: ignore[attr-defined]
    kernel32.OpenThread.restype = ctypes.c_void_p
    kernel32.OpenThread.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
    # CancelSynchronousIo needs THREAD_TERMINATE on the handle.
    return kernel32.OpenThread(0x0001, False, threading.get_native_id())


def _close(handle: Any) -> None:
    import ctypes

    kernel32 = ctypes.WinDLL("kernel32")  # type: ignore[attr-defined]
    kernel32.CloseHandle(ctypes.c_void_p(handle))


def read_line(prompt: str = "") -> str:
    """``input(prompt)``, with a Ctrl-C just before the read raised, not held (S-027)."""
    if os.name != "nt":
        return builtins.input(prompt)
    global _counter
    _install()
    handle = _open_current_thread()
    with _lock:
        _counter += 1
        _reading["n"] = _counter
        _reading["thread"] = handle
    try:
        return builtins.input(prompt)
    finally:
        with _lock:
            _reading["n"] = 0
            _reading["thread"] = None
        if handle:
            _close(handle)
