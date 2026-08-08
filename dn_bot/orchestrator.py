"""Session orchestration: the bounded screenshot -> model -> action loop."""

from __future__ import annotations

import os
import time
import uuid
from pathlib import Path
from typing import Any

from .api import MINOTAUR_TOOL, SYSTEM_PROMPT, _call_openai, get_openai_client
from .capture import InvalidCoordinateError, capture_screen_base64
from .config import (
    COORDINATE_MAX_RETRIES_DEFAULT,
    MAX_CONTEXT_MESSAGES,
    MAX_STEPS_PER_SESSION,
    MOVE_DURATION,
    EmergencyStop,
    FocusLost,
    log,
    resolve_coordinate_max_retries,
)
from .device import DeviceInput, PyDirectInputDevice
from .farm import (
    FarmObservationClaim,
    FarmProfile,
    FarmSafetyStop,
    FarmWatchdog,
)
from .input_control import execute_game_action
from .recording import TraceRecorder, TraceRecordingDevice, TraceRecordingError
from .replay import ReplayResult
from .messages import (
    assistant_message,
    frame_message,
    tool_calls_wire,
    tool_result,
    user_text,
)
from .safety import _sanitize_log_text, check_emergency_stop

# The model may propose an action whose coordinate cannot be used: it is
# missing, malformed, outside the 1024x768 frame, inside the letterbox
# padding, or maps onto the failsafe corner. Such an action is never executed;
# the orchestrator reports the failure back to the model as a tool result and
# re-asks for a corrected action, up to this many times per step, before
# aborting fail closed. The budget defaults to 2; an operator can override it
# per session via the DN_COORDINATE_MAX_RETRIES env var (validated in preflight).
MAX_COORDINATE_RETRIES = COORDINATE_MAX_RETRIES_DEFAULT

# Sent for every tool call beyond the first in a single model reply.
_EXTRA_ACTION_REJECTION = "Aksi ditolak: hanya satu aksi per screenshot yang diizinkan."


def _abort_action(action, error: Exception) -> None:
    """Log and surface a fail-closed action failure.

    Shared by every action error path: the session stops with no further
    action. ``action`` is untrusted model input, so it is sanitized before
    entering the error message (pattern F-05, no terminal log injection).
    """
    log.exception("Aksi gagal; sesi dihentikan tanpa aksi tambahan.")
    raise RuntimeError(
        f"Aksi {_sanitize_log_text(str(action))!r} gagal: {error}"
    ) from error


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
    *,
    farm_profile: FarmProfile | None = None,
    until_stopped: bool = False,
    retreat_destination: str | None = None,
    record_trace_path: str | Path | None = None,
) -> None:
    """Run a bounded screenshot -> OpenAI -> validated action loop.

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
    if not isinstance(until_stopped, bool):
        raise ValueError("until_stopped harus berupa boolean.")
    if until_stopped and farm_profile is None:
        raise ValueError("until_stopped membutuhkan farm_profile.")
    if record_trace_path is not None and farm_profile is None:
        raise ValueError("record_trace_path membutuhkan farm_profile minotaur.")

    model = os.getenv("OPENAI_MODEL", "").strip()
    if not model:
        raise RuntimeError(
            "OPENAI_MODEL belum diatur. Pilih model OpenAI yang "
            "mendukung vision dan tool calling."
        )

    # Resolved once per session: the env var cannot change mid-process, and a
    # malformed value fails fast here (and during preflight) with a clear error.
    coordinate_retry_budget = resolve_coordinate_max_retries()
    session_id = _new_session_id()
    recorder = (
        TraceRecorder(record_trace_path, retreat_destination=retreat_destination)
        if record_trace_path is not None
        else None
    )
    active_device = (
        TraceRecordingDevice(device) if recorder is not None else device
    )
    if farm_profile is None:
        watchdog = None
    elif retreat_destination is None:
        watchdog = FarmWatchdog(farm_profile)
    else:
        watchdog = FarmWatchdog(
            farm_profile,
            retreat_destination=retreat_destination,
        )
    mode_instruction = instruction
    frame_caption = "Current screenshot."
    system_prompt = None
    if farm_profile is not None:
        mode_instruction += farm_profile.instruction_suffix
        # FarmProfile contains only the workflow extension; retain the base
        # safety and untrusted-screenshot instructions in every mode.
        system_prompt = SYSTEM_PROMPT + farm_profile.system_prompt
        if retreat_destination is not None:
            system_prompt += (
                "\n\nKonfigurasi operator membatasi tujuan retreat hanya ke "
                f"{retreat_destination.replace('_', ' ').title()}. "
                "Label lain adalah terlarang dan Python akan menolaknya; jangan "
                "usulkan tujuan lain."
            )
        frame_caption = watchdog.caption()
    limit_text = "sampai dihentikan operator" if until_stopped else f"maks {max_steps} langkah"
    log.info("Sesi %s dimulai (%s)", session_id, limit_text)
    client = get_openai_client()
    frame = capture_screen_base64()
    messages: list[dict[str, Any]] = [
        user_text(mode_instruction),
        frame_message(frame.encoded, frame_caption),
    ]

    step = 0
    while until_stopped or step < max_steps:
        step += 1
        step_started = time.monotonic()
        check_emergency_stop(active_device)
        if watchdog is not None:
            watchdog.check()
            frame_caption = watchdog.caption()
        step_limit = "∞" if until_stopped else str(max_steps)
        log.info("Langkah %s/%s (session=%s)", step, step_limit, session_id)
        messages = _compact_messages(messages)

        # A model reply whose action fails coordinate validation (missing,
        # malformed, out of bounds, letterbox padding, or the failsafe corner)
        # is never executed. The failure is reported back to the model as a
        # tool result and the model is re-asked for a corrected action on the
        # same frame, with a bounded retry budget per step (default
        # MAX_COORDINATE_RETRIES, overridable via DN_COORDINATE_MAX_RETRIES).
        # Any other action failure aborts fail closed.
        coordinate_retries = coordinate_retry_budget
        while True:
            try:
                if system_prompt is None:
                    reply = _call_openai(client, model, messages)
                else:
                    reply = _call_openai(
                        client,
                        model,
                        messages,
                        system_prompt=system_prompt,
                        tools=[MINOTAUR_TOOL],
                    )
            except RuntimeError as error:
                if recorder is not None:
                    raise
                # The chained cause is suppressed in _call_openai (`from None`)
                # so verbose SDK details never reach this log (F-06); the message
                # carries the actionable classification plus a bounded detail.
                log.exception(
                    "Provider API gagal; sesi dihentikan tanpa aksi tambahan: %s",
                    error,
                )
                log.info(
                    "Langkah %s selesai dalam %.1f s",
                    step,
                    time.monotonic() - step_started,
                )
                return
            except (IndexError, AttributeError, TypeError, ValueError):
                if recorder is not None:
                    raise
                log.exception(
                    "Respons model tidak valid; sesi dihentikan tanpa aksi tambahan."
                )
                log.info(
                    "Langkah %s selesai dalam %.1f s",
                    step,
                    time.monotonic() - step_started,
                )
                return

            # Wire-shape history: assistant message + tool-calls are built via
            # the contract module (messages.py), never as raw dicts.
            messages.append(
                assistant_message(reply.text, tool_calls_wire(reply.tool_requests))
            )

            if not reply.tool_requests:
                if watchdog is not None:
                    raise FarmSafetyStop(
                        "Model tidak mengirim aksi/state farming; sesi dihentikan aman."
                    )
                log.info("Model tidak meminta aksi lagi; sesi selesai.")
                log.info(
                    "Langkah %s selesai dalam %.1f s",
                    step,
                    time.monotonic() - step_started,
                )
                return

            retry = False
            for index, request in enumerate(reply.tool_requests):
                if index > 0:
                    result = _EXTRA_ACTION_REJECTION
                    log.warning(result)
                    messages.append(tool_result(request.id, result))
                    continue

                action = request.input.get("action")
                state_before = watchdog.state if watchdog is not None else None
                claim = None
                if watchdog is not None:
                    claim = FarmObservationClaim.from_wire(
                        request.input.get("farm_state"),
                        request.input.get("text"),
                        request.input.get("coordinate"),
                    )
                    candidate_state = watchdog.validate_claim(claim, action)
                    watchdog.ensure_action_allowed(candidate_state)
                try:
                    if recorder is not None:
                        active_device.begin_action()
                    execute_game_action(
                        action=action,
                        coordinate=request.input.get("coordinate"),
                        text=request.input.get("text"),
                        duration=request.input.get("duration", MOVE_DURATION),
                        frame=frame,
                        device=active_device,
                    )
                    result = f"Aksi {action!r} berhasil dijalankan."
                    if watchdog is not None:
                        watchdog.advance(candidate_state, action)
                    if recorder is not None:
                        recorder.record_step(
                            claim=claim,
                            action=request.input,
                            state_before=state_before,
                            state_after=watchdog.state,
                            device_calls=active_device.action_calls,
                            result=ReplayResult.SUCCESS,
                        )
                    log.info("Aksi: %s", action)
                except (EmergencyStop, FocusLost, FarmSafetyStop, TraceRecordingError):
                    raise
                except InvalidCoordinateError as error:
                    if coordinate_retries > 0:
                        coordinate_retries -= 1
                        result = f"Koordinat tidak valid: {error}"
                        log.warning(
                            "%s (sisa percobaan: %s)", result, coordinate_retries
                        )
                        # Pop the assistant message with the invalid
                        # function call (appended above) — sending it back
                        # to Gemini in the history triggers a 400
                        # thought_signature requirement. Replace with a
                        # plain user message carrying the same feedback so
                        # the retry call has zero function-call history.
                        messages.pop()
                        g = frame.geometry
                        messages.append(
                            user_text(
                                f"{result} Coba lagi dengan koordinat yang "
                                f"benar dalam rentang {g.offset_x}-"
                                f"{g.offset_x + g.content_width - 1} untuk x "
                                f"dan {g.offset_y}-"
                                f"{g.offset_y + g.content_height - 1} untuk y."
                            )
                        )
                        frame = capture_screen_base64()  # fresh frame for retry
                        messages.append(
                            frame_message(frame.encoded, frame_caption)
                        )
                        retry = True
                        break
                    if recorder is not None and not active_device.action_failed:
                        # Coordinate validation failures never reach the device;
                        # they must not become misleading device_failure entries.
                        raise
                    log.error(
                        "Budget retry koordinat habis "
                        "(DN_COORDINATE_MAX_RETRIES=%s); sesi dihentikan.",
                        coordinate_retry_budget,
                    )
                    _abort_action(action, error)
                except Exception as error:
                    if recorder is not None and not active_device.action_failed:
                        # Validation and other non-device failures must not
                        # become misleading device_failure trace entries.
                        raise
                    if recorder is not None and claim is not None:
                        recorder.record_step(
                            claim=claim,
                            action=request.input,
                            state_before=state_before,
                            state_after=state_before,
                            device_calls=active_device.action_calls,
                            result=ReplayResult.DEVICE_FAILURE,
                        )
                        # A physical device failure is an explicit, replayable
                        # failure outcome. Persist it before surfacing the
                        # original session error; API and policy failures never
                        # flush.
                        recorder.flush()
                    _abort_action(action, error)

                messages.append(tool_result(request.id, result))

            if retry:
                continue
            break

        # A fresh screenshot is a separate user message after the tool results.
        # This avoids asking the model to act on a stale frame.
        frame = capture_screen_base64()
        if watchdog is not None:
            frame_caption = watchdog.caption()
        else:
            frame_caption = "Current screenshot after the action."
        messages.append(frame_message(frame.encoded, frame_caption))
        messages = _compact_messages(messages)
        log.info(
            "Langkah %s selesai dalam %.1f s",
            step,
            time.monotonic() - step_started,
        )

    if recorder is not None:
        recorder.flush()
    if watchdog is not None:
        log.info("Farming berhenti setelah operator/guard menghentikan sesi.")
    else:
        log.warning("Sesi berhenti karena mencapai batas langkah.")
