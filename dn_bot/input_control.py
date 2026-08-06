"""Validated physical input actions via PyDirectInput."""

from __future__ import annotations

import math
from typing import Optional, Sequence, Any

import pydirectinput

from .capture import Frame, _physical_point
from .config import (
    ACTION_COOLDOWN,
    ACTION_KEYS,
    MOVE_DURATION,
    MOVE_KEYS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
)
from .safety import _safe_sleep, check_emergency_stop, check_target_window


def _validate_key(text: Optional[str], allowed: set[str]) -> str:
    if not isinstance(text, str) or text.lower() not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"Tombol tidak diizinkan. Pilihan: {allowed_text}")
    return text.lower()


def _press_key(key: str, duration: float) -> None:
    """Always release a key, including when the action is interrupted."""
    pydirectinput.keyDown(key)
    try:
        _safe_sleep(duration)
    finally:
        pydirectinput.keyUp(key)


def execute_game_action(
    action: str,
    coordinate: Optional[Sequence[Any]] = None,
    text: Optional[str] = None,
    duration: float = MOVE_DURATION,
    *,
    frame: Frame,
) -> None:
    """Execute one validated action from the model's custom tool.

    ``frame`` is the immutable snapshot the model observed; coordinate-based
    actions map against exactly this frame (deterministic, no hidden state).
    """
    check_emergency_stop()
    check_target_window()
    try:
        duration = float(duration)
    except (TypeError, ValueError) as error:
        raise ValueError("duration harus berupa angka antara 0.05 dan 2.0.") from error
    if not math.isfinite(duration):
        raise ValueError("duration harus berupa angka antara 0.05 dan 2.0.")
    duration = max(0.05, min(duration, 2.0))

    if action == "mouse_move":
        if coordinate is None:
            raise ValueError("mouse_move membutuhkan coordinate.")
        pydirectinput.moveTo(*_physical_point(coordinate, frame))
    elif action in {"left_click", "right_click"}:
        if coordinate is None:
            raise ValueError(f"{action} membutuhkan coordinate.")
        pydirectinput.moveTo(*_physical_point(coordinate, frame))
        if action == "left_click":
            pydirectinput.click()
        else:
            pydirectinput.rightClick()
    elif action == "press_move_key":
        _press_key(_validate_key(text, MOVE_KEYS), duration)
    elif action == "press_action_key":
        _press_key(_validate_key(text, ACTION_KEYS), min(duration, 1.0))
    elif action == "move_camera":
        if coordinate is None:
            raise ValueError("move_camera membutuhkan coordinate.")
        target_x, target_y = _physical_point(coordinate, frame)
        center_x, center_y = _physical_point((TARGET_WIDTH // 2, TARGET_HEIGHT // 2), frame)
        # Anchor every camera move at the screenshot center so the action does
        # not depend on the cursor's previous position or accumulate drift.
        pydirectinput.moveTo(center_x, center_y)
        pydirectinput.moveTo(target_x, target_y)
    elif action == "wait":
        _safe_sleep(duration)
    else:
        raise ValueError(f"Aksi tidak diizinkan: {action}")

    _safe_sleep(ACTION_COOLDOWN)
