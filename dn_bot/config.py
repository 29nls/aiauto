"""Configuration, constants, core types, and startup preflight for dn_bot.

This module has no internal dependencies, so every other module may import
from it without creating import cycles.
"""

from __future__ import annotations

import logging
import os
import sys
from dataclasses import dataclass
from typing import Optional

from dotenv import load_dotenv

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("DN-Bot")

TARGET_WIDTH = 1024
TARGET_HEIGHT = 768
MAX_STEPS_PER_SESSION = 10
MAX_CONTEXT_MESSAGES = 8
ACTION_COOLDOWN = 0.15
MOVE_DURATION = 0.3
START_DELAY_SECONDS = 5
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
API_MAX_ATTEMPTS = 3
API_RETRY_BASE_DELAY = 1.5
API_ERROR_DETAIL_MAX = 500

MOVE_KEYS = {"w", "a", "s", "d", "q", "e"}
ACTION_KEYS = {
    "f",
    "space",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "0",
    "shift",
}


class EmergencyStop(RuntimeError):
    """Raised when the user activates the mouse-corner emergency stop."""


class FocusLost(RuntimeError):
    """Raised when the target-window check fails."""


@dataclass(frozen=True)
class CaptureGeometry:
    """Letterbox geometry needed to reverse-map model coordinates."""

    left: int
    top: int
    width: int
    height: int
    content_width: int
    content_height: int
    offset_x: int
    offset_y: int


def _int_env(name: str, default: Optional[str] = None) -> Optional[int]:
    """Parse an integer env var, failing fast with a clear message.

    Raises:
        ValueError: If the configured value is not an integer.
    """
    raw = os.getenv(name, default)
    if raw is None:
        return None
    try:
        return int(raw)
    except (TypeError, ValueError):
        raise ValueError(
            f"{name} harus berupa bilangan bulat, bukan {raw!r}."
        ) from None


def _validate_capture_env() -> None:
    """Validate capture-related env vars without touching the screen.

    Raises:
        ValueError: If the capture configuration is incomplete or invalid.
    """
    names = (
        "DN_CAPTURE_LEFT",
        "DN_CAPTURE_TOP",
        "DN_CAPTURE_WIDTH",
        "DN_CAPTURE_HEIGHT",
    )
    configured = [os.getenv(name) for name in names]
    if any(value is not None for value in configured):
        if not all(value is not None for value in configured):
            raise ValueError(
                "DN_CAPTURE_LEFT/TOP/WIDTH/HEIGHT harus diisi semuanya."
            )
        for name in names:
            _int_env(name)
        width = _int_env("DN_CAPTURE_WIDTH")
        height = _int_env("DN_CAPTURE_HEIGHT")
        if width < 2 or height < 2:
            raise ValueError("DN_CAPTURE_WIDTH/HEIGHT harus minimal 2.")
        return

    monitor_index = _int_env("DN_MONITOR", "1")
    if monitor_index < 1:
        raise ValueError("DN_MONITOR harus berupa bilangan bulat >= 1.")


def preflight_configuration() -> None:
    """Validate startup configuration before the countdown delay.

    Runs before the 5-second countdown so misconfiguration fails fast with a
    clear message instead of after the delay. Raises on the first problem:

    Raises:
        RuntimeError: Platform not supported or a required env var is missing.
        ValueError: Capture configuration is present but malformed.
    """
    if os.name != "nt":
        raise RuntimeError(
            "Script ini hanya mendukung Windows: cek fokus jendela dan input "
            "fisik bergantung pada API Windows. Jalankan pada Windows 10/11."
        )
    if not os.getenv("OPENROUTER_API_KEY", "").strip():
        raise RuntimeError(
            "OPENROUTER_API_KEY belum diatur. Copy .env.example menjadi .env "
            "dan isi API key secara lokal."
        )
    if not os.getenv("OPENROUTER_MODEL", "").strip():
        raise RuntimeError(
            "OPENROUTER_MODEL belum diatur. Pilih model OpenRouter yang "
            "mendukung vision dan tool calling."
        )
    if not os.getenv("DN_WINDOW_TITLE", "").strip():
        raise RuntimeError(
            "DN_WINDOW_TITLE wajib diisi agar input tidak terkirim ke "
            "aplikasi lain."
        )
    _validate_capture_env()
