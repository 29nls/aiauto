"""Session orchestration: the bounded screenshot -> model -> action loop."""

from __future__ import annotations

import os
import time
import uuid
from typing import Any

from .api import _call_openrouter, get_openrouter_client
from .capture import capture_screen_base64
from .config import (
    MAX_CONTEXT_MESSAGES,
    MAX_STEPS_PER_SESSION,
    MOVE_DURATION,
    EmergencyStop,
    FocusLost,
    log,
)
from .device import DeviceInput, PyDirectInputDevice
from .input_control import execute_game_action
from .messages import (
    assistant_message,
    frame_message,
    tool_calls_wire,
    tool_result,
    user_text,
)
from .safety import _sanitize_log_text, check_emergency_stop


def _compact_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bound history while preserving valid assistant/tool groups and latest frame."""
    if not messages:
        return messages

    instruction = messages[0]
    current_frame = messages[-1]
    history = messages[1:-1]
    turns: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(history):
        message = history[index]
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            index += 1
            continue

        end = index + 1
        while end < len(history) and history[end].get("role") == "tool":
            end += 1
        turns.append(history[index:end])
        index = end

    budget = MAX_CONTEXT_MESSAGES - 2
    selected: list[list[dict[str, Any]]] = []
    for turn in reversed(turns):
        if len(turn) > budget:
            # Do not fall back to older context when the newest complete turn
            # cannot fit; stale action history is less useful than no history.
            break
        selected.insert(0, turn)
        budget -= len(turn)

    compacted = [instruction]
    for turn in selected:
        compacted.extend(turn)
    compacted.append(current_frame)
    return compacted[-MAX_CONTEXT_MESSAGES:]


def _new_session_id() -> str:
    """Short, log-safe session identifier. Not a secret."""
    return f"{time.strftime('%Y%m%d-%H%M%S')}-{uuid.uuid4().hex[:6]}"


def run_dn_bot(
    instruction: str,
    max_steps: int = MAX_STEPS_PER_SESSION,
    device: DeviceInput = PyDirectInputDevice(),
) -> None:
    """Run a bounded screenshot -> OpenRouter -> validated action loop.

    ``device`` is the input seam, defaulting to the production adapter so
    non-dry-run behavior is byte-identical; it is threaded through the
    emergency/focus guards and every action so the whole session stays on the
    injected seam. Passing a ``DryRunDevice`` (flag ``--dry-run``) rehearses
    the loop with zero physical input: actions are validated, mapped, and
    logged by the device instead of executed.
    """
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("Instruction harus berupa teks yang tidak kosong.")
    if (
        isinstance(max_steps, bool)
        or not isinstance(max_steps, int)
        or not 1 <= max_steps <= MAX_STEPS_PER_SESSION
    ):
        raise ValueError(
            f"max_steps harus berupa integer antara 1 dan {MAX_STEPS_PER_SESSION}."
        )

    model = os.getenv("OPENROUTER_MODEL", "").strip()
    if not model:
        raise RuntimeError(
            "OPENROUTER_MODEL belum diatur. Pilih model OpenRouter yang "
            "mendukung vision dan tool calling."
        )

    session_id = _new_session_id()
    log.info("Sesi %s dimulai (maks %s langkah)", session_id, max_steps)
    client = get_openrouter_client()
    frame = capture_screen_base64()
    messages: list[dict[str, Any]] = [
        user_text(instruction),
        frame_message(frame.encoded, "Current screenshot."),
    ]

    for step in range(1, max_steps + 1):
        step_started = time.monotonic()
        check_emergency_stop(device)
        log.info("Langkah %s/%s (session=%s)", step, max_steps, session_id)
        messages = _compact_messages(messages)

        try:
            reply = _call_openrouter(client, model, messages)
        except RuntimeError as error:
            # The chained cause is suppressed in _call_openrouter (`from None`)
            # so verbose SDK details never reach this log (F-06); the message
            # carries the actionable classification plus a bounded detail.
            log.exception(
                "OpenRouter API gagal; sesi dihentikan tanpa aksi tambahan: %s",
                error,
            )
            log.info(
                "Langkah %s selesai dalam %.1f s",
                step,
                time.monotonic() - step_started,
            )
            return
        except (IndexError, AttributeError, TypeError, ValueError):
            log.exception("Respons model tidak valid; sesi dihentikan tanpa aksi tambahan.")
            log.info(
                "Langkah %s selesai dalam %.1f s",
                step,
                time.monotonic() - step_started,
            )
            return

        # Wire-shape history: assistant message + tool-calls are built via the
        # contract module (messages.py), never as raw dicts.
        messages.append(
            assistant_message(reply.text, tool_calls_wire(reply.tool_requests))
        )

        if not reply.tool_requests:
            log.info("Model tidak meminta aksi lagi; sesi selesai.")
            log.info(
                "Langkah %s selesai dalam %.1f s",
                step,
                time.monotonic() - step_started,
            )
            return

        for index, request in enumerate(reply.tool_requests):
            if index > 0:
                result = "Aksi ditolak: hanya satu aksi per screenshot yang diizinkan."
                log.warning(result)
            else:
                action = request.input.get("action")
                try:
                    execute_game_action(
                        action=action,
                        coordinate=request.input.get("coordinate"),
                        text=request.input.get("text"),
                        duration=request.input.get("duration", MOVE_DURATION),
                        frame=frame,
                        device=device,
                    )
                    result = f"Aksi {action!r} berhasil dijalankan."
                    log.info("Aksi: %s", action)
                except (EmergencyStop, FocusLost):
                    raise
                except Exception as error:
                    log.exception("Aksi gagal; sesi dihentikan tanpa aksi tambahan.")
                    # `action` adalah input model (tak tepercaya): sanitasi sebelum
                    # masuk pesan error agar tidak terjadi log injection (pola F-05).
                    raise RuntimeError(
                        f"Aksi {_sanitize_log_text(str(action))!r} gagal: {error}"
                    ) from error

            messages.append(tool_result(request.id, result))

        # A fresh screenshot is a separate user message after the tool results.
        # This avoids asking the model to act on a stale frame.
        frame = capture_screen_base64()
        messages.append(
            frame_message(frame.encoded, "Current screenshot after the action.")
        )
        messages = _compact_messages(messages)
        log.info(
            "Langkah %s selesai dalam %.1f s",
            step,
            time.monotonic() - step_started,
        )

    log.warning("Sesi berhenti karena mencapai batas langkah.")
