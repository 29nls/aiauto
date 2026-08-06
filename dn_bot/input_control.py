"""Validated physical input actions via the input device seam."""

from __future__ import annotations

import math
from typing import Optional, Sequence, Any

from .capture import Frame, _physical_point
from .config import (
    ACTION_COOLDOWN,
    ACTION_KEYS,
    MOVE_DURATION,
    MOVE_KEYS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
)
from .device import DeviceInput, PyDirectInputDevice
from .safety import _safe_sleep, _sanitize_log_text, check_emergency_stop, check_target_window


def _validate_key(text: Optional[str], allowed: set[str]) -> str:
    if not isinstance(text, str) or text.lower() not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"Tombol tidak diizinkan. Pilihan: {allowed_text}")
    return text.lower()


def _press_key(key: str, duration: float, device: DeviceInput) -> None:
    """Always release a key, including when the action is interrupted."""
    device.keyDown(key)
    try:
        _safe_sleep(duration, device=device)
    finally:
        device.keyUp(key)


def execute_game_action(
    action: str,
    coordinate: Optional[Sequence[Any]] = None,
    text: Optional[str] = None,
    duration: float = MOVE_DURATION,
    *,
    frame: Frame,
    device: DeviceInput = PyDirectInputDevice(),
) -> None:
    """Execute one validated action from the model's custom tool.

    ``frame`` is the immutable snapshot the model observed; coordinate-based
    actions map against exactly this frame (deterministic, no hidden state).
    ``device`` is the input seam — defaulting to the production adapter — so
    tests can inject a recorder and assert the exact input sequence. The same
    device is threaded through the emergency/focus guards so the whole action
    path stays on the injected seam.
    """
    check_emergency_stop(device)
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
        device.moveTo(*_physical_point(coordinate, frame))
    elif action in {"left_click", "right_click"}:
        if coordinate is None:
            raise ValueError(f"{action} membutuhkan coordinate.")
        device.moveTo(*_physical_point(coordinate, frame))
        if action == "left_click":
            device.click()
        else:
            device.rightClick()
    elif action == "press_move_key":
        _press_key(_validate_key(text, MOVE_KEYS), duration, device)
    elif action == "press_action_key":
        _press_key(_validate_key(text, ACTION_KEYS), min(duration, 1.0), device)
    elif action == "move_camera":
        if coordinate is None:
            raise ValueError("move_camera membutuhkan coordinate.")
        target_x, target_y = _physical_point(coordinate, frame)
        center_x, center_y = _physical_point((TARGET_WIDTH // 2, TARGET_HEIGHT // 2), frame)
        # Anchor every camera move at the screenshot center so the action does
        # not depend on the cursor's previous position or accumulate drift.
        device.moveTo(center_x, center_y)
        device.moveTo(target_x, target_y)
    elif action == "wait":
        _safe_sleep(duration, device=device)
    else:
        # `action` adalah input model (tak tepercaya): sanitasi sebelum masuk
        # pesan error agar tidak terjadi terminal log injection via traceback
        # (pola F-05, diterapkan pada nilai dari model seperti window title).
        raise ValueError(f"Aksi tidak diizinkan: {_sanitize_log_text(str(action))}")

    _safe_sleep(ACTION_COOLDOWN, device=device)
