import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import dn_bot
from conftest import _sdk_response, _sdk_tool_call


def test_f12_is_allowlisted_and_executes_through_action_seam(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    device = dn_bot.device.DryRunDevice()
    with patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control, "_safe_sleep"
    ):
        dn_bot.execute_game_action(
            "press_action_key", text="f12", frame=frame, device=device
        )
    assert ("keyDown", ("f12",)) in device.calls
    assert ("keyUp", ("f12",)) in device.calls


def test_watchdog_accepts_documented_minotaur_flow():
    watchdog = dn_bot.FarmWatchdog(
        dn_bot.MINOTAUR_PROFILE, state_timeout_seconds=60, max_actions_without_transition=3
    )
    assert watchdog.state is dn_bot.FarmState.PRE_DUNGEON
    watchdog.validate_and_advance("entering_dungeon", "left_click")
    watchdog.validate_and_advance("combat", "press_move_key")
    watchdog.validate_and_advance("boss_reward", "wait")
    watchdog.validate_and_advance("loot_chest", "wait")
    watchdog.validate_and_advance("loot_result", "left_click")
    watchdog.validate_and_advance("return_navigation", "press_action_key", "f12")
    watchdog.validate_and_advance("pre_dungeon", "wait")
    assert watchdog.state is dn_bot.FarmState.PRE_DUNGEON


def test_watchdog_rejects_illegal_transition_and_action():
    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE)
    with pytest.raises(dn_bot.FarmSafetyStop, match="Transisi"):
        watchdog.validate_and_advance("combat", "wait")

    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE)
    with pytest.raises(dn_bot.FarmSafetyStop, match="tidak diizinkan"):
        watchdog.validate_and_advance("pre_dungeon", "press_move_key")


def test_watchdog_enters_recovery_after_repeated_no_progress():
    watchdog = dn_bot.FarmWatchdog(
        dn_bot.MINOTAUR_PROFILE,
        max_actions_without_transition=2,
        state_timeout_seconds=60,
    )
    watchdog.validate_and_advance("pre_dungeon", "wait")
    watchdog.validate_and_advance("pre_dungeon", "wait")
    watchdog.validate_and_advance("pre_dungeon", "wait")
    assert watchdog.state is dn_bot.FarmState.RECOVERY


def test_watchdog_stops_if_recovery_stalls():
    watchdog = dn_bot.FarmWatchdog(
        dn_bot.MINOTAUR_PROFILE,
        max_actions_without_transition=1,
        state_timeout_seconds=60,
    )
    watchdog.validate_and_advance("recovery", "wait")
    watchdog.validate_and_advance("recovery", "wait")
    with pytest.raises(dn_bot.FarmSafetyStop, match="Recovery"):
        watchdog.validate_and_advance("recovery", "wait")


def test_watchdog_enters_recovery_after_state_timeout():
    now = [0.0]
    watchdog = dn_bot.FarmWatchdog(
        dn_bot.MINOTAUR_PROFILE,
        state_timeout_seconds=5,
        clock=lambda: now[0],
    )
    now[0] = 6.0
    watchdog.check()
    assert watchdog.state is dn_bot.FarmState.RECOVERY


def test_farm_cli_requires_profile_for_until_stopped():
    with pytest.raises(SystemExit, match="membutuhkan --farm-profile"):
        dn_bot.__main__.main(["--until-stopped"])


def test_farm_cli_propagates_profile_and_until_stopped():
    with patch.object(dn_bot.__main__, "preflight_configuration"), patch.object(
        dn_bot.__main__.time, "sleep"
    ), patch.object(dn_bot.__main__, "run_dn_bot") as run:
        dn_bot.__main__.main(["--farm-profile", "minotaur", "--until-stopped", "--dry-run"])
    assert run.call_args.kwargs["farm_profile"] is dn_bot.MINOTAUR_PROFILE
    assert run.call_args.kwargs["until_stopped"] is True
    assert isinstance(run.call_args.kwargs["device"], dn_bot.DryRunDevice)


def test_farm_loop_requires_farm_state_and_uses_extended_prompt(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768}, encoded="frame")
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **payload: _sdk_response(content="selesai")
            )
        )
    )
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client", return_value=client), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"):
        with pytest.raises(dn_bot.FarmSafetyStop, match="tidak mengirim aksi/state"):
            dn_bot.run_dn_bot(
                "farm minotaur", max_steps=1, farm_profile=dn_bot.MINOTAUR_PROFILE
            )


def test_minotaur_tool_requires_farm_state():
    parameters = dn_bot.MINOTAUR_TOOL["function"]["parameters"]
    assert "farm_state" in parameters["properties"]
    assert parameters["required"] == ["action", "farm_state"]


def test_farm_loop_accepts_state_and_sends_f12_transition(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768}, encoded="frame")
    responses = iter(
        [
            _sdk_response(
                tool_calls=[
                    _sdk_tool_call(
                        "call-1",
                        '{"action":"wait","farm_state":"pre_dungeon"}',
                    )
                ]
            ),
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **payload: next(responses))
        )
    )
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client", return_value=client), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", side_effect=[frame, frame]
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.orchestrator, "execute_game_action"
    ) as execute:
        dn_bot.run_dn_bot(
            "farm minotaur", max_steps=1, farm_profile=dn_bot.MINOTAUR_PROFILE
        )
    execute.assert_called_once()
