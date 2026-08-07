import json
import os
from types import SimpleNamespace
from unittest.mock import patch

import pytest

import dn_bot
import dn_bot.__main__
from conftest import RecordingDevice, _sdk_response, _sdk_tool_call


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


def test_observation_claim_is_not_authoritative_until_action_succeeds(
    capture_region,
):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768}, encoded="frame")
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **payload: _sdk_response(
                    tool_calls=[
                        _sdk_tool_call(
                            "call-1",
                            '{"action":"left_click","farm_state":"entering_dungeon","coordinate":[500,400]}',
                        )
                    ]
                )
            )
        )
    )
    watchdogs = []
    device = RecordingDevice()

    def build_watchdog(profile):
        watchdog = dn_bot.FarmWatchdog(profile)
        watchdogs.append(watchdog)
        return watchdog

    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client", return_value=client), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.orchestrator, "FarmWatchdog", side_effect=build_watchdog
    ), patch.object(
        dn_bot.orchestrator, "execute_game_action", side_effect=RuntimeError("device failed")
    ):
        with pytest.raises(RuntimeError, match="device failed"):
            dn_bot.run_dn_bot(
                "farm minotaur",
                max_steps=1,
                farm_profile=dn_bot.MINOTAUR_PROFILE,
                device=device,
            )

    assert len(watchdogs) == 1
    watchdog = watchdogs[0]
    assert watchdog.state is dn_bot.FarmState.PRE_DUNGEON

    claim = dn_bot.FarmObservationClaim.from_wire("entering_dungeon")
    assert watchdog.validate_claim(claim, "left_click") is dn_bot.FarmState.ENTERING_DUNGEON
    assert watchdog.state is dn_bot.FarmState.PRE_DUNGEON
    watchdog.advance(dn_bot.FarmState.ENTERING_DUNGEON, "left_click")
    assert watchdog.state is dn_bot.FarmState.ENTERING_DUNGEON


def test_orchestrator_commits_claim_after_successful_device(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768}, encoded="frame")
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **payload: _sdk_response(
                    tool_calls=[
                        _sdk_tool_call(
                            "call-1",
                            '{"action":"left_click","farm_state":"entering_dungeon","coordinate":[500,400]}',
                        )
                    ]
                )
            )
        )
    )
    watchdogs = []

    def build_watchdog(profile):
        watchdog = dn_bot.FarmWatchdog(profile)
        watchdogs.append(watchdog)
        return watchdog

    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client", return_value=client), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.orchestrator, "FarmWatchdog", side_effect=build_watchdog
    ), patch.object(dn_bot.orchestrator, "execute_game_action"):
        dn_bot.run_dn_bot(
            "farm minotaur",
            max_steps=1,
            farm_profile=dn_bot.MINOTAUR_PROFILE,
            device=RecordingDevice(),
        )

    assert len(watchdogs) == 1
    assert watchdogs[0].state is dn_bot.FarmState.ENTERING_DUNGEON


def test_observation_claim_rejects_unvalidated_state_object():
    with pytest.raises(dn_bot.FarmSafetyStop, match="Klaim state"):
        dn_bot.FarmObservationClaim("entering_dungeon")


def test_validate_legacy_wire_claim_delegates_to_claim_boundary():
    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE)
    assert (
        watchdog.validate("entering_dungeon", "left_click")
        is dn_bot.FarmState.ENTERING_DUNGEON
    )
    assert watchdog.state is dn_bot.FarmState.PRE_DUNGEON


def test_watchdog_accepts_documented_minotaur_flow():
    watchdog = dn_bot.FarmWatchdog(
        dn_bot.MINOTAUR_PROFILE, state_timeout_seconds=60, max_actions_without_transition=3
    )
    assert watchdog.state is dn_bot.FarmState.PRE_DUNGEON
    watchdog.validate_and_advance("entering_dungeon", "left_click")
    watchdog.validate_and_advance("combat", "press_move_key")
    watchdog.validate_and_advance("boss_reward", "wait")
    watchdog.validate_and_advance("loot_chest", "wait")
    watchdog.validate_and_advance("loot_result", "wait")
    watchdog.validate_and_advance("loot_result", "wait")
    watchdog.validate_and_advance("retreat_dialog", "press_action_key", "f12")
    watchdog.validate_and_advance(
        "return_wait", "left_click", "Town", coordinate=[700, 400]
    )
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
    assert watchdog.state is dn_bot.FarmState.RECOVERY


def test_recovery_requires_wait_before_returning_to_pre_dungeon():
    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE)
    watchdog.validate_and_advance("recovery", "wait")
    with pytest.raises(dn_bot.FarmSafetyStop, match="hanya boleh melaporkan pre_dungeon"):
        watchdog.validate_and_advance("pre_dungeon", "press_action_key", "f12")


def test_recovery_cannot_jump_directly_to_retreat_dialog():
    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE)
    watchdog.validate_and_advance("recovery", "wait")
    with pytest.raises(dn_bot.FarmSafetyStop, match="Transisi"):
        watchdog.validate_and_advance("retreat_dialog", "press_action_key", "f12")


def test_recovery_to_pre_dungeon_starts_a_fresh_action_budget():
    watchdog = dn_bot.FarmWatchdog(
        dn_bot.MINOTAUR_PROFILE,
        max_actions_per_run=2,
        state_timeout_seconds=60,
    )
    watchdog.validate_and_advance("recovery", "wait")
    watchdog.validate_and_advance("pre_dungeon", "wait")

    # Without resetting the failed run's budget, this transition would enter
    # recovery again instead of starting the next run.
    watchdog.validate_and_advance("entering_dungeon", "left_click")
    assert watchdog.state is dn_bot.FarmState.ENTERING_DUNGEON


def test_retreat_click_requires_a_coordinate_pair():
    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE)
    for state, action in [
        ("entering_dungeon", "left_click"),
        ("combat", "wait"),
        ("boss_reward", "wait"),
        ("loot_chest", "wait"),
        ("loot_result", "wait"),
    ]:
        watchdog.validate_and_advance(state, action)
    watchdog.validate_and_advance("loot_result", "wait")
    watchdog.validate_and_advance("retreat_dialog", "press_action_key", "f12")

    for coordinate in ([], [700], [700, 400, 1], [700.0, 400]):
        with pytest.raises(dn_bot.FarmSafetyStop, match="Town atau Stage Entrance"):
            watchdog.validate_and_advance(
                "return_wait", "left_click", "Town", coordinate=coordinate
            )


def test_run_budget_recovery_can_return_to_pre_dungeon():
    watchdog = dn_bot.FarmWatchdog(
        dn_bot.MINOTAUR_PROFILE,
        max_actions_per_run=1,
        state_timeout_seconds=60,
    )
    watchdog.validate_and_advance("entering_dungeon", "left_click")
    assert watchdog.state is dn_bot.FarmState.RECOVERY
    watchdog.validate_and_advance("recovery", "wait")
    watchdog.validate_and_advance("pre_dungeon", "wait")
    assert watchdog.state is dn_bot.FarmState.PRE_DUNGEON


def test_watchdog_recovery_counter_is_cumulative():
    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE, max_recovery_attempts=2)
    watchdog.validate_and_advance("recovery", "wait")
    watchdog.validate_and_advance("pre_dungeon", "wait")
    watchdog.validate_and_advance("recovery", "wait")
    watchdog.validate_and_advance("pre_dungeon", "wait")
    with pytest.raises(dn_bot.FarmSafetyStop, match="Recovery"):
        watchdog.validate_and_advance("recovery", "wait")


def test_watchdog_rejects_non_text_action():
    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE)
    with pytest.raises(dn_bot.FarmSafetyStop, match="bukan teks"):
        watchdog.validate_and_advance("pre_dungeon", None)


def test_watchdog_allows_bounded_recovery_after_action_budget():
    watchdog = dn_bot.FarmWatchdog(
        dn_bot.MINOTAUR_PROFILE,
        max_actions_without_transition=20,
        max_actions_per_run=1,
    )
    watchdog.validate_and_advance("entering_dungeon", "left_click")
    assert watchdog.state is dn_bot.FarmState.RECOVERY

    # The failed run budget must not block the recovery wait or its safe exit.
    watchdog.ensure_action_allowed(dn_bot.FarmState.RECOVERY)
    watchdog.validate_and_advance("recovery", "wait")
    watchdog.ensure_action_allowed(dn_bot.FarmState.PRE_DUNGEON)


def test_watchdog_stops_if_recovery_stalls():
    watchdog = dn_bot.FarmWatchdog(
        dn_bot.MINOTAUR_PROFILE,
        max_actions_without_transition=1,
        state_timeout_seconds=60,
    )
    watchdog.validate_and_advance("recovery", "wait")
    with pytest.raises(dn_bot.FarmSafetyStop, match="Recovery"):
        watchdog.validate_and_advance("recovery", "wait")


def test_watchdog_rejects_recovery_at_cumulative_limit_before_action():
    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE, max_recovery_attempts=1)
    watchdog.validate_and_advance("recovery", "wait")
    watchdog.validate_and_advance("pre_dungeon", "wait")
    with pytest.raises(dn_bot.FarmSafetyStop, match="Recovery"):
        watchdog.ensure_action_allowed(dn_bot.FarmState.RECOVERY)


def test_watchdog_enters_recovery_after_state_timeout():
    now = [0.0]
    watchdog = dn_bot.FarmWatchdog(
        dn_bot.MINOTAUR_PROFILE,
        state_timeout_seconds=5,
        clock=lambda: now[0],
    )
    now[0] = 5.0
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


def test_post_action_farm_safety_stop_is_not_wrapped_as_action_failure(capture_region):
    frame = capture_region(
        {"left": 0, "top": 0, "width": 1024, "height": 768}, encoded="frame"
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **payload: _sdk_response(
                    tool_calls=[
                        _sdk_tool_call(
                            "call-1",
                            '{"action":"wait","farm_state":"pre_dungeon"}',
                        )
                    ]
                )
            )
        )
    )
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(
        dn_bot.orchestrator, "get_openrouter_client", return_value=client
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.orchestrator, "execute_game_action"
    ), patch.object(
        dn_bot.orchestrator.FarmWatchdog,
        "advance",
        side_effect=dn_bot.FarmSafetyStop("post-action guard"),
    ):
        with pytest.raises(dn_bot.FarmSafetyStop, match="post-action guard"):
            dn_bot.run_dn_bot(
                "farm minotaur", max_steps=1, farm_profile=dn_bot.MINOTAUR_PROFILE
            )


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


def test_farm_exit_phases_enforce_golden_path_and_forbidden_actions():
    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE)
    for state, action in [
        ("entering_dungeon", "left_click"),
        ("combat", "wait"),
        ("boss_reward", "wait"),
        ("loot_chest", "wait"),
        ("loot_result", "wait"),
    ]:
        watchdog.validate_and_advance(state, action)

    with pytest.raises(dn_bot.FarmSafetyStop, match="tidak diizinkan"):
        watchdog.validate_and_advance(
            "loot_result", "left_click", coordinate=[650, 400]
        )

    # The first loot_result observation is not enough; a successful wait in
    # that state must settle the loot before F12 is accepted.
    with pytest.raises(dn_bot.FarmSafetyStop, match="Loot belum stabil"):
        watchdog.validate_and_advance("retreat_dialog", "press_action_key", "f12")
    watchdog.validate_and_advance("loot_result", "wait")
    with pytest.raises(dn_bot.FarmSafetyStop, match="tidak diizinkan"):
        watchdog.validate_and_advance("loot_result", "press_action_key", "f12")

    watchdog.validate_and_advance("retreat_dialog", "press_action_key", "f12")

    with pytest.raises(dn_bot.FarmSafetyStop, match="tidak boleh menekan F12"):
        watchdog.validate_and_advance("return_wait", "press_action_key", "f12")
    with pytest.raises(dn_bot.FarmSafetyStop, match="Town atau Stage Entrance"):
        watchdog.validate_and_advance(
            "return_wait", "left_click", coordinate=[650, 400]
        )
    with pytest.raises(dn_bot.FarmSafetyStop, match="Town atau Stage Entrance"):
        watchdog.validate_and_advance(
            "return_wait", "left_click", "Unknown", coordinate=[650, 400]
        )
    watchdog.validate_and_advance(
        "return_wait", "left_click", "Stage Entrance", coordinate=[650, 400]
    )

    with pytest.raises(dn_bot.FarmSafetyStop, match="tidak diizinkan"):
        watchdog.validate_and_advance(
            "pre_dungeon", "left_click", coordinate=[500, 400]
        )
    watchdog.validate_and_advance("pre_dungeon", "wait")


def test_retreat_dialog_rejects_unlabeled_same_state_click_and_allows_wait():
    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE)
    for state, action in [
        ("entering_dungeon", "left_click"),
        ("combat", "wait"),
        ("boss_reward", "wait"),
        ("loot_chest", "wait"),
        ("loot_result", "wait"),
    ]:
        watchdog.validate_and_advance(state, action)
    watchdog.validate_and_advance("loot_result", "wait")
    watchdog.validate_and_advance("retreat_dialog", "press_action_key", "f12")

    with pytest.raises(dn_bot.FarmSafetyStop, match="hanya boleh wait"):
        watchdog.validate_and_advance(
            "retreat_dialog", "left_click", "Town", coordinate=[650, 400]
        )
    with pytest.raises(dn_bot.FarmSafetyStop, match="Town/Stage Entrance"):
        watchdog.validate_and_advance(
            "retreat_dialog", "left_click", "other", coordinate=[650, 400]
        )
    watchdog.validate_and_advance("retreat_dialog", "wait")
    watchdog.validate_and_advance("retreat_dialog", "wait")


def test_farm_loop_executes_explicit_exit_phases_with_recorder(capture_region):
    frame = capture_region(
        {"left": 0, "top": 0, "width": 1024, "height": 768}, encoded="frame"
    )
    states = [
        ("entering_dungeon", "left_click", None, [500, 400]),
        ("combat", "wait", None, None),
        ("boss_reward", "wait", None, None),
        ("loot_chest", "wait", None, None),
        ("loot_result", "wait", None, None),
        ("loot_result", "wait", None, None),
        ("retreat_dialog", "press_action_key", "f12", None),
        ("return_wait", "left_click", "Town", [700, 400]),
        ("return_wait", "wait", None, None),
        ("pre_dungeon", "wait", None, None),
    ]
    responses = iter(
        [
            _sdk_response(
                tool_calls=[
                    _sdk_tool_call(
                        f"call-{index}",
                        json.dumps(
                            {
                                "action": action,
                                "farm_state": state,
                                **({"text": text} if text is not None else {}),
                                **(
                                    {"coordinate": coordinate}
                                    if coordinate is not None
                                    else {}
                                ),
                            }
                        ),
                    )
                ]
            )
            for index, (state, action, text, coordinate) in enumerate(states, 1)
        ]
    )
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(create=lambda **payload: next(responses))
        )
    )
    device = RecordingDevice()

    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(
        dn_bot.orchestrator, "get_openrouter_client", return_value=client
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        dn_bot.run_dn_bot(
            "farm minotaur",
            max_steps=len(states),
            farm_profile=dn_bot.MINOTAUR_PROFILE,
            device=device,
        )

    physical_calls = [call for call in device.calls if call[0] != "position"]
    assert physical_calls == [
        ("moveTo", (500, 400)),
        ("click", ()),
        ("keyDown", ("f12",)),
        ("keyUp", ("f12",)),
        ("moveTo", (700, 400)),
        ("click", ()),
    ]


def test_minotaur_policy_drives_watchdog_schema_and_prompt():
    policy = dn_bot.MINOTAUR_PHASE_POLICY
    profile = dn_bot.MINOTAUR_PROFILE

    with pytest.raises(TypeError):
        policy[dn_bot.FarmState.PRE_DUNGEON] = policy[dn_bot.FarmState.PRE_DUNGEON]
    assert profile.phase_policy is policy
    assert profile.allowed_actions == {
        state: phase.allowed_actions for state, phase in policy.items()
    }
    assert profile.transitions == {
        state: phase.transitions for state, phase in policy.items()
    }
    assert all(
        set(phase.actions_by_next_state) == set(phase.transitions)
        for phase in policy.values()
    )
    assert [
        state.value
        for state in policy
    ] == dn_bot.MINOTAUR_TOOL["function"]["parameters"]["properties"]["farm_state"]["enum"]
    assert list(dn_bot.farm_action_values()) == dn_bot.MINOTAUR_TOOL["function"]["parameters"]["properties"]["action"]["enum"]
    assert dn_bot.MINOTAUR_TOOL["function"]["parameters"]["properties"]["action"]["enum"] == list(
        dn_bot.DRAGON_NEST_TOOL["function"]["parameters"]["properties"]["action"]["enum"]
    )

    prompt = profile.system_prompt
    assert dn_bot.farm.farm_policy_prompt(policy) in prompt
    for state, phase in policy.items():
        assert state.value in prompt
        for action in phase.allowed_actions:
            assert action in prompt
        for target in phase.transitions:
            assert target.value in prompt
    assert "Town atau Stage Entrance" in prompt
    assert "requires a stable loot wait" in prompt


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
