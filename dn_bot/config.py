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
# Official OpenAI endpoint. The client uses the SDK default directly; the
# constant remains useful to callers that need to display the selected service.
OPENAI_BASE_URL = "https://api.openai.com/v1"
# Deprecated compatibility name. It no longer selects or enables OpenRouter.
OPENROUTER_BASE_URL = OPENAI_BASE_URL
API_MAX_ATTEMPTS = 3
API_RETRY_BASE_DELAY = 1.5
API_ERROR_DETAIL_MAX = 500
# Default seconds before an OpenAI request is aborted (env OPENAI_TIMEOUT).
# Bounded so a hung request cannot hold the session for the SDK default (~600 s)
# times API_MAX_ATTEMPTS without any emergency responsiveness in between.
OPENAI_TIMEOUT_DEFAULT = 60
# Default session goal, used when neither the CLI flag (--instruction) nor the
# DN_INSTRUCTION env var is provided. Byte-identical to the pre-T3 hardcoded
# text so no-args behavior is unchanged.
DEFAULT_INSTRUCTION = (
    "Amati screenshot. Jika ada NPC yang jelas terlihat dan aman untuk "
    "didekati, dekati secara perlahan lalu gunakan F untuk interaksi. "
    "Jika tujuan tidak jelas, jangan melakukan aksi."
)
# Cheap shape guard for the OpenAI key in preflight. Deliberately conservative:
# it catches clearly invalid values, while authentication remains the provider's
# responsibility.
OPENAI_KEY_PREFIX = "sk-"
OPENAI_KEY_MIN_LENGTH = 40
# Optional Minotaur retreat destination. None preserves the legacy behavior
# (both visible labels accepted); an explicit value makes the destination strict.
RETREAT_DESTINATION_ENV = "DN_RETREAT_DESTINATION"
RETREAT_DESTINATIONS = ("stage_entrance", "town")
_UNSET = object()

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
    "f12",
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


def _is_plausible_openai_key(value: str) -> bool:
    """Cheap shape check for an OpenAI project or user key.

    Authentication remains the provider's responsibility. This only catches
    clearly invalid values so preflight can fail before the countdown.
    """
    return (
        value.startswith(OPENAI_KEY_PREFIX)
        and not value.startswith("sk-or-v1-")
        and len(value) >= OPENAI_KEY_MIN_LENGTH
    )


def validate_retreat_destination(value: object | None) -> str | None:
    """Validate one operator retreat destination, preserving only an unset value."""
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(
            f"{RETREAT_DESTINATION_ENV} harus berupa salah satu: "
            "stage_entrance atau town."
        ) from None
    normalized = value.strip().casefold()
    if normalized not in RETREAT_DESTINATIONS:
        raise ValueError(
            f"{RETREAT_DESTINATION_ENV} harus berupa salah satu: "
            "stage_entrance atau town."
        ) from None
    return normalized


def resolve_retreat_destination(cli_value: str | None = None) -> str | None:
    """Resolve CLI over env, or return None for the legacy both-label mode."""
    if cli_value is not None:
        return validate_retreat_destination(cli_value)
    return validate_retreat_destination(os.getenv(RETREAT_DESTINATION_ENV))


def _request_timeout() -> int:
    """Seconds before an OpenAI request is aborted (env OPENAI_TIMEOUT).

    Defaults to ``OPENAI_TIMEOUT_DEFAULT`` (60 s). Fails fast with a clear
    message on non-integer or non-positive values, mirroring the ``_int_env``
    parsing pattern.

    Parsing happens at client construction (``get_openai_client``), not in
    preflight: preflight is intentionally unchanged, and a malformed value
    still surfaces at session start before the first request.

    Raises:
        ValueError: If the configured value is not a positive integer.
    """
    timeout = _int_env("OPENAI_TIMEOUT", str(OPENAI_TIMEOUT_DEFAULT))
    if timeout <= 0:
        raise ValueError(
            "OPENAI_TIMEOUT harus berupa bilangan bulat positif (detik)."
        ) from None
    return timeout


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


def preflight_configuration(retreat_destination: object = _UNSET) -> None:
    """Validate startup configuration before the countdown delay.

    ``retreat_destination`` is the already-resolved CLI value when provided.
    The sentinel preserves the direct-call behavior of reading the environment.

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
    api_key = os.getenv("OPENAI_API_KEY", "").strip()
    if not api_key:
        raise RuntimeError(
            "OPENAI_API_KEY belum diatur. Copy .env.example menjadi .env "
            "dan isi API key secara lokal."
        )
    if not _is_plausible_openai_key(api_key):
        raise RuntimeError(
            "OPENAI_API_KEY tampak tidak valid: harus diawali 'sk-' "
            "dengan panjang minimal yang wajar. Isi API key OpenAI asli di "
            ".env — jangan memakai placeholder dari .env.example."
        )
    if not os.getenv("OPENAI_MODEL", "").strip():
        raise RuntimeError(
            "OPENAI_MODEL belum diatur. Pilih model OpenAI yang "
            "mendukung vision dan tool calling."
        )
    if not os.getenv("DN_WINDOW_TITLE", "").strip():
        raise RuntimeError(
            "DN_WINDOW_TITLE wajib diisi agar input tidak terkirim ke "
            "aplikasi lain."
        )
    _validate_capture_env()
    if retreat_destination is _UNSET:
        validate_retreat_destination(os.getenv(RETREAT_DESTINATION_ENV))
    else:
        validate_retreat_destination(retreat_destination)
