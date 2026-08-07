import json
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import dn_bot
import dn_bot.__main__
from conftest import RecordingDevice
from dn_bot.recording import (
    TraceRecorder,
    TraceRecordingDevice,
    TraceRecordingError,
    load_trace_path,
)
from dn_bot.replay import ReplayResult, load_replay_trace, replay_trace


_REGION = {"left": 0, "top": 0, "width": 1024, "height": 768}


def _step_data():
    claim = dn_bot.FarmObservationClaim(
        dn_bot.FarmState.ENTERING_DUNGEON,
        text="  WONT_BE_STORED ",
        coordinate=[500, 400],
    )
    action = {
        "action": "left_click",
        "text": "Town <free ui text>",
        "coordinate": [500, 400],
        "duration": 0.3,
    }
    return claim, action


def test_trace_recording_device_delegates_and_excludes_position():
    delegate = RecordingDevice(position=(100, 100))
    device = TraceRecordingDevice(delegate)

    device.begin_action()
    assert device.position() == (100, 100)
    device.moveTo(10, 20)
    device.keyDown("w")
    device.keyUp("w")
    device.click()
    device.rightClick()

    assert delegate.calls == [
        ("position", ()),
        ("moveTo", (10, 20)),
        ("keyDown", ("w",)),
        ("keyUp", ("w",)),
        ("click", ()),
        ("rightClick", ()),
    ]
    assert device.action_calls == (
        dn_bot.ReplayDeviceCall("moveTo", (10, 20)),
        dn_bot.ReplayDeviceCall("keyDown", ("w",)),
        dn_bot.ReplayDeviceCall("keyUp", ("w",)),
        dn_bot.ReplayDeviceCall("click", ()),
        dn_bot.ReplayDeviceCall("rightClick", ()),
    )
    assert device.action_failed is False


def test_trace_recording_device_marks_position_failure_without_recording_observation():
    class FailingPositionDevice(RecordingDevice):
        def position(self):
            raise OSError("position offline")

    device = TraceRecordingDevice(FailingPositionDevice())
    with pytest.raises(OSError, match="position offline"):
        device.position()
    assert device.action_failed is True
    assert device.action_calls == ()


def test_trace_recording_device_marks_delegate_failure_without_faking_success():
    class FailingDevice(RecordingDevice):
        def click(self):
            self.calls.append(("moveTo", (99, 99)))
            raise OSError("device offline")

    delegate = FailingDevice()
    device = TraceRecordingDevice(delegate)
    device.begin_action()
    device.moveTo(1, 2)
    with pytest.raises(OSError, match="device offline"):
        device.click()

    assert device.action_failed is True
    assert device.action_calls == (dn_bot.ReplayDeviceCall("moveTo", (1, 2)),)


def test_trace_recorder_sanitizes_claim_and_action_before_version_one_write(tmp_path):
    path = tmp_path / "trace.json"
    recorder = TraceRecorder(path, retreat_destination="town")
    claim, action = _step_data()
    recorder.record_step(
        claim=claim,
        action=action,
        state_before=dn_bot.FarmState.PRE_DUNGEON,
        state_after=dn_bot.FarmState.ENTERING_DUNGEON,
        result=ReplayResult.SUCCESS,
    )
    recorder.flush()

    wire = json.loads(path.read_text(encoding="utf-8"))
    assert wire["version"] == 1
    assert wire["profile"] == "minotaur"
    step = wire["steps"][0]
    assert step["frame_id"] == "frame_000001"
    assert "text" not in step["claim"]
    assert "text" not in step["action"]
    assert step["action"]["coordinate"] == [500, 400]
    assert load_replay_trace(path).to_dict() == wire


def test_trace_recorder_uses_sequential_ids_and_preserves_destination(tmp_path):
    path = tmp_path / "trace.json"
    recorder = TraceRecorder(path, retreat_destination="stage_entrance")
    for state in (dn_bot.FarmState.PRE_DUNGEON, dn_bot.FarmState.ENTERING_DUNGEON):
        recorder.record_step(
            claim=dn_bot.FarmObservationClaim(state),
            action={"action": "wait"},
            state_before=state,
            state_after=state,
            result=ReplayResult.SUCCESS,
        )
    recorder.flush()

    trace = load_replay_trace(path)
    assert trace.retreat_destination == "stage_entrance"
    assert [step.frame_id for step in trace.steps] == [
        "frame_000001",
        "frame_000002",
    ]


def test_trace_recorder_writes_device_failure_with_partial_successful_calls(tmp_path):
    path = tmp_path / "trace.json"
    recorder = TraceRecorder(path, retreat_destination="town")
    device = TraceRecordingDevice(RecordingDevice())
    device.begin_action()
    device.moveTo(500, 400)
    recorder.record_step(
        claim=dn_bot.FarmObservationClaim(dn_bot.FarmState.ENTERING_DUNGEON),
        action={"action": "left_click", "coordinate": [500, 400]},
        state_before=dn_bot.FarmState.PRE_DUNGEON,
        state_after=dn_bot.FarmState.PRE_DUNGEON,
        device_calls=device.action_calls,
        result=ReplayResult.DEVICE_FAILURE,
    )
    recorder.flush()

    expected = load_replay_trace(path).steps[0].expected
    assert expected.result is ReplayResult.DEVICE_FAILURE
    assert expected.state_before is expected.state_after is dn_bot.FarmState.PRE_DUNGEON
    assert expected.device_calls == (dn_bot.ReplayDeviceCall("moveTo", (500, 400)),)


def test_trace_recorder_rejects_invalid_destination_at_construction(tmp_path):
    with pytest.raises(TraceRecordingError, match="DN_RETREAT_DESTINATION"):
        TraceRecorder(tmp_path / "trace.json", retreat_destination="unknown")


def test_trace_recorder_atomic_failure_keeps_previous_target_and_cleans_temp(tmp_path, monkeypatch):
    path = tmp_path / "trace.json"
    path.write_text("previous", encoding="utf-8")
    recorder = TraceRecorder(path, retreat_destination=None)
    recorder.record_step(
        claim=dn_bot.FarmObservationClaim(dn_bot.FarmState.PRE_DUNGEON),
        action={"action": "wait"},
        state_before=dn_bot.FarmState.PRE_DUNGEON,
        state_after=dn_bot.FarmState.PRE_DUNGEON,
        result=ReplayResult.SUCCESS,
    )

    def fail_replace(_source, _target):
        raise OSError("disk full")

    monkeypatch.setattr("dn_bot.recording.os.replace", fail_replace)
    with pytest.raises(TraceRecordingError, match="Trace gagal ditulis"):
        recorder.flush()

    assert path.read_text(encoding="utf-8") == "previous"
    assert list(tmp_path.glob(".trace.json.*.tmp")) == []


def test_load_trace_path_rejects_missing_parent_before_session(tmp_path):
    with pytest.raises(TraceRecordingError, match="Folder tujuan"):
        load_trace_path(tmp_path / "missing" / "trace.json")


def test_parse_args_accepts_record_trace():
    args = dn_bot.__main__._parse_args(
        ["--farm-profile", "minotaur", "--record-trace", "run.json"]
    )
    assert args.record_trace == "run.json"


def test_main_rejects_record_trace_without_minotaur_profile(tmp_path):
    with pytest.raises(SystemExit, match="membutuhkan --farm-profile minotaur"):
        dn_bot.__main__.main(["--record-trace", str(tmp_path / "trace.json")])


def test_recording_mode_propagates_api_failure_for_nonzero_cli_exit(tmp_path):
    path = tmp_path / "trace.json"
    with patch.dict(
        __import__("os").environ,
        {"OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client"), patch.object(
        dn_bot.orchestrator,
        "_call_openrouter",
        side_effect=RuntimeError("api down"),
    ), patch.object(
        dn_bot.orchestrator,
        "capture_screen_base64",
        return_value=SimpleNamespace(encoded="frame"),
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"):
        with pytest.raises(RuntimeError, match="api down"):
            dn_bot.run_dn_bot(
                "farm minotaur",
                max_steps=1,
                farm_profile=dn_bot.MINOTAUR_PROFILE,
                record_trace_path=path,
            )
    assert not path.exists()


def test_main_recording_safety_failure_returns_nonzero(tmp_path):
    path = tmp_path / "trace.json"
    with patch.object(dn_bot.__main__, "preflight_configuration"), patch.object(
        dn_bot.__main__.time, "sleep"
    ), patch.object(
        dn_bot.__main__,
        "run_dn_bot",
        side_effect=dn_bot.FarmSafetyStop("policy rejected"),
    ):
        with pytest.raises(SystemExit) as error:
            dn_bot.__main__.main(
                ["--farm-profile", "minotaur", "--record-trace", str(path)]
            )

    assert error.value.code == 1
    assert not path.exists()


def test_main_emits_recording_warning_and_passes_path(tmp_path, capsys):
    path = tmp_path / "trace.json"
    with patch.object(dn_bot.__main__, "preflight_configuration"), patch.object(
        dn_bot.__main__.time, "sleep"
    ), patch.object(dn_bot.__main__, "run_dn_bot") as run:
        dn_bot.__main__.main(
            ["--farm-profile", "minotaur", "--record-trace", str(path)]
        )

    output = capsys.readouterr().out
    assert "record-trace" in output
    assert "tidak menyimpan screenshot" in output
    assert run.call_args.kwargs["record_trace_path"] == str(path)
    assert run.call_args.kwargs["farm_profile"] is dn_bot.MINOTAUR_PROFILE


def test_recorded_real_session_round_trips_through_offline_replay(tmp_path, capture_region):
    path = tmp_path / "trace.json"
    frames = [
        capture_region(_REGION, encoded="frame-1"),
        capture_region(_REGION, encoded="frame-2"),
    ]
    replies = iter(
        [
            dn_bot.ModelReply(
                text="",
                tool_requests=[
                    dn_bot.ToolRequest(
                        id="call-1",
                        input={
                            "farm_state": "entering_dungeon",
                            "action": "left_click",
                            "coordinate": [500, 400],
                        },
                    )
                ],
            )
        ]
    )
    device = RecordingDevice()
    with patch.dict(
        __import__("os").environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client"), patch.object(
        dn_bot.orchestrator, "_call_openrouter", side_effect=lambda *args, **kwargs: next(replies)
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", side_effect=frames
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

    report = replay_trace(load_replay_trace(path))
    assert report.final_state is dn_bot.FarmState.ENTERING_DUNGEON
    assert report.device_calls == (("moveTo", (500, 400)), ("click", ()))


def test_dry_run_recording_never_calls_production_adapter(tmp_path, capture_region):
    path = tmp_path / "trace.json"
    frame = capture_region(_REGION, encoded="frame")
    reply = dn_bot.ModelReply(
        text="",
        tool_requests=[
            dn_bot.ToolRequest(
                id="call-1",
                input={
                    "farm_state": "entering_dungeon",
                    "action": "left_click",
                    "coordinate": [500, 400],
                },
            )
        ],
    )
    with patch.dict(
        __import__("os").environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client"), patch.object(
        dn_bot.orchestrator, "_call_openrouter", return_value=reply
    ), patch.object(dn_bot.orchestrator, "capture_screen_base64", return_value=frame), patch.object(
        dn_bot.orchestrator, "check_emergency_stop"
    ), patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control, "_safe_sleep"
    ), patch.object(dn_bot.device.pydirectinput, "moveTo") as move, patch.object(
        dn_bot.device.pydirectinput, "click"
    ) as click:
        dn_bot.run_dn_bot(
            "farm minotaur",
            max_steps=1,
            farm_profile=dn_bot.MINOTAUR_PROFILE,
            device=dn_bot.DryRunDevice(),
            record_trace_path=path,
        )

    move.assert_not_called()
    click.assert_not_called()
    assert load_replay_trace(path).steps[0].expected.result is ReplayResult.SUCCESS
