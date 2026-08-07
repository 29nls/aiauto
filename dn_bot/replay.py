"""Secret-free replay traces for the Minotaur workflow.

A replay contains only opaque frame identities, model claims, action payloads,
and expected outcomes. It never stores screenshots, SDK responses, credentials,
or other session state. Replays use the same FarmObservationClaim,
FarmWatchdog, and execute_game_action paths as the live workflow, while routing
input to an in-memory device and disabling only live focus and sleep I/O.
"""

from __future__ import annotations

import json
import math
import re
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any, Mapping
from unittest.mock import patch

from .capture import Frame, _geometry_for_region
from . import input_control as _input_control
from .config import ACTION_KEYS, EmergencyStop, MOVE_KEYS, validate_retreat_destination
from .farm import (
    FarmObservationClaim,
    FarmProfile,
    FarmState,
    FarmWatchdog,
    MINOTAUR_PROFILE,
)
from .input_control import execute_game_action


TRACE_VERSION = 1
TRACE_PROFILE = "minotaur"
_TRACE_KEYS = {"version", "profile", "retreat_destination", "steps"}
_STEP_KEYS = {"frame_id", "claim", "action", "expected"}
_CLAIM_KEYS = {"farm_state", "text", "coordinate"}
_ACTION_KEYS = {"action", "text", "coordinate", "duration"}
_EXPECTED_KEYS = {"state_before", "state_after", "device_calls", "result"}
_CALL_METHODS = {"moveTo", "keyDown", "keyUp", "click", "rightClick"}
_RESULT_VALUES = {"success", "device_failure"}
_MAX_TRACE_BYTES = 1_000_000
_MAX_TEXT_LENGTH = 120
_MAX_FRAME_ID_LENGTH = 80
_SAFE_FRAME_ID = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]*$")
_SAFE_TEXT = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.: /-]*$")
_SAFE_TEXT_VALUES = frozenset(
    {"town", "stage entrance", *ACTION_KEYS, *MOVE_KEYS}
)
_REPLAY_FRAME = Frame(
    encoded="",
    geometry=_geometry_for_region({"left": 0, "top": 0, "width": 1024, "height": 768}),
)


class ReplayTraceError(ValueError):
    """Raised when a replay trace is malformed or contains unsafe data."""


class ReplayMismatch(ReplayTraceError):
    """Raised when replay output differs from the trace expectation."""


class _ReplayDeviceFailure(RuntimeError):
    """Private marker for a coarse replay failure before a primitive."""


class ReplayResult(str, Enum):
    """Expected result of one replayed action."""

    SUCCESS = "success"
    DEVICE_FAILURE = "device_failure"


@dataclass(frozen=True)
class ReplayDeviceCall:
    """One expected primitive call on the in-memory device."""

    method: str
    args: tuple[Any, ...]

    def __post_init__(self) -> None:
        _validate_device_call(self)

    def to_dict(self) -> dict[str, Any]:
        return _device_call_to_wire(self)


@dataclass(frozen=True)
class ReplayExpected:
    """Typed expected outcome for one replay step."""

    state_before: FarmState
    state_after: FarmState
    device_calls: tuple[ReplayDeviceCall, ...]
    result: ReplayResult

    def __post_init__(self) -> None:
        _validate_expected(self)

    def to_dict(self) -> dict[str, Any]:
        return _expected_to_wire(self)


@dataclass(frozen=True)
class ReplayStep:
    """One frame claim, proposed action, and expected deterministic outcome."""

    frame_id: str
    claim: Mapping[str, Any]
    action: Mapping[str, Any]
    expected: ReplayExpected

    def __post_init__(self) -> None:
        # Accept the old mapping form for direct callers, but store only the
        # validated typed form from this point onward.
        if isinstance(self.expected, Mapping):
            object.__setattr__(self, "expected", _parse_expected(self.expected, "direct"))
        elif not isinstance(self.expected, ReplayExpected):
            raise ReplayTraceError("ReplayStep expected tidak sesuai schema.")

    def to_dict(self) -> dict[str, Any]:
        return {
            "frame_id": _frame_id(self.frame_id, "direct"),
            "claim": _parse_claim(self.claim, "direct"),
            "action": _parse_action(self.action, "direct"),
            "expected": self.expected.to_dict(),
        }


@dataclass(frozen=True)
class ReplayTrace:
    """Versioned, JSON-compatible replay document."""

    steps: tuple[ReplayStep, ...]
    retreat_destination: str | None = None
    version: int = TRACE_VERSION
    profile: str = TRACE_PROFILE

    def __post_init__(self) -> None:
        if self.version != TRACE_VERSION or self.profile != TRACE_PROFILE:
            raise ReplayTraceError("Replay object tidak sesuai schema versi 1.")
        if not isinstance(self.steps, tuple) or not self.steps:
            raise ReplayTraceError("Replay harus memiliki minimal satu step.")
        if not all(isinstance(step, ReplayStep) for step in self.steps):
            raise ReplayTraceError("Replay steps tidak sesuai schema.")
        frame_ids = [_frame_id(step.frame_id, "direct") for step in self.steps]
        if len(frame_ids) != len(set(frame_ids)):
            raise ReplayTraceError("frame_id duplikat dalam replay.")
        try:
            validate_retreat_destination(self.retreat_destination)
        except ValueError:
            raise ReplayTraceError("Tujuan retreat replay tidak valid.") from None

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ReplayTrace":
        if not isinstance(value, Mapping):
            raise ReplayTraceError("Replay harus berupa object JSON.")
        _require_exact_keys(value, _TRACE_KEYS, "trace")
        if value.get("version") != TRACE_VERSION:
            raise ReplayTraceError(f"Versi replay harus {TRACE_VERSION}.")
        if value.get("profile") != TRACE_PROFILE:
            raise ReplayTraceError("Replay hanya mendukung profile minotaur.")
        try:
            destination = validate_retreat_destination(value.get("retreat_destination"))
        except ValueError as error:
            raise ReplayTraceError(str(error)) from None

        raw_steps = value.get("steps")
        if not isinstance(raw_steps, list) or not raw_steps:
            raise ReplayTraceError("Replay harus memiliki minimal satu step.")
        steps: list[ReplayStep] = []
        frame_ids: set[str] = set()
        for index, raw_step in enumerate(raw_steps):
            if not isinstance(raw_step, Mapping):
                raise ReplayTraceError(f"Step {index} harus berupa object JSON.")
            _require_exact_keys(raw_step, _STEP_KEYS, f"step {index}")
            frame_id = _frame_id(raw_step["frame_id"], index)
            if frame_id in frame_ids:
                raise ReplayTraceError(f"frame_id duplikat: {frame_id!r}.")
            frame_ids.add(frame_id)
            claim = _parse_claim(raw_step["claim"], index)
            action = _parse_action(raw_step["action"], index)
            expected = _parse_expected(raw_step["expected"], index)
            steps.append(ReplayStep(frame_id, claim, action, expected))
        return cls(tuple(steps), destination)

    def to_dict(self) -> dict[str, Any]:
        destination = validate_retreat_destination(self.retreat_destination)
        return {
            "version": self.version,
            "profile": self.profile,
            "retreat_destination": destination,
            "steps": [step.to_dict() for step in self.steps],
        }


@dataclass(frozen=True)
class ReplayReport:
    """Deterministic replay result."""

    steps_replayed: int
    final_state: FarmState
    device_calls: tuple[tuple[str, tuple[Any, ...]], ...]


class ReplayDevice:
    """In-memory DeviceInput implementation used only by the replay runner."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, tuple[Any, ...]]] = []
        self._fail_after: int | None = None
        self._fail_before_first_primitive = False

    def position(self) -> tuple[int, int]:
        if self._fail_before_first_primitive:
            self._fail_before_first_primitive = False
            raise _ReplayDeviceFailure("Simulated device failure before first primitive.")
        return (100, 100)

    def fail_before_first_primitive(self) -> None:
        """Fail the next safety position check before any primitive call."""
        self._fail_before_first_primitive = True

    def moveTo(self, x: int, y: int) -> None:
        self._record("moveTo", (x, y))

    def keyDown(self, key: str) -> None:
        self._record("keyDown", (key,))

    def keyUp(self, key: str) -> None:
        self._record("keyUp", (key,))

    def click(self) -> None:
        self._record("click", ())

    def rightClick(self) -> None:
        self._record("rightClick", ())

    def fail_after(self, call_count: int) -> None:
        """Fail after ``call_count`` successful primitives."""
        self._fail_after = call_count

    def _record(self, method: str, args: tuple[Any, ...]) -> None:
        if self._fail_after is not None and self._fail_after == 0:
            self._fail_after = None
            raise _ReplayDeviceFailure("Simulated device failure.")
        self.calls.append((method, args))
        if self._fail_after is not None:
            self._fail_after -= 1


def _is_replay_device_failure(error: BaseException) -> bool:
    """Recognize only this runner's fault through the safety wrapper."""
    return isinstance(error, _ReplayDeviceFailure) or isinstance(
        error.__cause__, _ReplayDeviceFailure
    )


def replay_trace(
    trace: ReplayTrace | Mapping[str, Any],
    *,
    profile: FarmProfile = MINOTAUR_PROFILE,
) -> ReplayReport:
    """Replay claims through the live validation and action paths.

    No OpenAI call, screenshot capture, focus check, sleep, or physical
    input occurs. The claim is parsed and validated, the action budget is
    checked, ``execute_game_action`` runs against a synthetic frame and
    ``ReplayDevice``, and ``FarmWatchdog.advance`` commits only after success.
    """
    if isinstance(trace, ReplayTrace):
        # Revalidate objects created directly by callers instead of trusting
        # dataclass construction to enforce the wire schema.
        try:
            raw_trace = trace.to_dict()
        except (AttributeError, TypeError, ValueError) as error:
            raise ReplayTraceError("Object ReplayTrace tidak sesuai schema.") from None
        trace = ReplayTrace.from_dict(raw_trace)
    else:
        trace = ReplayTrace.from_dict(trace)
    if trace.profile != profile.name:
        raise ReplayTraceError("Replay profile tidak cocok dengan FarmProfile.")
    watchdog = FarmWatchdog(profile, retreat_destination=trace.retreat_destination)
    device = ReplayDevice()

    for index, step in enumerate(trace.steps):
        expected = step.expected
        _expect_state(watchdog.state, expected.state_before, index, "state_before")
        claim = FarmObservationClaim.from_wire(
            step.claim["farm_state"],
            step.claim.get("text"),
            step.claim.get("coordinate"),
        )
        action_name = step.action["action"]
        candidate = watchdog.validate_claim(claim, action_name)
        watchdog.ensure_action_allowed(candidate)
        before_calls = len(device.calls)
        try:
            if expected.result is ReplayResult.DEVICE_FAILURE:
                if expected.device_calls:
                    device.fail_after(len(expected.device_calls))
                else:
                    # A zero-call device failure is deliberately coarse. It
                    # represents failure before the first primitive, such as
                    # an emergency-stop position observation failure.
                    device.fail_before_first_primitive()
            # The action implementation is reused unchanged. Only the two
            # live-only guards are replaced for this in-memory runner: replay
            # has no focused game window and must not wait in real time.
            with patch.object(_input_control, "check_target_window", lambda: None), patch.object(
                _input_control, "_safe_sleep", lambda _seconds, device: None
            ):
                execute_game_action(
                    action=action_name,
                    coordinate=step.action.get("coordinate"),
                    text=step.action.get("text"),
                    duration=step.action.get("duration", 0.05),
                    frame=_REPLAY_FRAME,
                    device=device,
                )
        except _ReplayDeviceFailure as error:
            if expected.result is not ReplayResult.DEVICE_FAILURE:
                raise ReplayMismatch(f"Step {index}: device gagal tanpa ekspektasi.") from error
            if expected.state_after is not expected.state_before:
                raise ReplayMismatch(
                    f"Step {index}: device_failure harus mempertahankan state."
                ) from error
        except ValueError as error:
            raise ReplayTraceError(f"Step {index}: aksi tidak valid: {error}") from None
        except Exception as error:
            if not isinstance(error, EmergencyStop) or not _is_replay_device_failure(error):
                raise
            if expected.result is not ReplayResult.DEVICE_FAILURE:
                raise ReplayMismatch(f"Step {index}: device gagal tanpa ekspektasi.") from error
            if expected.state_after is not expected.state_before:
                raise ReplayMismatch(
                    f"Step {index}: device_failure harus mempertahankan state."
                ) from error
        else:
            if expected.result is ReplayResult.DEVICE_FAILURE:
                raise ReplayMismatch(f"Step {index}: device_failure tidak terjadi.")
            watchdog.advance(candidate, action_name)

        _expect_state(watchdog.state, expected.state_after, index, "state_after")
        actual_calls = device.calls[before_calls:]
        expected_calls = tuple(
            (call.method, call.args) for call in expected.device_calls
        )
        if tuple(actual_calls) != expected_calls:
            raise ReplayMismatch(
                f"Step {index}: device_calls berbeda; expected {expected_calls!r}, "
                f"got {tuple(actual_calls)!r}."
            )

    return ReplayReport(len(trace.steps), watchdog.state, tuple(device.calls))


def load_replay_trace(path: str | Path) -> ReplayTrace:
    """Load and validate one UTF-8 JSON replay without reading external assets."""
    file_path = Path(path)
    try:
        if file_path.stat().st_size > _MAX_TRACE_BYTES:
            raise ReplayTraceError("File replay terlalu besar.")
        value = json.loads(file_path.read_text(encoding="utf-8"))
    except ReplayTraceError:
        raise
    except (OSError, UnicodeError, json.JSONDecodeError) as error:
        raise ReplayTraceError(f"Replay tidak dapat dibaca: {error}") from None
    return ReplayTrace.from_dict(value)


def _parse_claim(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplayTraceError(f"Step {index} claim harus berupa object JSON.")
    _require_subset_keys(value, _CLAIM_KEYS, f"step {index} claim")
    if "farm_state" not in value:
        raise ReplayTraceError(f"Step {index} claim wajib memiliki farm_state.")
    result = {key: value[key] for key in value}
    _validate_optional_text(result, "text", f"step {index} claim")
    _validate_optional_coordinate(result, "coordinate", f"step {index} claim")
    _validate_state_value(result["farm_state"], f"step {index} farm_state")
    _validate_policy_text(result.get("text"), f"step {index} claim text")
    return result


def _parse_action(value: Any, index: int) -> dict[str, Any]:
    if not isinstance(value, Mapping):
        raise ReplayTraceError(f"Step {index} action harus berupa object JSON.")
    _require_subset_keys(value, _ACTION_KEYS, f"step {index} action")
    if "action" not in value:
        raise ReplayTraceError(f"Step {index} action wajib memiliki action.")
    result = {key: value[key] for key in value}
    _safe_text(result["action"], f"step {index} action", 40)
    _validate_optional_text(result, "text", f"step {index} action")
    _validate_optional_coordinate(result, "coordinate", f"step {index} action")
    _validate_policy_text(result.get("text"), f"step {index} action text")
    if "duration" in result:
        if (
            isinstance(result["duration"], bool)
            or not isinstance(result["duration"], (int, float))
            or not math.isfinite(result["duration"])
        ):
            raise ReplayTraceError(f"Step {index} duration harus berupa angka finite.")
    return result


def _parse_expected(value: Any, index: int | str) -> ReplayExpected:
    if not isinstance(value, Mapping):
        raise ReplayTraceError(f"Step {index} expected harus berupa object JSON.")
    _require_exact_keys(value, _EXPECTED_KEYS, f"step {index} expected")
    state_before = _validate_state_value(value["state_before"], f"step {index} state_before")
    state_after = _validate_state_value(value["state_after"], f"step {index} state_after")
    result = value["result"]
    if not isinstance(result, str) or result not in _RESULT_VALUES:
        raise ReplayTraceError(f"Step {index} result tidak dikenal.")
    device_calls = _parse_device_calls(value["device_calls"], index)
    if result == ReplayResult.DEVICE_FAILURE.value and state_after is not state_before:
        raise ReplayTraceError(f"Step {index} device_failure harus mempertahankan state.")
    return ReplayExpected(
        state_before=state_before,
        state_after=state_after,
        device_calls=device_calls,
        result=ReplayResult(result),
    )


def _parse_device_calls(value: Any, index: int | str) -> tuple[ReplayDeviceCall, ...]:
    if not isinstance(value, list):
        raise ReplayTraceError(f"Step {index} device_calls harus berupa list.")
    if len(value) > 8:
        raise ReplayTraceError("device_calls terlalu banyak.")
    calls: list[ReplayDeviceCall] = []
    for call in value:
        if not isinstance(call, Mapping) or set(call) != {"method", "args"}:
            raise ReplayTraceError("device_call harus memiliki method dan args.")
        args = call["args"]
        if not isinstance(args, list):
            raise ReplayTraceError("device_call tidak valid.")
        typed_call = ReplayDeviceCall(call["method"], tuple(args))
        _validate_device_call(typed_call)
        calls.append(typed_call)
    return tuple(calls)


def _validate_device_call(call: ReplayDeviceCall) -> None:
    if not isinstance(call.method, str) or not isinstance(call.args, tuple):
        raise ReplayTraceError("device_call tidak sesuai schema.")
    if call.method not in _CALL_METHODS:
        raise ReplayTraceError("device_call tidak valid.")
    args = call.args
    if call.method == "moveTo":
        valid_args = len(args) == 2 and all(
            isinstance(argument, int) and not isinstance(argument, bool)
            for argument in args
        )
    elif call.method in {"keyDown", "keyUp"}:
        valid_args = (
            len(args) == 1
            and isinstance(args[0], str)
            and args[0].casefold() in ACTION_KEYS | MOVE_KEYS
        )
    else:
        valid_args = len(args) == 0
    if not valid_args:
        raise ReplayTraceError("device_call args tidak sesuai method.")


def _device_call_to_wire(call: ReplayDeviceCall) -> dict[str, Any]:
    if not isinstance(call, ReplayDeviceCall):
        raise ReplayTraceError("device_call tidak sesuai schema.")
    _validate_device_call(call)
    return {"method": call.method, "args": list(call.args)}


def _validate_expected(expected: ReplayExpected) -> None:
    if not isinstance(expected.state_before, FarmState) or not isinstance(
        expected.state_after, FarmState
    ):
        raise ReplayTraceError("expected state tidak sesuai schema.")
    if (
        not isinstance(expected.device_calls, tuple)
        or len(expected.device_calls) > 8
        or not all(isinstance(call, ReplayDeviceCall) for call in expected.device_calls)
    ):
        raise ReplayTraceError("expected device_calls tidak sesuai schema.")
    if not isinstance(expected.result, ReplayResult):
        raise ReplayTraceError("expected result tidak sesuai schema.")
    if expected.result is ReplayResult.DEVICE_FAILURE and expected.state_after is not expected.state_before:
        raise ReplayTraceError("Step device_failure harus mempertahankan state.")


def _expected_to_wire(expected: ReplayExpected) -> dict[str, Any]:
    if not isinstance(expected, ReplayExpected):
        raise ReplayTraceError("expected tidak sesuai schema.")
    _validate_expected(expected)
    return {
        "state_before": expected.state_before.value,
        "state_after": expected.state_after.value,
        "device_calls": [_device_call_to_wire(call) for call in expected.device_calls],
        "result": expected.result.value,
    }


def _validate_state_value(value: Any, field: str) -> FarmState:
    if not isinstance(value, str) or value not in {state.value for state in FarmState}:
        raise ReplayTraceError(f"{field} harus berupa state farming yang dikenal.")
    return FarmState(value)


def _expect_state(actual: FarmState, expected: FarmState, index: int, field: str) -> None:
    if actual is not expected:
        raise ReplayMismatch(
            f"Step {index}: {field} expected {expected.value!r}, got {actual.value!r}."
        )


def _frame_id(value: Any, index: int) -> str:
    if (
        not isinstance(value, str)
        or len(value) > _MAX_FRAME_ID_LENGTH
        or not _SAFE_FRAME_ID.fullmatch(value)
    ):
        raise ReplayTraceError(f"Step {index} frame_id harus berupa identifier opaque.")
    return value


def _safe_text(value: Any, field: str, limit: int) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > limit
        or not _SAFE_TEXT.fullmatch(value)
    ):
        raise ReplayTraceError(
            f"{field} harus berupa teks sintetis singkat tanpa secret atau data pribadi."
        )
    return value


def _validate_policy_text(value: Any, field: str) -> None:
    """Allow only workflow tokens, never arbitrary UI or personal text."""
    if value is not None and value.casefold() not in _SAFE_TEXT_VALUES:
        raise ReplayTraceError(
            f"{field} harus memakai token workflow yang sudah diizinkan."
        )


def _validate_optional_text(value: Mapping[str, Any], field: str, context: str) -> None:
    if field in value and value[field] is not None:
        _safe_text(value[field], f"{context} {field}", _MAX_TEXT_LENGTH)


def _validate_optional_coordinate(value: Mapping[str, Any], field: str, context: str) -> None:
    if field in value and value[field] is not None:
        coordinate = value[field]
        if (
            not isinstance(coordinate, list)
            or len(coordinate) != 2
            or any(isinstance(part, bool) or not isinstance(part, int) for part in coordinate)
            or not all(0 <= part < limit for part, limit in zip(coordinate, (1024, 768)))
        ):
            raise ReplayTraceError(f"{context} {field} harus berupa coordinate integer valid.")


def _require_exact_keys(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    if set(value) != allowed:
        raise ReplayTraceError(f"{context} memiliki field yang tidak sesuai schema.")


def _require_subset_keys(value: Mapping[str, Any], allowed: set[str], context: str) -> None:
    if not set(value).issubset(allowed):
        raise ReplayTraceError(f"{context} memiliki field yang tidak sesuai schema.")
