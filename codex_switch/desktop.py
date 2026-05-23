from __future__ import annotations

import os
import platform
import shutil
import subprocess
import time
from pathlib import Path
from typing import Callable, Mapping, Optional

from .store import CodexSwitchError


def restart_codex_desktop(
    *,
    system: Optional[str] = None,
    runner: Callable[..., subprocess.CompletedProcess] = subprocess.run,
    popener: Callable[..., subprocess.Popen] = subprocess.Popen,
    sleeper: Callable[[float], None] = time.sleep,
    environ: Optional[Mapping[str, str]] = None,
) -> str:
    current_system = system or platform.system()
    env = environ or os.environ
    if current_system == "Darwin":
        return _restart_macos(runner=runner, sleeper=sleeper)
    if current_system == "Windows":
        return _restart_windows(runner=runner, popener=popener, sleeper=sleeper, environ=env)
    raise CodexSwitchError(f"restart-desktop is not supported on {current_system}")


def _restart_macos(
    *,
    runner: Callable[..., subprocess.CompletedProcess],
    sleeper: Callable[[float], None],
) -> str:
    runner(
        ["osascript", "-e", 'tell application "Codex" to quit'],
        check=False,
        capture_output=True,
        text=True,
    )
    sleeper(1.5)
    _kill_macos_codex_processes(runner)
    sleeper(0.5)
    open_result = runner(
        ["open", "-a", "Codex"],
        check=False,
        capture_output=True,
        text=True,
    )
    if open_result.returncode != 0:
        detail = (open_result.stderr or open_result.stdout or "unknown error").strip()
        raise CodexSwitchError(f"failed to reopen Codex Desktop: {detail}")
    return "restarted Codex Desktop"


def _kill_macos_codex_processes(runner: Callable[..., subprocess.CompletedProcess]) -> None:
    runner(["pkill", "-x", "Codex"], check=False, capture_output=True, text=True)
    for pattern in (
        "/Applications/Codex.app/Contents/Frameworks/Codex Helper",
        "/Applications/Codex.app/Contents/Resources/codex app-server",
        "/Applications/Codex.app/Contents/Resources/node_repl",
        "/Applications/Codex.app/Contents/Resources/native/bare-modifier-monitor",
    ):
        runner(["pkill", "-f", pattern], check=False, capture_output=True, text=True)


def _restart_windows(
    *,
    runner: Callable[..., subprocess.CompletedProcess],
    popener: Callable[..., subprocess.Popen],
    sleeper: Callable[[float], None],
    environ: Mapping[str, str],
) -> str:
    runner(
        ["taskkill", "/IM", "Codex.exe", "/F", "/T"],
        check=False,
        capture_output=True,
        text=True,
    )
    sleeper(1.5)

    for candidate in _windows_codex_candidates(environ):
        if candidate.exists():
            popener([str(candidate)], close_fds=True)
            return "restarted Codex Desktop"

    codex_exe = shutil.which("Codex.exe")
    if codex_exe:
        popener([codex_exe], close_fds=True)
        return "restarted Codex Desktop"

    try:
        popener(["cmd", "/c", "start", "", "Codex"], close_fds=True)
    except OSError as exc:
        raise CodexSwitchError(f"failed to reopen Codex Desktop: {exc}") from exc
    return "restarted Codex Desktop"


def _windows_codex_candidates(environ: Mapping[str, str]) -> list[Path]:
    local_app_data = environ.get("LOCALAPPDATA")
    program_files = environ.get("ProgramFiles")
    program_files_x86 = environ.get("ProgramFiles(x86)")
    candidates = []
    if local_app_data:
        local = Path(local_app_data)
        candidates.extend(
            [
                local / "Programs" / "Codex" / "Codex.exe",
                local / "Codex" / "Codex.exe",
            ]
        )
    if program_files:
        candidates.append(Path(program_files) / "Codex" / "Codex.exe")
    if program_files_x86:
        candidates.append(Path(program_files_x86) / "Codex" / "Codex.exe")
    return candidates
