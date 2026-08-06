"""Safety guards: emergency stop, window focus, and responsive sleep.

This module depends only on ``dn_bot.config`` so capture and input modules can
use it without import cycles.
"""

from __future__ import annotations

import os
import re
import time

import pydirectinput

from .config import EmergencyStop, FocusLost

# PyDirectInput's failsafe is an emergency mechanism, not an anti-cheat feature.
pydirectinput.FAILSAFE = True
pydirectinput.PAUSE = 0.03


def check_emergency_stop() -> None:
    """Stop before another action if the cursor is in the failsafe corner."""
    try:
        x, y = pydirectinput.position()
    except Exception as error:
        raise EmergencyStop("Tidak dapat memeriksa posisi cursor; sesi dihentikan.") from error
    if 0 <= x <= 5 and 0 <= y <= 5:
        raise EmergencyStop("Cursor berada di pojok kiri atas.")


_ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\x80-\x9f]")


def _sanitize_log_text(text: str) -> str:
    """Strip control characters (incl. ANSI CSI escape sequences) from text
    that will be embedded in log messages, preventing terminal log injection
    via untrusted values such as window titles."""
    text = _ANSI_CSI_RE.sub("", text)
    return _CONTROL_RE.sub("", text)


def check_target_window() -> None:
    """Require the configured Dragon Nest window to have focus on Windows.

    Fail-closed: on non-Windows platforms the window-focus guard cannot work,
    so the session is refused instead of silently proceeding without the safety
    check (README states this project is Windows-only).
    """
    if os.name != "nt":
        raise FocusLost(
            "Script ini hanya mendukung Windows: cek fokus jendela tidak dapat "
            "berjalan pada platform ini, sehingga sesi ditolak (fail-closed). "
            "Jalankan pada Windows 10/11."
        )
    expected = os.getenv("DN_WINDOW_TITLE", "").strip()
    if not expected:
        raise FocusLost(
            "DN_WINDOW_TITLE wajib diisi agar input tidak terkirim ke aplikasi lain."
        )

    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    title_buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title_buffer, length + 1)
    active_title = _sanitize_log_text(title_buffer.value)
    if expected.casefold() not in active_title.casefold():
        raise FocusLost(
            f"Jendela aktif bukan target DN_WINDOW_TITLE={expected!r} "
            f"(aktif: {active_title!r})."
        )


def _safe_sleep(seconds: float) -> None:
    """Sleep in short intervals so emergency/focus checks remain responsive."""
    deadline = time.monotonic() + seconds
    while True:
        check_emergency_stop()
        check_target_window()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.05, remaining))
