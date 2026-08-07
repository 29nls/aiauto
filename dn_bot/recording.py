"""Opt-in, secret-free recording for Minotaur replay traces."""

from __future__ import annotations

import json
import math
import os
import tempfile
from pathlib import Path
from typing import Any, Mapping

from .config import (
    MOVE_DURATION,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    validate_retreat_destination,
)
from .device import DeviceInput
from .farm import FarmObservationClaim, FarmState
from .replay import (
    ReplayDeviceCall,
    ReplayExpected,
    ReplayResult,
    ReplayStep,
    ReplayTrace,
    _SAFE_TEXT_VALUES,
)


class TraceRecordingError(RuntimeError):
    """Raised when an opt-in trace cannot be validated or written."""


def load_trace_path(path: str | Path) -> Path:
    """Validate a trace destination before a session starts."""
    target = Path(path)
    if not target.name:
        raise TraceRecordingError("Path trace harus berupa nama file.")
    if not target.parent.is_dir():
        raise TraceRecordingError(
            "Folder tujuan trace tidak ditemukan; buat folder tersebut terlebih dahulu."
        )
    if target.exists() and target.is_dir():
        raise TraceRecordingError("Path trace harus menunjuk ke file, bukan folder.")
    return target


class TraceRecordingDevice:
    """Delegate DeviceInput calls while recording successful action primitives."""

    def __init__(self, delegate: DeviceInput) -> None:
        self.delegate = delegate
        self.action_calls: tuple[ReplayDeviceCall, ...] = ()
        self.action_failed = False

    def begin_action(self) -> None:
        self.action_calls = ()
        self.action_failed = False

    def position(self) -> tuple[int, int]:
        # Position is a safety observation, never a replay action.
        try:
            return self.delegate.position()
        except Exception:
            self.action_failed = True
            raise

    def moveTo(self, x: int, y: int) -> None:
        self._call("moveTo", (x, y), self.delegate.moveTo, x, y)

    def keyDown(self, key: str) -> None:
        self._call("keyDown", (key,), self.delegate.keyDown, key)

    def keyUp(self, key: str) -> None:
        self._call("keyUp", (key,), self.delegate.keyUp, key)

    def click(self) -> None:
        self._call("click", (), self.delegate.click)

    def rightClick(self) -> None:
        self._call("rightClick", (), self.delegate.rightClick)

    def _call(self, method: str, args: tuple[Any, ...], callback, *callback_args) -> None:
        try:
            callback(*callback_args)
        except Exception:
            self.action_failed = True
            raise
        self.action_calls += (ReplayDeviceCall(method, args),)


class TraceRecorder:
    """Build and atomically flush a sanitized version 1 replay trace."""

    def __init__(self, path: str | Path, *, retreat_destination: str | None) -> None:
        self.path = load_trace_path(path)
        try:
            self.retreat_destination = validate_retreat_destination(retreat_destination)
        except ValueError as error:
            raise TraceRecordingError(str(error)) from None
        self._steps: list[ReplayStep] = []
        self._next_frame = 1

    def record_step(
        self,
        *,
        claim: FarmObservationClaim,
        action: Mapping[str, Any],
        state_before: FarmState,
        state_after: FarmState,
        device_calls: tuple[ReplayDeviceCall, ...] = (),
        result: ReplayResult,
    ) -> None:
        if not isinstance(claim, FarmObservationClaim):
            raise TraceRecordingError("Trace claim tidak sesuai schema.")
        if not isinstance(state_before, FarmState) or not isinstance(state_after, FarmState):
            raise TraceRecordingError("Trace state tidak sesuai schema.")
        safe_claim = self._claim_to_wire(claim)
        safe_action = self._action_to_wire(action)
        self._validate_action_requirements(safe_action)
        expected = ReplayExpected(
            state_before=state_before,
            state_after=state_after,
            device_calls=tuple(device_calls),
            result=result,
        )
        step = ReplayStep(
            f"frame_{self._next_frame:06d}",
            safe_claim,
            safe_action,
            expected,
        )
        self._steps.append(step)
        self._next_frame += 1

    def flush(self) -> None:
        """Atomically replace the target with the current valid trace."""
        if not self._steps:
            return
        trace = ReplayTrace(tuple(self._steps), self.retreat_destination)
        payload = json.dumps(
            trace.to_dict(),
            ensure_ascii=True,
            indent=2,
            sort_keys=True,
        )
        temporary: Path | None = None
        fd: int | None = None
        try:
            fd, temporary_name = tempfile.mkstemp(
                prefix=f".{self.path.name}.",
                suffix=".tmp",
                dir=self.path.parent,
                text=True,
            )
            temporary = Path(temporary_name)
            stream = os.fdopen(fd, "w", encoding="utf-8", newline="\n")
            fd = None  # ``stream`` owns the descriptor from here.
            with stream:
                stream.write(payload)
                stream.write("\n")
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temporary, self.path)
            temporary = None
        except (OSError, TypeError, ValueError) as error:
            raise TraceRecordingError(f"Trace gagal ditulis secara atomic: {error}") from None
        finally:
            if fd is not None:
                try:
                    os.close(fd)
                except OSError:
                    pass
            if temporary is not None:
                try:
                    temporary.unlink()
                except FileNotFoundError:
                    pass
                except OSError:
                    pass

    @staticmethod
    def _claim_to_wire(claim: FarmObservationClaim) -> dict[str, Any]:
        result: dict[str, Any] = {"farm_state": claim.claimed_state.value}
        token = _safe_token(claim.text)
        if token is not None:
            result["text"] = token
        coordinate = _safe_coordinate(claim.coordinate)
        if coordinate is not None:
            result["coordinate"] = coordinate
        return result

    @staticmethod
    def _validate_action_requirements(action: Mapping[str, Any]) -> None:
        action_name = action["action"]
        if action_name in {"mouse_move", "left_click", "right_click", "move_camera"}:
            if "coordinate" not in action:
                raise TraceRecordingError(
                    "Trace action berbasis koordinat kehilangan coordinate valid."
                )
        if action_name in {"press_move_key", "press_action_key"}:
            if "text" not in action:
                raise TraceRecordingError(
                    "Trace aksi tombol kehilangan text yang diizinkan."
                )

    @staticmethod
    def _action_to_wire(action: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(action, Mapping) or not isinstance(action.get("action"), str):
            raise TraceRecordingError("Trace action tidak sesuai schema.")
        result: dict[str, Any] = {"action": action["action"]}
        token = _safe_token(action.get("text"))
        if token is not None:
            result["text"] = token
        coordinate = _safe_coordinate(action.get("coordinate"))
        if coordinate is not None:
            result["coordinate"] = coordinate
        duration = action.get("duration", MOVE_DURATION)
        if (
            isinstance(duration, (int, float))
            and not isinstance(duration, bool)
            and math.isfinite(duration)
        ):
            result["duration"] = duration
        else:
            raise TraceRecordingError("Trace duration tidak finite.")
        return result


def _safe_token(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    normalized = " ".join(value.casefold().split())
    return normalized if normalized in _SAFE_TEXT_VALUES else None


def _safe_coordinate(value: Any) -> list[int] | None:
    if not isinstance(value, (list, tuple)) or len(value) != 2:
        return None
    if any(isinstance(part, bool) or not isinstance(part, int) for part in value):
        return None
    if not all(0 <= part < limit for part, limit in zip(value, (TARGET_WIDTH, TARGET_HEIGHT))):
        return None
    return [value[0], value[1]]
