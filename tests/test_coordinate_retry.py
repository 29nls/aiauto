"""Focused tests: bounded coordinate-error retry inside ``run_dn_bot``.

When the model proposes an action whose coordinate fails validation (outside
the 1024x768 frame, in the letterbox padding, or mapping onto the failsafe
corner), the orchestrator must NOT execute it. It reports the failure back to
the model as a tool result and re-asks for a corrected action on the same
frame, up to ``MAX_COORDINATE_RETRIES`` per step. Exhausting the budget aborts
the session fail closed, exactly like any other action failure.

These tests drive the real ``execute_game_action`` (only the window-focus and
sleep helpers are patched), so an invalid action provably never reaches the
input device.
"""

import json
import os
import subprocess
import sys
from unittest.mock import patch

import pytest

import dn_bot
from conftest import RecordingDevice
from dn_bot.replay import load_replay_trace, replay_trace


def _reply(request_id, tool_input):
    return dn_bot.ModelReply(
        text="",
        tool_requests=[dn_bot.ToolRequest(id=request_id, input=tool_input)],
    )


_OUT_OF_BOUNDS_CLICK = {"action": "left_click", "coordinate": [2000, 2000]}
_VALID_WAIT = {"action": "wait"}

# (moveTo, click, rightClick) are the only primitives a coordinate action could
# perform; their absence proves the invalid action was never executed.
_EXECUTED = ("moveTo", "click", "rightClick")


def _env():
    # The retry budget is pinned to the default so the assertions below stay
    # deterministic even if an operator sets DN_COORDINATE_MAX_RETRIES locally.
    return patch.dict(
        os.environ,
        {
            "OPENAI_API_KEY": "test-key",
            "OPENAI_MODEL": "test/free",
            "DN_COORDINATE_MAX_RETRIES": "2",
        },
        clear=False,
    )


def test_invalid_coordinate_error_is_a_value_error_subclass(capture_region):
    """The retry trigger subclasses ValueError, so existing consumers that
    catch ValueError (replay, action validation, tests) are unaffected."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    assert issubclass(dn_bot.InvalidCoordinateError, ValueError)
    with pytest.raises(dn_bot.InvalidCoordinateError, match="luar ukuran"):
        dn_bot._physical_point([2000, 2000], frame)


def test_near_boundary_coordinate_is_clipped_not_rejected(capture_region):
    """A coordinate barely beyond the frame edge (≤ 8 px) is clipped to the
    nearest valid pixel instead of raising InvalidCoordinateError.
    [#1,025, #  500] → [1,023,  500]; [-3, 200] → [0, 200]."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    # Just past the right edge: clipped to (1023, 500), identical to [1023, 500].
    assert dn_bot._physical_point([1025, 500], frame) == dn_bot._physical_point(
        [1023, 500], frame
    )
    # Just before the top edge: clipped to (200, 0), identical to [200, 0].
    assert dn_bot._physical_point([200, -3], frame) == dn_bot._physical_point(
        [200, 0], frame
    )
    # Still raises for genuinely wild coordinates.
    with pytest.raises(dn_bot.InvalidCoordinateError, match="luar ukuran"):
        dn_bot._physical_point([9999, 9999], frame)


def test_out_of_bounds_coordinate_is_reported_back_and_corrected(capture_region):
    """An out-of-bounds coordinate is never executed: the orchestrator captures
    a fresh frame and sends the invalid-coordinate message as user feedback;
    the corrected action then runs normally."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    replies = iter(
        [_reply("call-1", _OUT_OF_BOUNDS_CLICK), _reply("call-2", _VALID_WAIT)]
    )
    requests = []
    captures = {"count": 0}

    def _capture():
        captures["count"] += 1
        return frame

    device = RecordingDevice()
    with _env(), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", side_effect=_capture
    ), patch.object(
        dn_bot.orchestrator,
        "_call_openai",
        side_effect=lambda *args, **kwargs: (
            requests.append(args[2]),
            next(replies),
        )[1],
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        dn_bot.run_dn_bot("go", max_steps=1, device=device)

    assert len(requests) == 2
    # The retry call now carries the error as a user message (not a tool
    # result) to avoid Gemini's thought_signature requirement.
    feedback = [
        message
        for message in requests[1]
        if message.get("role") == "user"
        and isinstance(message.get("content"), str)
        and "Koordinat tidak valid" in message["content"]
    ]
    assert feedback
    # The retry captures a fresh frame so the model re-analyses the screen;
    # together with the step-start capture and the post-action refresh that
    # totals three captures for a single-step session.
    assert captures["count"] == 3
    assert not [call for call in device.calls if call[0] in _EXECUTED]


def test_missing_coordinate_is_reported_back_and_corrected(capture_region):
    """A click action with no coordinate at all is the same family of model
    mistake: it is never executed, gets the same feedback tool result, and the
    model is re-asked for a corrected action."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    replies = iter(
        [
            _reply("call-1", {"action": "left_click"}),
            _reply("call-2", _VALID_WAIT),
        ]
    )
    requests = []
    device = RecordingDevice()
    with _env(), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator,
        "_call_openai",
        side_effect=lambda *args, **kwargs: (
            requests.append(args[2]),
            next(replies),
        )[1],
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        dn_bot.run_dn_bot("go", max_steps=1, device=device)

    assert len(requests) == 2
    feedback = [
        message
        for message in requests[1]
        if message.get("role") == "user"
        and isinstance(message.get("content"), str)
        and "Koordinat tidak valid" in message["content"]
    ]
    assert feedback
    assert "membutuhkan coordinate" in feedback[0]["content"]
    assert not [call for call in device.calls if call[0] in _EXECUTED]


def test_coordinate_retry_exhaustion_aborts_without_executing(capture_region):
    """Exhausting the per-step retry budget aborts the session fail closed and
    the invalid action is never executed."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    calls = {"count": 0}
    device = RecordingDevice()

    def _reply_bad(*args, **kwargs):
        calls["count"] += 1
        return _reply(f"call-{calls['count']}", _OUT_OF_BOUNDS_CLICK)

    with _env(), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator, "_call_openai", side_effect=_reply_bad
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        with pytest.raises(RuntimeError, match="Aksi 'left_click' gagal"):
            dn_bot.run_dn_bot("go", max_steps=1, device=device)

    assert calls["count"] == dn_bot.orchestrator.MAX_COORDINATE_RETRIES + 1
    assert not [call for call in device.calls if call[0] in _EXECUTED]


def test_coordinate_retry_budget_zero_aborts_immediately(capture_region, caplog):
    """DN_COORDINATE_MAX_RETRIES=0 disables retries: an invalid coordinate
    aborts the session fail closed after exactly one model call, still without
    executing anything. The log surfaces the exhausted budget before aborting."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    calls = {"count": 0}
    device = RecordingDevice()

    def _reply_bad(*args, **kwargs):
        calls["count"] += 1
        return _reply(f"call-{calls['count']}", _OUT_OF_BOUNDS_CLICK)

    with _env(), patch.dict(
        os.environ, {"DN_COORDINATE_MAX_RETRIES": "0"}, clear=False
    ), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator, "_call_openai", side_effect=_reply_bad
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        with pytest.raises(RuntimeError, match="Aksi 'left_click' gagal"):
            dn_bot.run_dn_bot("go", max_steps=1, device=device)

    assert calls["count"] == 1
    assert not [call for call in device.calls if call[0] in _EXECUTED]
    assert "Budget retry koordinat habis (DN_COORDINATE_MAX_RETRIES=0)" in caplog.text


def test_coordinate_retry_budget_one_allows_single_retry(capture_region, caplog):
    """DN_COORDINATE_MAX_RETRIES=1 allows exactly one re-ask: two model calls
    in total before the session aborts fail closed, still without executing
    anything. The log surfaces the exhausted budget after the retry fails."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    calls = {"count": 0}
    device = RecordingDevice()

    def _reply_bad(*args, **kwargs):
        calls["count"] += 1
        return _reply(f"call-{calls['count']}", _OUT_OF_BOUNDS_CLICK)

    with _env(), patch.dict(
        os.environ, {"DN_COORDINATE_MAX_RETRIES": "1"}, clear=False
    ), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator, "_call_openai", side_effect=_reply_bad
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        with pytest.raises(RuntimeError, match="Aksi 'left_click' gagal"):
            dn_bot.run_dn_bot("go", max_steps=1, device=device)

    assert calls["count"] == 2
    assert not [call for call in device.calls if call[0] in _EXECUTED]
    assert "Budget retry koordinat habis (DN_COORDINATE_MAX_RETRIES=1)" in caplog.text


def test_coordinate_retry_model_stubbornly_sends_invalid_until_exhausted(
    capture_region, caplog
):
    """With budget=2, a model that keeps sending invalid coordinates gets
    retried twice, then the session aborts with the budget exhaustion log.
    All three model calls produce out-of-bounds clicks; none are executed."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    calls = {"count": 0}
    device = RecordingDevice()

    def _always_bad(*args, **kwargs):
        calls["count"] += 1
        return _reply(f"call-{calls['count']}", _OUT_OF_BOUNDS_CLICK)

    with _env(), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator, "_call_openai", side_effect=_always_bad
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        with pytest.raises(RuntimeError, match="Aksi 'left_click' gagal"):
            dn_bot.run_dn_bot("go", max_steps=1, device=device)

    assert calls["count"] == 3  # initial + 2 retries
    assert not [call for call in device.calls if call[0] in _EXECUTED]
    assert "Budget retry koordinat habis (DN_COORDINATE_MAX_RETRIES=2)" in caplog.text


def test_coordinate_retry_answers_all_tool_calls_before_reasking(capture_region):
    """When the first of several tool calls fails validation, every tool call
    in that reply still gets a tool result before the model is re-asked (the
    OpenAI-compatible wire requires complete tool results)."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    replies = iter(
        [
            dn_bot.ModelReply(
                text="",
                tool_requests=[
                    dn_bot.ToolRequest(id="call-1", input=_OUT_OF_BOUNDS_CLICK),
                    dn_bot.ToolRequest(id="call-2", input=_VALID_WAIT),
                ],
            ),
            _reply("call-3", _VALID_WAIT),
        ]
    )
    requests = []
    with _env(), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator,
        "_call_openai",
        side_effect=lambda *args, **kwargs: (
            requests.append(args[2]),
            next(replies),
        )[1],
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        dn_bot.run_dn_bot("go", max_steps=1, device=RecordingDevice())

    assert len(requests) == 2
    # The invalid assistant message is popped before retry; the retry call
    # carries error feedback as a user message with frame, not tool results.
    second_messages = requests[1]
    user_feedback = [
        message
        for message in second_messages
        if message.get("role") == "user"
        and isinstance(message.get("content"), str)
        and "Koordinat tidak valid" in message["content"]
    ]
    assert user_feedback


def test_coordinate_retry_exhausted_with_recorder_writes_no_trace(capture_region, tmp_path):
    """With --record-trace active, exhausting coordinate retries re-raises the
    coordinate error (a validation failure, not a device failure) and never
    writes a partial trace or a misleading device_failure entry."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    trace_path = tmp_path / "trace.json"
    calls = {"count": 0}

    def _reply_bad(*args, **kwargs):
        calls["count"] += 1
        return _reply(
            f"call-{calls['count']}",
            {
                "action": "left_click",
                "farm_state": "entering_dungeon",
                "coordinate": [2000, 2000],
            },
        )

    with _env(), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator, "_call_openai", side_effect=_reply_bad
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        with pytest.raises(dn_bot.InvalidCoordinateError, match="luar ukuran"):
            dn_bot.run_dn_bot(
                "farm minotaur",
                max_steps=1,
                farm_profile=dn_bot.MINOTAUR_PROFILE,
                device=RecordingDevice(),
                record_trace_path=trace_path,
            )

    assert calls["count"] == dn_bot.orchestrator.MAX_COORDINATE_RETRIES + 1
    assert not trace_path.exists()


def test_non_coordinate_action_error_aborts_without_retry(capture_region):
    """Errors that are not coordinate-validation failures still abort the
    session immediately, exactly once — no retry loop."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    calls = {"count": 0}

    def _reply_wait(*args, **kwargs):
        calls["count"] += 1
        return _reply("call-1", _VALID_WAIT)

    with _env(), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator, "_call_openai", side_effect=_reply_wait
    ), patch.object(
        dn_bot.orchestrator,
        "execute_game_action",
        side_effect=ValueError("boom"),
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"):
        with pytest.raises(RuntimeError, match="Aksi 'wait' gagal"):
            dn_bot.run_dn_bot("go", max_steps=1, device=RecordingDevice())

    assert calls["count"] == 1


def test_farm_coordinate_retry_keeps_watchdog_state_until_valid_action(
    capture_region,
):
    """In farm mode a failed coordinate action must not advance the watchdog;
    the corrected action is revalidated against the unchanged state."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    replies = iter(
        [
            _reply(
                "call-1",
                {
                    "action": "left_click",
                    "farm_state": "entering_dungeon",
                    "coordinate": [2000, 2000],
                },
            ),
            _reply("call-2", {"action": "wait", "farm_state": "pre_dungeon"}),
        ]
    )
    watchdogs = []

    def build_watchdog(profile, **kwargs):
        watchdog = dn_bot.FarmWatchdog(profile, **kwargs)
        watchdogs.append(watchdog)
        return watchdog

    with _env(), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator,
        "_call_openai",
        side_effect=lambda *args, **kwargs: next(replies),
    ), patch.object(
        dn_bot.orchestrator, "FarmWatchdog", side_effect=build_watchdog
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        dn_bot.run_dn_bot(
            "farm minotaur",
            max_steps=1,
            farm_profile=dn_bot.MINOTAUR_PROFILE,
            device=RecordingDevice(),
        )

    assert len(watchdogs) == 1
    # The failed left_click must not advance the state; only the corrected
    # same-state wait runs, so the watchdog stays in PRE_DUNGEON.
    assert watchdogs[0].state is dn_bot.FarmState.PRE_DUNGEON


def test_record_replay_roundtrip_with_missing_coordinate_retry(tmp_path, capture_region):
    """Regression guard: a session that retried a missing-coordinate action
    records a replayable JSON v1 trace containing ONLY the corrected valid
    step, and that artifact replays successfully both in-process and through
    the ``python -m dn_bot replay`` CLI subprocess — with the expected final
    state, step count, and device calls. Expectations are hand-authored, and
    no game window, screenshot, network, or credentials are involved."""
    path = tmp_path / "trace.json"
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    replies = iter(
        [
            # Attempt 1: a click with NO coordinate — retried, never executed.
            _reply(
                "call-1",
                {"action": "left_click", "farm_state": "entering_dungeon"},
            ),
            # Attempt 2: the corrected action that actually runs and records.
            _reply(
                "call-2",
                {
                    "action": "left_click",
                    "farm_state": "entering_dungeon",
                    "coordinate": [512, 384],
                },
            ),
        ]
    )
    requests = []
    device = RecordingDevice()
    with _env(), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator,
        "_call_openai",
        side_effect=lambda *args, **kwargs: (
            requests.append(args[2]),
            next(replies),
        )[1],
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        dn_bot.run_dn_bot(
            "farm minotaur",
            max_steps=1,
            farm_profile=dn_bot.MINOTAUR_PROFILE,
            device=device,
            record_trace_path=path,
        )

    # The missing-coordinate attempt was reported back to the model (one
    # retry), never executed, and never recorded. The retry call carries
    # error feedback as a user message (not a tool result) to avoid
    # Gemini's thought_signature requirement on function-call history.
    assert len(requests) == 2
    feedback = [
        message
        for message in requests[1]
        if message.get("role") == "user"
        and isinstance(message.get("content"), str)
        and "Koordinat tidak valid" in message["content"]
    ]
    assert feedback
    assert "membutuhkan coordinate" in feedback[0]["content"]
    # Only the corrected action reached the device, exactly once: the failed
    # attempt contributed zero primitives.
    assert [call for call in device.calls if call[0] in _EXECUTED] == [
        ("moveTo", (512, 384)),
        ("click", ()),
    ]

    # Emitted trace: exactly one valid, secret-free step with hand-authored
    # expectations (the failed attempt is absent).
    wire = json.loads(path.read_text(encoding="utf-8"))
    assert wire["version"] == 1
    assert wire["profile"] == "minotaur"
    steps = wire["steps"]
    assert len(steps) == 1
    step = steps[0]
    assert step["frame_id"] == "frame_000001"
    assert "text" not in step["claim"] and "text" not in step["action"]
    assert step["claim"]["farm_state"] == "entering_dungeon"
    assert step["claim"]["coordinate"] == [512, 384]
    assert step["action"]["action"] == "left_click"
    assert step["action"]["coordinate"] == [512, 384]
    assert step["expected"]["state_before"] == "pre_dungeon"
    assert step["expected"]["state_after"] == "entering_dungeon"
    assert step["expected"]["result"] == "success"
    assert step["expected"]["device_calls"] == [
        {"method": "moveTo", "args": [512, 384]},
        {"method": "click", "args": []},
    ]

    # In-process replay through the real offline machinery (JSON v1 parser,
    # FarmWatchdog, ReplayDevice, execute_game_action).
    report = replay_trace(load_replay_trace(path))
    assert report.steps_replayed == 1
    assert report.final_state is dn_bot.FarmState.ENTERING_DUNGEON
    assert report.device_calls == (("moveTo", (512, 384)), ("click", ()))

    # Replay through the shipped CLI subprocess, fully offline.
    result = subprocess.run(
        [sys.executable, "-m", "dn_bot", "replay", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Replay berhasil" in result.stdout
    assert "final_state=entering_dungeon" in result.stdout
    assert "steps=1" in result.stdout
    assert "device_calls=2" in result.stdout
    assert result.stderr == ""


def test_record_replay_roundtrip_with_device_failure(tmp_path, capture_region):
    """Regression guard: a session whose valid action fails mid-primitive
    (moveTo succeeds, click fails) records a replayable JSON v1 trace with a
    ``device_failure`` step that preserves state (``state_before`` ==
    ``state_after``) and only the partial calls that succeeded — and that
    artifact replays identically both in-process and through the
    ``python -m dn_bot replay`` CLI subprocess. Expectations are hand-authored;
    no game window, screenshot, network, or credentials are involved."""

    class ClickFailingDevice(RecordingDevice):
        """moveTo succeeds; click fails — a mid-primitive device failure."""

        def click(self):
            self.calls.append(("click", ()))
            raise RuntimeError("device click failed")

    path = tmp_path / "trace.json"
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    replies = iter(
        [
            _reply(
                "call-1",
                {
                    "action": "left_click",
                    "farm_state": "entering_dungeon",
                    "coordinate": [512, 384],
                },
            )
        ]
    )
    requests = []
    device = ClickFailingDevice()
    with _env(), patch.object(
        dn_bot.orchestrator, "get_openai_client"
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator,
        "_call_openai",
        side_effect=lambda *args, **kwargs: (
            requests.append(args[2]),
            next(replies),
        )[1],
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        with pytest.raises(RuntimeError, match="Aksi 'left_click' gagal"):
            dn_bot.run_dn_bot(
                "farm minotaur",
                max_steps=1,
                farm_profile=dn_bot.MINOTAUR_PROFILE,
                device=device,
                record_trace_path=path,
            )

    # A device failure is a recorded outcome, not a retry: exactly one model
    # request, and the session aborts fail closed after the trace is flushed.
    assert len(requests) == 1

    # Emitted trace: one device_failure step whose state is preserved and
    # whose device_calls hold only the primitives that succeeded (moveTo was
    # recorded; the failing click never became a call).
    wire = json.loads(path.read_text(encoding="utf-8"))
    assert wire["version"] == 1
    assert wire["profile"] == "minotaur"
    steps = wire["steps"]
    assert len(steps) == 1
    step = steps[0]
    assert step["frame_id"] == "frame_000001"
    assert "text" not in step["claim"] and "text" not in step["action"]
    assert step["claim"]["farm_state"] == "entering_dungeon"
    assert step["claim"]["coordinate"] == [512, 384]
    assert step["action"]["action"] == "left_click"
    assert step["action"]["coordinate"] == [512, 384]
    assert step["expected"]["state_before"] == "pre_dungeon"
    assert step["expected"]["state_after"] == "pre_dungeon"
    assert step["expected"]["result"] == "device_failure"
    assert step["expected"]["device_calls"] == [
        {"method": "moveTo", "args": [512, 384]}
    ]

    # In-process replay through the real offline machinery: the failure
    # re-fires after the first primitive, the watchdog never advances, and
    # only the successful call is counted.
    report = replay_trace(load_replay_trace(path))
    assert report.steps_replayed == 1
    assert report.final_state is dn_bot.FarmState.PRE_DUNGEON
    assert report.device_calls == (("moveTo", (512, 384)),)

    # Replay through the shipped CLI subprocess, fully offline.
    result = subprocess.run(
        [sys.executable, "-m", "dn_bot", "replay", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )
    assert result.returncode == 0, result.stderr
    assert "Replay berhasil" in result.stdout
    assert "final_state=pre_dungeon" in result.stdout
    assert "steps=1" in result.stdout
    assert "device_calls=1" in result.stdout
    assert result.stderr == ""
