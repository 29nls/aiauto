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

import os
from unittest.mock import patch

import pytest

import dn_bot
from conftest import RecordingDevice


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
    return patch.dict(
        os.environ,
        {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test/free"},
        clear=False,
    )


def test_invalid_coordinate_error_is_a_value_error_subclass(capture_region):
    """The retry trigger subclasses ValueError, so existing consumers that
    catch ValueError (replay, action validation, tests) are unaffected."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    assert issubclass(dn_bot.InvalidCoordinateError, ValueError)
    with pytest.raises(dn_bot.InvalidCoordinateError, match="luar ukuran"):
        dn_bot._physical_point([2000, 2000], frame)


def test_out_of_bounds_coordinate_is_reported_back_and_corrected(capture_region):
    """An out-of-bounds coordinate is never executed: the orchestrator sends a
    tool result with the invalid-coordinate message and re-asks the model on
    the same frame; the corrected action then runs normally."""
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
    feedback = [
        message
        for message in requests[1]
        if message.get("role") == "tool" and message.get("tool_call_id") == "call-1"
    ]
    assert feedback
    assert feedback[0]["content"].startswith("Koordinat tidak valid")
    # The retry reuses the same frame: only the session start and the post-step
    # refresh captured, never a mid-retry screenshot.
    assert captures["count"] == 2
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
    second_messages = requests[1]
    tool_results = [
        message
        for message in second_messages
        if message.get("role") == "tool"
    ]
    answered = {message["tool_call_id"] for message in tool_results}
    assert {"call-1", "call-2"} <= answered
    assert any(
        message.get("tool_call_id") == "call-2" and "ditolak" in message["content"]
        for message in tool_results
    )


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
