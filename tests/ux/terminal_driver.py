"""Drive a program in a real pseudo-terminal and record what a user would see.

UX walkthroughs (``docs/ux/``) must run the real binary in a real terminal,
because a mocked ``input()`` hides exactly the things a person notices:
prompt redraws, colors, line editing, Ctrl-C handling and silences. This
driver starts a program in a pseudo-terminal (ConPTY on Windows, ``pty`` on
POSIX), sends keystrokes, and records every byte of output with a timestamp.

From the recording it reports the time to first visible output after each
input and the longest silent gap, the two numbers ``UX_BAR.md`` asks for.

Standard library only (``ctypes`` on Windows). Test and walkthrough tooling;
nothing under ``src/`` imports it.
"""

from __future__ import annotations

import os
import re
import subprocess
import sys
import threading
import time
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

ANSI_RE = re.compile(
    r"\x1b\[[0-?]*[ -/]*[@-~]"  # CSI
    r"|\x1b\][^\x07\x1b]*(?:\x07|\x1b\\)"  # OSC
    r"|\x1b[@-Z\\-_]"  # two-byte escapes
)


def strip_ansi(text: str) -> str:
    """Remove escape sequences and normalize line endings."""
    text = ANSI_RE.sub("", text)
    return text.replace("\r\n", "\n").replace("\r", "\n")


@dataclass
class Event:
    """One chunk of output (``out``) or one input sent (``in``)."""

    t: float
    kind: str
    data: str


@dataclass
class Recording:
    """Everything that happened in a session, with times relative to start."""

    argv: list[str]
    events: list[Event] = field(default_factory=list)
    exit_code: int | None = None

    @property
    def raw(self) -> str:
        return "".join(e.data for e in self.events if e.kind == "out")

    @property
    def plain(self) -> str:
        return strip_ansi(self.raw)

    def first_output_after(self, t: float) -> float | None:
        for e in self.events:
            if e.kind == "out" and e.t > t and strip_ansi(e.data).strip():
                return e.t - t
        return None

    def longest_silence(self, *, start: float = 0.0, end: float | None = None) -> float:
        """Longest gap between visible output chunks inside [start, end]."""
        stamps = [start] + [
            e.t
            for e in self.events
            if e.kind == "out" and strip_ansi(e.data).strip() and e.t >= start
        ]
        if end is not None:
            stamps = [s for s in stamps if s <= end] + [end]
        return max((b - a for a, b in zip(stamps, stamps[1:])), default=0.0)

    def timeline(self) -> str:
        """Readable log: one line per input and per output chunk."""
        lines = []
        for e in self.events:
            shown = strip_ansi(e.data) if e.kind == "out" else repr(e.data)
            shown = shown.replace("\n", "\\n")
            lines.append(f"{e.t:8.3f}s {e.kind:>3} {shown[:200]}")
        return "\n".join(lines)


class _Session:
    """Common driver API; platform classes implement spawn, read, write, close."""

    def __init__(
        self,
        argv: Sequence[str],
        *,
        cwd: str | None,
        env: Mapping[str, str] | None,
        cols: int,
        rows: int,
    ) -> None:
        self.recording = Recording(list(argv))
        self._t0 = time.perf_counter()
        self._lock = threading.Lock()
        self._buffer = ""
        self._closed = threading.Event()

    def now(self) -> float:
        return time.perf_counter() - self._t0

    def _on_output(self, data: str) -> None:
        with self._lock:
            self.recording.events.append(Event(self.now(), "out", data))
            self._buffer += data

    def send(self, text: str) -> float:
        """Type text. Returns the session time at which it was sent."""
        t = self.now()
        with self._lock:
            self.recording.events.append(Event(t, "in", text))
        self._write(text.encode("utf-8"))
        return t

    def send_line(self, text: str) -> float:
        return self.send(text + "\r")

    def ctrl_c(self) -> float:
        return self.send("\x03")

    def expect(self, pattern: str, timeout: float = 30.0) -> bool:
        """Wait until the plain output since the last match contains pattern."""
        regex = re.compile(pattern)
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            with self._lock:
                plain = strip_ansi(self._buffer)
                m = regex.search(plain)
                if m:
                    # Consume up to the match so the next expect looks forward.
                    self._buffer = plain[m.end() :]
                    return True
            if self._closed.is_set():
                break
            time.sleep(0.02)
        return False

    def wait_quiet(self, seconds: float, timeout: float = 60.0) -> None:
        """Wait until no output has arrived for ``seconds``."""
        deadline = time.perf_counter() + timeout
        while time.perf_counter() < deadline:
            with self._lock:
                last = max(
                    (e.t for e in self.recording.events if e.kind == "out"), default=0.0
                )
            if self.now() - last >= seconds or self._closed.is_set():
                return
            time.sleep(0.05)

    # platform hooks
    def _write(self, data: bytes) -> None:  # pragma: no cover - platform specific
        raise NotImplementedError

    def close(self, timeout: float = 5.0) -> Recording:  # pragma: no cover
        raise NotImplementedError


# ---------------------------------------------------------------------------
# Windows ConPTY
# ---------------------------------------------------------------------------

if sys.platform == "win32":
    import ctypes
    from ctypes import wintypes

    _k32 = ctypes.WinDLL("kernel32", use_last_error=True)

    class _COORD(ctypes.Structure):
        _fields_ = [("X", wintypes.SHORT), ("Y", wintypes.SHORT)]

    class _STARTUPINFOW(ctypes.Structure):
        _fields_ = [
            ("cb", wintypes.DWORD),
            ("lpReserved", wintypes.LPWSTR),
            ("lpDesktop", wintypes.LPWSTR),
            ("lpTitle", wintypes.LPWSTR),
            ("dwX", wintypes.DWORD),
            ("dwY", wintypes.DWORD),
            ("dwXSize", wintypes.DWORD),
            ("dwYSize", wintypes.DWORD),
            ("dwXCountChars", wintypes.DWORD),
            ("dwYCountChars", wintypes.DWORD),
            ("dwFillAttribute", wintypes.DWORD),
            ("dwFlags", wintypes.DWORD),
            ("wShowWindow", wintypes.WORD),
            ("cbReserved2", wintypes.WORD),
            ("lpReserved2", ctypes.c_void_p),
            ("hStdInput", wintypes.HANDLE),
            ("hStdOutput", wintypes.HANDLE),
            ("hStdError", wintypes.HANDLE),
        ]

    class _STARTUPINFOEXW(ctypes.Structure):
        _fields_ = [
            ("StartupInfo", _STARTUPINFOW),
            ("lpAttributeList", ctypes.c_void_p),
        ]

    class _PROCESS_INFORMATION(ctypes.Structure):
        _fields_ = [
            ("hProcess", wintypes.HANDLE),
            ("hThread", wintypes.HANDLE),
            ("dwProcessId", wintypes.DWORD),
            ("dwThreadId", wintypes.DWORD),
        ]

    _PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE = 0x00020016
    _EXTENDED_STARTUPINFO_PRESENT = 0x00080000
    _CREATE_UNICODE_ENVIRONMENT = 0x00000400
    _STILL_ACTIVE = 259
    _STARTF_USESTDHANDLES = 0x00000100

    _k32.CreatePseudoConsole.argtypes = [
        _COORD,
        wintypes.HANDLE,
        wintypes.HANDLE,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_void_p),
    ]
    _k32.CreatePseudoConsole.restype = ctypes.c_long
    _k32.ClosePseudoConsole.argtypes = [ctypes.c_void_p]
    _k32.CreatePipe.argtypes = [
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.POINTER(wintypes.HANDLE),
        ctypes.c_void_p,
        wintypes.DWORD,
    ]
    _k32.InitializeProcThreadAttributeList.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        wintypes.DWORD,
        ctypes.POINTER(ctypes.c_size_t),
    ]
    _k32.UpdateProcThreadAttribute.argtypes = [
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_size_t,
        ctypes.c_void_p,
        ctypes.c_void_p,
    ]
    _k32.CreateProcessW.argtypes = [
        wintypes.LPCWSTR,
        wintypes.LPWSTR,
        ctypes.c_void_p,
        ctypes.c_void_p,
        wintypes.BOOL,
        wintypes.DWORD,
        ctypes.c_void_p,
        wintypes.LPCWSTR,
        ctypes.c_void_p,
        ctypes.POINTER(_PROCESS_INFORMATION),
    ]
    _k32.ReadFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    _k32.WriteFile.argtypes = [
        wintypes.HANDLE,
        ctypes.c_void_p,
        wintypes.DWORD,
        ctypes.POINTER(wintypes.DWORD),
        ctypes.c_void_p,
    ]
    _k32.GetExitCodeProcess.argtypes = [wintypes.HANDLE, ctypes.POINTER(wintypes.DWORD)]
    _k32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]
    _k32.TerminateProcess.argtypes = [wintypes.HANDLE, wintypes.UINT]
    _k32.CloseHandle.argtypes = [wintypes.HANDLE]

    def _check(ok: object, what: str) -> None:
        if not ok:
            raise OSError(ctypes.get_last_error(), f"{what} failed")

    class _ConPtySession(_Session):
        def __init__(
            self,
            argv: Sequence[str],
            *,
            cwd: str | None,
            env: Mapping[str, str] | None,
            cols: int,
            rows: int,
        ) -> None:
            super().__init__(argv, cwd=cwd, env=env, cols=cols, rows=rows)
            in_read, in_write = wintypes.HANDLE(), wintypes.HANDLE()
            out_read, out_write = wintypes.HANDLE(), wintypes.HANDLE()
            _check(
                _k32.CreatePipe(ctypes.byref(in_read), ctypes.byref(in_write), None, 0),
                "CreatePipe",
            )
            _check(
                _k32.CreatePipe(
                    ctypes.byref(out_read), ctypes.byref(out_write), None, 0
                ),
                "CreatePipe",
            )
            self._hpc = ctypes.c_void_p()
            hr = _k32.CreatePseudoConsole(
                _COORD(cols, rows), in_read, out_write, 0, ctypes.byref(self._hpc)
            )
            if hr != 0:
                raise OSError(hr, "CreatePseudoConsole failed")
            _k32.CloseHandle(in_read)
            _k32.CloseHandle(out_write)
            self._in_write, self._out_read = in_write, out_read

            size = ctypes.c_size_t()
            _k32.InitializeProcThreadAttributeList(None, 1, 0, ctypes.byref(size))
            self._attr_buf = ctypes.create_string_buffer(size.value)
            _check(
                _k32.InitializeProcThreadAttributeList(
                    self._attr_buf, 1, 0, ctypes.byref(size)
                ),
                "InitializeProcThreadAttributeList",
            )
            _check(
                _k32.UpdateProcThreadAttribute(
                    self._attr_buf,
                    0,
                    _PROC_THREAD_ATTRIBUTE_PSEUDOCONSOLE,
                    self._hpc,
                    ctypes.sizeof(ctypes.c_void_p),
                    None,
                    None,
                ),
                "UpdateProcThreadAttribute",
            )
            si = _STARTUPINFOEXW()
            si.StartupInfo.cb = ctypes.sizeof(_STARTUPINFOEXW)
            # Without STARTF_USESTDHANDLES and null handles, a child of a
            # parent whose stdio is redirected inherits the parent's pipes and
            # writes there instead of to the pseudo console.
            si.StartupInfo.dwFlags = _STARTF_USESTDHANDLES
            si.lpAttributeList = ctypes.cast(self._attr_buf, ctypes.c_void_p)
            pi = _PROCESS_INFORMATION()
            merged = dict(os.environ if env is None else env)
            env_block = ctypes.create_unicode_buffer(
                "".join(f"{k}={v}\0" for k, v in merged.items()) + "\0"
            )
            cmdline = ctypes.create_unicode_buffer(subprocess.list2cmdline(list(argv)))
            _check(
                _k32.CreateProcessW(
                    None,
                    cmdline,
                    None,
                    None,
                    False,
                    _EXTENDED_STARTUPINFO_PRESENT | _CREATE_UNICODE_ENVIRONMENT,
                    env_block,
                    cwd,
                    ctypes.byref(si),
                    ctypes.byref(pi),
                ),
                "CreateProcessW",
            )
            self._hprocess, self._hthread = pi.hProcess, pi.hThread
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()

        def _read_loop(self) -> None:
            buf = ctypes.create_string_buffer(65536)
            n = wintypes.DWORD()
            pending = b""
            while True:
                ok = _k32.ReadFile(self._out_read, buf, len(buf), ctypes.byref(n), None)
                if not ok or n.value == 0:
                    break
                pending += buf.raw[: n.value]
                try:
                    text = pending.decode("utf-8")
                    pending = b""
                except UnicodeDecodeError as exc:
                    text = pending[: exc.start].decode("utf-8")
                    pending = pending[exc.start :]
                if text:
                    self._on_output(text)
            self._closed.set()

        def _write(self, data: bytes) -> None:
            n = wintypes.DWORD()
            _k32.WriteFile(self._in_write, data, len(data), ctypes.byref(n), None)

        def alive(self) -> bool:
            code = wintypes.DWORD()
            _k32.GetExitCodeProcess(self._hprocess, ctypes.byref(code))
            return code.value == _STILL_ACTIVE

        def close(self, timeout: float = 5.0) -> Recording:
            if _k32.WaitForSingleObject(self._hprocess, int(timeout * 1000)) != 0:
                _k32.TerminateProcess(self._hprocess, 1)
                _k32.WaitForSingleObject(self._hprocess, 2000)
            code = wintypes.DWORD()
            _k32.GetExitCodeProcess(self._hprocess, ctypes.byref(code))
            self.recording.exit_code = int(code.value)
            # The reader must keep draining while the pseudo console closes.
            _k32.ClosePseudoConsole(self._hpc)
            self._reader.join(timeout=5)
            for h in (self._in_write, self._out_read, self._hprocess, self._hthread):
                _k32.CloseHandle(h)
            return self.recording


# ---------------------------------------------------------------------------
# POSIX pty
# ---------------------------------------------------------------------------

else:
    import fcntl
    import pty
    import struct
    import termios

    class _PosixSession(_Session):
        def __init__(
            self,
            argv: Sequence[str],
            *,
            cwd: str | None,
            env: Mapping[str, str] | None,
            cols: int,
            rows: int,
        ) -> None:
            super().__init__(argv, cwd=cwd, env=env, cols=cols, rows=rows)
            master, slave = pty.openpty()
            fcntl.ioctl(
                slave, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0)
            )
            self._proc = subprocess.Popen(
                list(argv),
                stdin=slave,
                stdout=slave,
                stderr=slave,
                cwd=cwd,
                env=dict(env) if env is not None else None,
                start_new_session=True,
                close_fds=True,
            )
            os.close(slave)
            self._master = master
            self._reader = threading.Thread(target=self._read_loop, daemon=True)
            self._reader.start()

        def _read_loop(self) -> None:
            while True:
                try:
                    data = os.read(self._master, 65536)
                except OSError:
                    break
                if not data:
                    break
                self._on_output(data.decode("utf-8", "replace"))
            self._closed.set()

        def _write(self, data: bytes) -> None:
            os.write(self._master, data)

        def alive(self) -> bool:
            return self._proc.poll() is None

        def close(self, timeout: float = 5.0) -> Recording:
            try:
                self._proc.wait(timeout=timeout)
            except subprocess.TimeoutExpired:
                self._proc.kill()
                self._proc.wait(timeout=5)
            self.recording.exit_code = self._proc.returncode
            self._reader.join(timeout=5)
            os.close(self._master)
            return self.recording


def spawn(
    argv: Sequence[str],
    *,
    cwd: str | None = None,
    env: Mapping[str, str] | None = None,
    cols: int = 80,
    rows: int = 30,
) -> _Session:
    """Start ``argv`` in a pseudo-terminal of the given size (80 columns by default)."""
    if sys.platform == "win32":
        return _ConPtySession(argv, cwd=cwd, env=env, cols=cols, rows=rows)
    return _PosixSession(argv, cwd=cwd, env=env, cols=cols, rows=rows)
