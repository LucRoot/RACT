"""What this machine has, for first-run setup (B-015).

LR:: Setup recommends a local model size from memory, so it needs total
and available RAM on Windows, Linux and macOS without adding a dependency.
Standard library and ctypes only. Every value that cannot be read is None,
and the recommendation treats unknown memory conservatively.
"""

from __future__ import annotations

import os
import platform
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from ract import programs
from ract.git_run import run_git

GB = 1024**3


@dataclass(frozen=True)
class HostProfile:
    platform: str
    arch: str
    python_version: str
    cpu_logical: int | None
    total_ram_bytes: int | None
    available_ram_bytes: int | None
    free_disk_bytes: int | None
    git_version: str | None
    gpu_hint: str | None


def _windows_memory() -> tuple[int | None, int | None]:
    import ctypes
    from ctypes import wintypes

    class MEMORYSTATUSEX(ctypes.Structure):
        _fields_ = [
            ("dwLength", wintypes.DWORD),
            ("dwMemoryLoad", wintypes.DWORD),
            ("ullTotalPhys", ctypes.c_ulonglong),
            ("ullAvailPhys", ctypes.c_ulonglong),
            ("ullTotalPageFile", ctypes.c_ulonglong),
            ("ullAvailPageFile", ctypes.c_ulonglong),
            ("ullTotalVirtual", ctypes.c_ulonglong),
            ("ullAvailVirtual", ctypes.c_ulonglong),
            ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
        ]

    status = MEMORYSTATUSEX()
    status.dwLength = ctypes.sizeof(MEMORYSTATUSEX)
    windll = getattr(ctypes, "windll", None)
    if windll is None or not windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status)):
        return None, None
    return int(status.ullTotalPhys), int(status.ullAvailPhys)


def _linux_memory() -> tuple[int | None, int | None]:
    values: dict[str, int] = {}
    for line in Path("/proc/meminfo").read_text(encoding="utf-8").splitlines():
        m = re.match(r"(\w+):\s+(\d+) kB", line)
        if m:
            values[m.group(1)] = int(m.group(2)) * 1024
    return values.get("MemTotal"), values.get("MemAvailable")


def _macos_memory() -> tuple[int | None, int | None]:
    total_out = subprocess.run(
        ["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=5
    )
    total = int(total_out.stdout.strip()) if total_out.returncode == 0 else None
    vm = subprocess.run(["vm_stat"], capture_output=True, text=True, timeout=5)
    available = None
    if vm.returncode == 0:
        size = re.search(r"page size of (\d+) bytes", vm.stdout)
        pages = {
            k: int(v)
            for k, v in re.findall(
                r'"?Pages (free|inactive|speculative)"?:\s+(\d+)', vm.stdout
            )
        }
        if size and pages:
            available = sum(pages.values()) * int(size.group(1))
    return total, available


def memory() -> tuple[int | None, int | None]:
    """Total and available physical memory in bytes; None when unreadable."""
    try:
        if sys.platform == "win32":
            return _windows_memory()
        if sys.platform == "darwin":
            return _macos_memory()
        return _linux_memory()
    except (OSError, ValueError, subprocess.SubprocessError) as exc:
        print(f"note: could not read memory size: {exc}", file=sys.stderr)
        return None, None


def _git_version() -> str | None:
    if programs.git() == "git":  # B-214: not on PATH (the current folder is not searched)
        return None
    try:
        out = run_git("--version", capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return None
    m = re.search(r"(\d+\.\d+(?:\.\d+)?)", out.stdout)
    return m.group(1) if m else None


def _gpu_hint() -> str | None:
    """A hint only; it never changes the recommendation."""
    if shutil.which("nvidia-smi"):
        return "NVIDIA GPU"
    if sys.platform == "darwin" and platform.machine() == "arm64":
        return "Apple silicon (unified memory)"
    if shutil.which("rocminfo"):
        return "AMD GPU"
    return None


def probe_host(directory: Path | None = None) -> HostProfile:
    """Read this machine's profile. Nothing here touches the network."""
    total, available = memory()
    try:
        free = shutil.disk_usage(directory or Path.cwd()).free
    except OSError:
        free = None
    return HostProfile(
        platform=platform.system() or "unknown",
        arch=platform.machine() or "unknown",
        python_version=platform.python_version(),
        cpu_logical=os.cpu_count(),
        total_ram_bytes=total,
        available_ram_bytes=available,
        free_disk_bytes=free,
        git_version=_git_version(),
        gpu_hint=_gpu_hint(),
    )


def _gb(value: int | None) -> str:
    return "unknown" if value is None else f"{value / GB:.1f} GB"


def describe(profile: HostProfile) -> list[str]:
    """Plain lines for the machine check."""
    return [
        f"Python {profile.python_version} on {profile.platform} {profile.arch}",
        f"git {profile.git_version}" if profile.git_version else "git: not found",
        f"memory: {_gb(profile.total_ram_bytes)} total, "
        f"{_gb(profile.available_ram_bytes)} available",
        f"CPU cores: {profile.cpu_logical or 'unknown'}",
        f"free disk here: {_gb(profile.free_disk_bytes)}",
        f"GPU: {profile.gpu_hint or 'none detected'}",
    ]


__all__ = ["GB", "HostProfile", "describe", "memory", "probe_host"]
