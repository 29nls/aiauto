import pytest

import dn_bot


OFFICIAL_ACTIONS = frozenset(
    dn_bot.DRAGON_NEST_TOOL["function"]["parameters"]["properties"]["action"][
        "enum"
    ]
)
_POLICY_ACTION_CASES = tuple(
    (source, target, action)
    for source, phase in dn_bot.MINOTAUR_PHASE_POLICY.items()
    for target, actions in phase.actions_by_next_state.items()
    for action in sorted(actions)
)


def _watchdog_at_loot_result(*, retreat_destination=None):
    watchdog = dn_bot.FarmWatchdog(
        dn_bot.MINOTAUR_PROFILE,
        retreat_destination=retreat_destination,
    )
    for state, action in (
        ("entering_dungeon", "left_click"),
        ("combat", "wait"),
        ("boss_reward", "wait"),
        ("loot_chest", "wait"),
        ("loot_result", "wait"),
    ):
        watchdog.validate_and_advance(state, action)
    return watchdog


def _watchdog_at_retreat_dialog(*, retreat_destination=None):
    watchdog = _watchdog_at_loot_result(
        retreat_destination=retreat_destination,
    )
    watchdog.validate_and_advance("loot_result", "wait")
    watchdog.validate_and_advance("retreat_dialog", "press_action_key", "f12")
    return watchdog


def test_minotaur_policy_covers_only_real_states_and_official_actions():
    policy = dn_bot.MINOTAUR_PHASE_POLICY

    assert set(policy) == set(dn_bot.FarmState)
    assert all(isinstance(state, dn_bot.FarmState) for state in policy)
    for phase in policy.values():
        assert set(phase.actions_by_next_state) == set(phase.transitions)
        assert all(isinstance(target, dn_bot.FarmState) for target in phase.transitions)
        assert all(phase.actions_by_next_state[target] for target in phase.transitions)
        assert phase.allowed_actions <= OFFICIAL_ACTIONS

    assert set(dn_bot.farm_action_values()) == OFFICIAL_ACTIONS
    assert set(
        dn_bot.MINOTAUR_TOOL["function"]["parameters"]["properties"]["action"][
            "enum"
        ]
    ) == OFFICIAL_ACTIONS
    assert set(
        dn_bot.MINOTAUR_TOOL["function"]["parameters"]["properties"]["farm_state"][
            "enum"
        ]
    ) == {state.value for state in policy}


def test_each_policy_action_passes_the_executable_action_boundary(capture_region):
    frame = capture_region(
        {"left": 0, "top": 0, "width": 1024, "height": 768},
        encoded="policy-actions",
    )
    payloads = {
        "mouse_move": {"coordinate": [500, 400]},
        "left_click": {"coordinate": [500, 400]},
        "right_click": {"coordinate": [500, 400]},
        "press_move_key": {"text": "w"},
        "press_action_key": {"text": "f12"},
        "move_camera": {"coordinate": [500, 400]},
        "wait": {},
    }
    with pytest.MonkeyPatch.context() as monkeypatch:
        monkeypatch.setattr(dn_bot.input_control, "check_target_window", lambda: None)
        monkeypatch.setattr(dn_bot.input_control, "_safe_sleep", lambda *args, **kwargs: None)
        for action in sorted(OFFICIAL_ACTIONS):
            device = dn_bot.DryRunDevice()
            dn_bot.execute_game_action(
                action,
                frame=frame,
                device=device,
                **payloads[action],
            )


@pytest.mark.parametrize("source,target,action", _POLICY_ACTION_CASES)
def test_every_policy_transition_action_passes_claim_validation(source, target, action):
    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE)
    watchdog.state = source
    if source is dn_bot.FarmState.LOOT_RESULT and action == "press_action_key":
        watchdog._loot_result_stabilized = True

    text = "f12" if action == "press_action_key" else None
    if source is dn_bot.FarmState.RETREAT_DIALOG and target is dn_bot.FarmState.RETURN_WAIT:
        text = "Town"
    coordinate = [700, 400] if text == "Town" else None
    assert watchdog.validate_claim(
        dn_bot.FarmObservationClaim(target, text=text, coordinate=coordinate),
        action,
    ) is target


def test_minotaur_policy_metadata_is_attached_only_to_the_relevant_phases():
    policy = dn_bot.MINOTAUR_PHASE_POLICY

    for state, phase in policy.items():
        if state is dn_bot.FarmState.LOOT_RESULT:
            assert phase.required_key == "f12"
            assert phase.requires_stable_wait is True
        else:
            assert not phase.requires_stable_wait

        if state is dn_bot.FarmState.RETREAT_DIALOG:
            assert phase.click_labels == ("town", "stage entrance")
            assert phase.coordinate_required is True
        else:
            assert not phase.click_labels
            assert phase.coordinate_required is False


def test_rendered_minotaur_prompt_contains_the_complete_policy():
    policy_text = dn_bot.farm.farm_policy_prompt(dn_bot.MINOTAUR_PHASE_POLICY)
    prompt = dn_bot.MINOTAUR_PROFILE.system_prompt

    assert policy_text in prompt
    for state, phase in dn_bot.MINOTAUR_PHASE_POLICY.items():
        assert f"- {state.value}:" in policy_text
        for action in phase.allowed_actions:
            assert action in policy_text
        for target in phase.transitions:
            assert target.value in policy_text


def test_loot_result_requires_one_successful_wait_and_rejects_duplicate_f12():
    watchdog = _watchdog_at_loot_result()

    with pytest.raises(dn_bot.FarmSafetyStop, match="Loot belum stabil"):
        watchdog.validate_and_advance("retreat_dialog", "press_action_key", "f12")
    assert watchdog.state is dn_bot.FarmState.LOOT_RESULT

    watchdog.validate_and_advance("loot_result", "wait")
    watchdog.validate_and_advance("retreat_dialog", "press_action_key", "f12")

    with pytest.raises(dn_bot.FarmSafetyStop, match="tidak boleh menekan F12"):
        watchdog.validate_and_advance("retreat_dialog", "press_action_key", "f12")
    assert watchdog.state is dn_bot.FarmState.RETREAT_DIALOG


@pytest.mark.parametrize(
    "destination,label",
    [("town", "Town"), ("stage_entrance", "Stage Entrance")],
)
def test_retreat_dialog_accepts_only_configured_label_and_valid_coordinate(
    destination, label
):
    watchdog = _watchdog_at_retreat_dialog(retreat_destination=destination)
    assert (
        watchdog.validate(
            "return_wait",
            "left_click",
            label,
            coordinate=[700, 400],
        )
        is dn_bot.FarmState.RETURN_WAIT
    )


@pytest.mark.parametrize(
    "destination,label,coordinate",
    [
        ("town", "Stage Entrance", [700, 400]),
        ("stage_entrance", "Town", [700, 400]),
        ("town", "Town", None),
        ("town", "Town", [1024, 400]),
        ("town", "Town", [700, 768]),
        ("town", "Town", [700.0, 400]),
    ],
)
def test_retreat_dialog_fails_closed_for_destination_or_coordinate_mismatch(
    destination, label, coordinate
):
    watchdog = _watchdog_at_retreat_dialog(retreat_destination=destination)

    with pytest.raises(dn_bot.FarmSafetyStop):
        watchdog.validate("return_wait", "left_click", label, coordinate=coordinate)
    assert watchdog.state is dn_bot.FarmState.RETREAT_DIALOG


@pytest.mark.parametrize("target", list(dn_bot.MINOTAUR_PHASE_POLICY[dn_bot.FarmState.RETREAT_DIALOG].transitions))
def test_retreat_dialog_never_accepts_f12(target):
    watchdog = _watchdog_at_retreat_dialog()

    with pytest.raises(dn_bot.FarmSafetyStop, match="tidak boleh menekan F12"):
        watchdog.validate_claim(
            dn_bot.FarmObservationClaim(target),
            "press_action_key",
        )


@pytest.mark.parametrize("action", sorted(OFFICIAL_ACTIONS - {"wait"}))
def test_return_wait_is_wait_only(action):
    watchdog = _watchdog_at_retreat_dialog()
    watchdog.validate_and_advance(
        "return_wait",
        "left_click",
        "Town",
        coordinate=[700, 400],
    )

    with pytest.raises(dn_bot.FarmSafetyStop):
        watchdog.validate_claim(
            dn_bot.FarmObservationClaim(dn_bot.FarmState.RETURN_WAIT),
            action,
        )


def test_every_return_wait_target_allows_only_wait():
    phase = dn_bot.MINOTAUR_PHASE_POLICY[dn_bot.FarmState.RETURN_WAIT]
    assert set(phase.transitions) == {
        dn_bot.FarmState.RETURN_WAIT,
        dn_bot.FarmState.PRE_DUNGEON,
        dn_bot.FarmState.RECOVERY,
    }
    assert all(actions == frozenset({"wait"}) for actions in phase.actions_by_next_state.values())


def test_recovery_matrix_requires_wait_for_safe_exit_and_allows_bounded_f12():
    policy = dn_bot.MINOTAUR_PHASE_POLICY[dn_bot.FarmState.RECOVERY]
    assert policy.actions_by_next_state[dn_bot.FarmState.RECOVERY] == frozenset(
        {"press_action_key", "wait"}
    )
    assert policy.actions_by_next_state[dn_bot.FarmState.PRE_DUNGEON] == frozenset(
        {"wait"}
    )

    watchdog = dn_bot.FarmWatchdog(dn_bot.MINOTAUR_PROFILE)
    watchdog.validate_and_advance("recovery", "wait")
    watchdog.validate_and_advance("recovery", "press_action_key", "f12")
    watchdog.validate_and_advance("pre_dungeon", "wait")
    assert watchdog.state is dn_bot.FarmState.PRE_DUNGEON

    with pytest.raises(dn_bot.FarmSafetyStop):
        watchdog.validate_claim(
            dn_bot.FarmObservationClaim(dn_bot.FarmState.PRE_DUNGEON),
            "press_action_key",
        )
