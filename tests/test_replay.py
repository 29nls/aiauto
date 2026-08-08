import json

import pytest

import dn_bot
from dn_bot.replay import (
    ReplayDeviceCall,
    ReplayExpected,
    ReplayMismatch,
    ReplayResult,
    ReplayTrace,
    ReplayTraceError,
    ReplayStep,
    replay_trace,
)


def _step(frame_id, state, action, *, text=None, coordinate=None, before=None, after=None, calls=(), result="success"):
    if before is None:
        before = state
    if after is None:
        after = state
    return {
        "frame_id": frame_id,
        "claim": {"farm_state": state, "text": text, "coordinate": coordinate},
        "action": {"action": action, "text": text, "coordinate": coordinate},
        "expected": {
            "state_before": before,
            "state_after": after,
            "device_calls": [
                {"method": method, "args": list(args)} for method, args in calls
            ],
            "result": result,
        },
    }


def _trace(*steps, retreat_destination=None):
    return {
        "version": 1,
        "profile": "minotaur",
        "retreat_destination": retreat_destination,
        "steps": list(steps),
    }


def test_replay_runs_golden_path_without_openai_or_physical_input():
    steps = [
        _step("enter", "entering_dungeon", "left_click", coordinate=[500, 400], before="pre_dungeon", after="entering_dungeon", calls=(("moveTo", (500, 400)), ("click", ()))),
        _step("combat", "combat", "wait", before="entering_dungeon", after="combat"),
        _step("reward", "boss_reward", "wait", before="combat", after="boss_reward"),
        _step("chest", "loot_chest", "wait", before="boss_reward", after="loot_chest"),
        _step("loot", "loot_result", "wait", before="loot_chest", after="loot_result"),
        _step("loot-stable", "loot_result", "wait", before="loot_result", after="loot_result"),
        _step("dialog", "retreat_dialog", "press_action_key", text="f12", before="loot_result", after="retreat_dialog", calls=(("keyDown", ("f12",)), ("keyUp", ("f12",)))),
        _step("return", "return_wait", "left_click", text="Town", coordinate=[700, 400], before="retreat_dialog", after="return_wait", calls=(("moveTo", (700, 400)), ("click", ()))),
        _step("ready", "pre_dungeon", "wait", before="return_wait", after="pre_dungeon"),
    ]

    report = replay_trace(_trace(*steps, retreat_destination="town"))

    assert report.steps_replayed == len(steps)
    assert report.final_state is dn_bot.FarmState.PRE_DUNGEON
    assert ("keyDown", ("f12",)) in report.device_calls


def test_replay_rejects_invalid_claim_and_action_without_device_calls():
    invalid_claim = _trace(_step("bad", "not_a_state", "wait", before="pre_dungeon", after="pre_dungeon"))
    with pytest.raises(ReplayTraceError, match="state farming"):
        replay_trace(invalid_claim)

    # press_action_key is now legal in pre_dungeon; use an action that is
    # still forbidden (right_click is not in pre_dungeon's allowed set).
    invalid_action = _trace(_step("bad-action", "pre_dungeon", "right_click"))
    with pytest.raises(dn_bot.FarmSafetyStop):
        replay_trace(invalid_action)


def test_replay_device_failure_preserves_authoritative_state():
    trace = _trace(
        _step(
            "failed-enter",
            "entering_dungeon",
            "left_click",
            coordinate=[500, 400],
            before="pre_dungeon",
            after="pre_dungeon",
            result="device_failure",
        )
    )

    report = replay_trace(trace)

    assert report.final_state is dn_bot.FarmState.PRE_DUNGEON
    assert report.device_calls == ()

    # A multi primitive action can fail after its first call. The replay still
    # refuses to commit the claimed state and records the partial device trace.
    partial = _trace(
        _step(
            "failed-click",
            "entering_dungeon",
            "left_click",
            coordinate=[500, 400],
            before="pre_dungeon",
            after="pre_dungeon",
            calls=(("moveTo", (500, 400)),),
            result="device_failure",
        )
    )
    partial_report = replay_trace(partial)
    assert partial_report.final_state is dn_bot.FarmState.PRE_DUNGEON
    assert partial_report.device_calls == (("moveTo", (500, 400)),)


def test_replay_fault_is_private_and_not_a_real_emergency_stop():
    from dn_bot.replay import _ReplayDeviceFailure

    assert not issubclass(_ReplayDeviceFailure, dn_bot.EmergencyStop)
    assert not isinstance(_ReplayDeviceFailure("test"), dn_bot.EmergencyStop)


def test_real_emergency_stop_is_not_translated_by_replay(monkeypatch):
    trace = _trace(_step("operator-stop", "pre_dungeon", "wait"))
    stop = dn_bot.EmergencyStop("operator stop")

    def raise_stop(*args, **kwargs):
        raise stop

    monkeypatch.setattr(dn_bot.replay, "execute_game_action", raise_stop)
    with pytest.raises(dn_bot.EmergencyStop) as error:
        replay_trace(trace)
    assert error.value is stop


def test_replay_fault_still_uses_safety_wrapper_without_becoming_public_fault():
    from dn_bot.replay import ReplayDevice, _ReplayDeviceFailure

    device = ReplayDevice()
    device.fail_before_first_primitive()
    with pytest.raises(dn_bot.EmergencyStop) as error:
        dn_bot.check_emergency_stop(device)
    assert not isinstance(error.value, _ReplayDeviceFailure)
    assert isinstance(error.value.__cause__, _ReplayDeviceFailure)


@pytest.mark.parametrize(
    "action,action_fields",
    [
        ("wait", {}),
        ("left_click", {"coordinate": [500, 400]}),
    ],
    ids=["wait-position-check", "click-position-check"],
)
def test_replay_zero_call_device_failure_fails_before_first_primitive(
    action, action_fields
):
    trace = _trace(
        _step(
            "position-failure",
            "pre_dungeon",
            action,
            before="pre_dungeon",
            after="pre_dungeon",
            calls=(),
            result="device_failure",
            **action_fields,
        )
    )

    report = replay_trace(trace)

    assert report.final_state is dn_bot.FarmState.PRE_DUNGEON
    assert report.device_calls == ()


def test_zero_call_failure_preserves_state_for_following_replay_step():
    trace = _trace(
        _step(
            "position-failure",
            "pre_dungeon",
            "wait",
            before="pre_dungeon",
            after="pre_dungeon",
            calls=(),
            result="device_failure",
        ),
        _step(
            "enter-after-failure",
            "entering_dungeon",
            "left_click",
            coordinate=[500, 400],
            before="pre_dungeon",
            after="entering_dungeon",
            calls=(("moveTo", (500, 400)), ("click", ())),
        ),
    )

    report = replay_trace(trace)

    assert report.steps_replayed == 2
    assert report.final_state is dn_bot.FarmState.ENTERING_DUNGEON
    assert report.device_calls == (
        ("moveTo", (500, 400)),
        ("click", ()),
    )


def test_replay_rejects_zero_call_failure_that_changes_state():
    trace = _trace(
        _step(
            "invalid-failure-state",
            "entering_dungeon",
            "left_click",
            coordinate=[500, 400],
            before="pre_dungeon",
            after="entering_dungeon",
            calls=(),
            result="device_failure",
        )
    )

    with pytest.raises(ReplayTraceError, match="device_failure"):
        replay_trace(trace)


def test_replay_enforces_loot_stability_and_retreat_destination():
    first = _trace(
        _step("enter", "entering_dungeon", "left_click", coordinate=[500, 400], before="pre_dungeon", after="entering_dungeon", calls=(("moveTo", (500, 400)), ("click", ()))),
        _step("combat", "combat", "wait", before="entering_dungeon", after="combat"),
        _step("reward", "boss_reward", "wait", before="combat", after="boss_reward"),
        _step("chest", "loot_chest", "wait", before="boss_reward", after="loot_chest"),
        _step("loot", "loot_result", "wait", before="loot_chest", after="loot_result"),
        _step("early-f12", "retreat_dialog", "press_action_key", text="f12", before="loot_result", after="loot_result"),
    )
    with pytest.raises(dn_bot.FarmSafetyStop, match="Loot belum stabil"):
        replay_trace(first)

    mismatch = _trace(
        _step("enter", "entering_dungeon", "left_click", coordinate=[500, 400], before="pre_dungeon", after="entering_dungeon", calls=(("moveTo", (500, 400)), ("click", ()))),
        _step("combat", "combat", "wait", before="entering_dungeon", after="combat"),
        _step("reward", "boss_reward", "wait", before="combat", after="boss_reward"),
        _step("chest", "loot_chest", "wait", before="boss_reward", after="loot_chest"),
        _step("loot", "loot_result", "wait", before="loot_chest", after="loot_result"),
        _step("stable", "loot_result", "wait", before="loot_result", after="loot_result"),
        _step("dialog", "retreat_dialog", "press_action_key", text="f12", before="loot_result", after="retreat_dialog", calls=(("keyDown", ("f12",)), ("keyUp", ("f12",)))),
        _step("wrong-town", "return_wait", "left_click", text="Town", coordinate=[700, 400], before="retreat_dialog", after="retreat_dialog"),
        retreat_destination="stage_entrance",
    )
    with pytest.raises(dn_bot.FarmSafetyStop, match="konfigurasi operator"):
        replay_trace(mismatch)


def test_replay_preserves_recovery_budget_behavior():
    trace = _trace(
        _step("recover", "recovery", "wait", before="pre_dungeon", after="recovery"),
        _step("ready", "pre_dungeon", "wait", before="recovery", after="pre_dungeon"),
    )
    report = replay_trace(trace)
    assert report.final_state is dn_bot.FarmState.PRE_DUNGEON

    exhausted = _trace(
        _step("recover-1", "recovery", "wait", before="pre_dungeon", after="recovery"),
        _step("ready-1", "pre_dungeon", "wait", before="recovery", after="pre_dungeon"),
        _step("recover-2", "recovery", "wait", before="pre_dungeon", after="recovery"),
        _step("ready-2", "pre_dungeon", "wait", before="recovery", after="pre_dungeon"),
        _step("recover-3", "recovery", "wait", before="pre_dungeon", after="recovery"),
    )
    with pytest.raises(dn_bot.FarmSafetyStop, match="Recovery"):
        replay_trace(exhausted)


def test_replay_expected_dataclasses_round_trip_to_version_one_wire_shape():
    expected = ReplayExpected(
        state_before=dn_bot.FarmState.PRE_DUNGEON,
        state_after=dn_bot.FarmState.ENTERING_DUNGEON,
        device_calls=(ReplayDeviceCall("moveTo", (500, 400)), ReplayDeviceCall("click", ())),
        result=ReplayResult.SUCCESS,
    )
    step = ReplayStep(
        "typed",
        {"farm_state": "entering_dungeon", "text": None, "coordinate": [500, 400]},
        {"action": "left_click", "text": None, "coordinate": [500, 400]},
        expected,
    )
    trace = ReplayTrace((step,))

    wire = trace.to_dict()
    assert wire["version"] == 1
    assert wire["steps"][0]["expected"] == {
        "state_before": "pre_dungeon",
        "state_after": "entering_dungeon",
        "device_calls": [
            {"method": "moveTo", "args": [500, 400]},
            {"method": "click", "args": []},
        ],
        "result": "success",
    }
    assert ReplayTrace.from_dict(wire).to_dict() == wire


def test_replay_rejects_malformed_direct_typed_objects_before_execution():
    with pytest.raises(ReplayTraceError):
        ReplayDeviceCall("keyDown", ("Alice",))
    with pytest.raises(ReplayTraceError):
        ReplayExpected(
            state_before=dn_bot.FarmState.PRE_DUNGEON,
            state_after=dn_bot.FarmState.COMBAT,
            device_calls=(),
            result=ReplayResult.DEVICE_FAILURE,
        )
    with pytest.raises(ReplayTraceError):
        ReplayTrace((object(),))
    valid_step = ReplayStep(
        "same",
        {"farm_state": "pre_dungeon", "text": None, "coordinate": None},
        {"action": "wait", "text": None, "coordinate": None},
        ReplayExpected(
            dn_bot.FarmState.PRE_DUNGEON,
            dn_bot.FarmState.PRE_DUNGEON,
            (),
            ReplayResult.SUCCESS,
        ),
    )
    with pytest.raises(ReplayTraceError, match="duplikat"):
        ReplayTrace((valid_step, valid_step)).to_dict()


def test_replay_schema_is_versioned_and_rejects_secret_or_unknown_fields(tmp_path):
    trace = _trace(_step("one", "pre_dungeon", "wait"))
    parsed = ReplayTrace.from_dict(trace)
    assert parsed.to_dict()["version"] == 1
    assert parsed.to_dict()["steps"][0]["frame_id"] == "one"

    bad_version = dict(trace, version=2)
    with pytest.raises(ReplayTraceError, match="Versi"):
        ReplayTrace.from_dict(bad_version)

    bad_field = dict(trace, api_key="secret")
    with pytest.raises(ReplayTraceError, match="schema"):
        ReplayTrace.from_dict(bad_field)

    for field in ("claim", "action"):
        unsafe = _step("unsafe", "pre_dungeon", "wait", text="sk-or-v1-secret")
        unsafe["claim" if field == "claim" else "action"]["text"] = "sk-or-v1-secret"
        with pytest.raises(ReplayTraceError, match="token workflow"):
            ReplayTrace.from_dict(_trace(unsafe))

    personal = _step("personal", "pre_dungeon", "wait", text="Alice")
    with pytest.raises(ReplayTraceError, match="token workflow"):
        ReplayTrace.from_dict(_trace(personal))

    bad_state = _trace(_step("bad-state", "pre_dungeon", "wait", before="not_a_state"))
    with pytest.raises(ReplayTraceError, match="state farming"):
        ReplayTrace.from_dict(bad_state)
    bad_claim_state = _trace(_step("bad-claim", "pre_dungeon", "wait"))
    bad_claim_state["steps"][0]["claim"]["farm_state"] = "not_a_state"
    with pytest.raises(ReplayTraceError, match="state farming"):
        ReplayTrace.from_dict(bad_claim_state)

    bad_call = _trace(
        {**_step("bad-call", "pre_dungeon", "wait"), "expected": {
            "state_before": "pre_dungeon", "state_after": "pre_dungeon",
            "device_calls": [{"method": "keyDown", "args": ["Alice"]}],
            "result": "success",
        }}
    )
    with pytest.raises(ReplayTraceError, match="device_call args"):
        ReplayTrace.from_dict(bad_call)

    missing_claim_field = _trace(
        {**_step("missing", "pre_dungeon", "wait"), "claim": {"text": None, "coordinate": None}}
    )
    with pytest.raises(ReplayTraceError, match="farm_state"):
        ReplayTrace.from_dict(missing_claim_field)

    path = tmp_path / "trace.json"
    path.write_text(json.dumps(trace), encoding="utf-8")
    assert ReplayTrace.from_dict(json.loads(path.read_text(encoding="utf-8"))).profile == "minotaur"


# These are hand-authored replay contracts. The expected primitive calls are
# deliberately written here instead of being obtained from the action runner.
_POLICY_REPLAY_EDGE_CASES = (
    pytest.param("pre-stays-wait", "pre_dungeon", "pre_dungeon", "wait", None, None, (), "town", id="pre-stays-wait"),
    pytest.param("pre-enters-click", "pre_dungeon", "entering_dungeon", "left_click", None, [500, 400], (("moveTo", (500, 400)), ("click", ())), "town", id="pre-enters-click"),
    pytest.param("pre-recovers-wait", "pre_dungeon", "recovery", "wait", None, None, (), "town", id="pre-recovers-wait"),
    pytest.param("pre-same-left-click", "pre_dungeon", "pre_dungeon", "left_click", None, [500, 400], (("moveTo", (500, 400)), ("click", ())), "town", id="pre-same-left-click"),
    pytest.param("pre-enters-mouse-move", "pre_dungeon", "entering_dungeon", "mouse_move", None, [500, 400], (("moveTo", (500, 400)),), "town", id="pre-enters-mouse-move"),
    pytest.param("pre-recovers-left-click", "pre_dungeon", "recovery", "left_click", None, [500, 400], (("moveTo", (500, 400)), ("click", ())), "town", id="pre-recovers-left-click"),
    pytest.param("pre-same-mouse-move", "pre_dungeon", "pre_dungeon", "mouse_move", None, [500, 400], (("moveTo", (500, 400)),), "town", id="pre-same-mouse-move"),
    pytest.param("entering-stays-wait", "entering_dungeon", "entering_dungeon", "wait", None, None, (), "town", id="entering-stays-wait"),
    pytest.param("entering-same-right-click", "entering_dungeon", "entering_dungeon", "right_click", None, [500, 400], (("moveTo", (500, 400)), ("rightClick", ())), "town", id="entering-same-right-click"),
    pytest.param("entering-same-press-move-key", "entering_dungeon", "entering_dungeon", "press_move_key", "w", None, (("keyDown", ("w",)), ("keyUp", ("w",))), "town", id="entering-same-press-move-key"),
    pytest.param("entering-same-press-action-key", "entering_dungeon", "entering_dungeon", "press_action_key", "f12", None, (("keyDown", ("f12",)), ("keyUp", ("f12",))), "town", id="entering-same-press-action-key"),
    pytest.param("entering-same-move-camera", "entering_dungeon", "entering_dungeon", "move_camera", None, [500, 400], (("moveTo", (512, 384)), ("moveTo", (500, 400))), "town", id="entering-same-move-camera"),
    pytest.param("entering-same-left-click", "entering_dungeon", "entering_dungeon", "left_click", None, [500, 400], (("moveTo", (500, 400)), ("click", ())), "town", id="entering-same-left-click"),
    pytest.param("entering-same-mouse-move", "entering_dungeon", "entering_dungeon", "mouse_move", None, [500, 400], (("moveTo", (500, 400)),), "town", id="entering-same-mouse-move"),
    pytest.param("entering-combat-wait", "entering_dungeon", "combat", "wait", None, None, (), "town", id="entering-combat-wait"),
    pytest.param("entering-combat-move-camera", "entering_dungeon", "combat", "move_camera", None, [500, 400], (("moveTo", (512, 384)), ("moveTo", (500, 400))), "town", id="entering-combat-move-camera"),
    pytest.param("entering-recovery-press-move-key", "entering_dungeon", "recovery", "press_move_key", "w", None, (("keyDown", ("w",)), ("keyUp", ("w",))), "town", id="entering-recovery-press-move-key"),
    pytest.param("combat-stays-wait", "combat", "combat", "wait", None, None, (), "town", id="combat-stays-wait"),
    pytest.param("combat-stays-left-click", "combat", "combat", "left_click", None, [500, 400], (("moveTo", (500, 400)), ("click", ())), "town", id="combat-stays-left-click"),
    pytest.param("combat-stays-right-click", "combat", "combat", "right_click", None, [500, 400], (("moveTo", (500, 400)), ("rightClick", ())), "town", id="combat-stays-right-click"),
    pytest.param("combat-stays-press-move-key", "combat", "combat", "press_move_key", "w", None, (("keyDown", ("w",)), ("keyUp", ("w",))), "town", id="combat-stays-press-move-key"),
    pytest.param("combat-stays-press-action-key", "combat", "combat", "press_action_key", "f12", None, (("keyDown", ("f12",)), ("keyUp", ("f12",))), "town", id="combat-stays-press-action-key"),
    pytest.param("combat-stays-move-camera", "combat", "combat", "move_camera", None, [500, 400], (("moveTo", (512, 384)), ("moveTo", (500, 400))), "town", id="combat-stays-move-camera"),
    pytest.param("combat-stays-mouse-move", "combat", "combat", "mouse_move", None, [500, 400], (("moveTo", (500, 400)),), "town", id="combat-stays-mouse-move"),
    pytest.param("combat-boss-reward-wait", "combat", "boss_reward", "wait", None, None, (), "town", id="combat-boss-reward-wait"),
    pytest.param("combat-boss-reward-right-click", "combat", "boss_reward", "right_click", None, [500, 400], (("moveTo", (500, 400)), ("rightClick", ())), "town", id="combat-boss-reward-right-click"),
    pytest.param("combat-recovers-wait", "combat", "recovery", "wait", None, None, (), "town", id="combat-recovers-wait"),
    pytest.param("combat-recovers-press-action-key", "combat", "recovery", "press_action_key", "f12", None, (("keyDown", ("f12",)), ("keyUp", ("f12",))), "town", id="combat-recovers-press-action-key"),
    pytest.param("boss-reward-stays-wait", "boss_reward", "boss_reward", "wait", None, None, (), "town", id="boss-reward-stays-wait"),
    pytest.param("boss-reward-loot-chest-wait", "boss_reward", "loot_chest", "wait", None, None, (), "town", id="boss-reward-loot-chest-wait"),
    pytest.param("boss-reward-recovers-wait", "boss_reward", "recovery", "wait", None, None, (), "town", id="boss-reward-recovers-wait"),
    pytest.param("loot-chest-stays-wait", "loot_chest", "loot_chest", "wait", None, None, (), "town", id="loot-chest-stays-wait"),
    pytest.param("loot-chest-stays-left-click", "loot_chest", "loot_chest", "left_click", None, [500, 400], (("moveTo", (500, 400)), ("click", ())), "town", id="loot-chest-stays-left-click"),
    pytest.param("loot-chest-loot-result-wait", "loot_chest", "loot_result", "wait", None, None, (), "town", id="loot-chest-loot-result-wait"),
    pytest.param("loot-chest-loot-result-mouse-move", "loot_chest", "loot_result", "mouse_move", None, [500, 400], (("moveTo", (500, 400)),), "town", id="loot-chest-loot-result-mouse-move"),
    pytest.param("loot-chest-recovers-wait", "loot_chest", "recovery", "wait", None, None, (), "town", id="loot-chest-recovers-wait"),
    pytest.param("loot-chest-recovers-left-click", "loot_chest", "recovery", "left_click", None, [500, 400], (("moveTo", (500, 400)), ("click", ())), "town", id="loot-chest-recovers-left-click"),
    pytest.param("loot-result-stabilizes-wait", "loot_result", "loot_result", "wait", None, None, (), "town", id="loot-result-stabilizes-wait"),
    pytest.param("loot-result-opens-retreat-f12", "loot_result", "retreat_dialog", "press_action_key", "f12", None, (("keyDown", ("f12",)), ("keyUp", ("f12",))), "town", id="loot-result-opens-retreat-f12"),
    pytest.param("loot-result-recovers-wait", "loot_result", "recovery", "wait", None, None, (), "town", id="loot-result-recovers-wait"),
    pytest.param("retreat-waits", "retreat_dialog", "retreat_dialog", "wait", None, None, (), "town", id="retreat-waits"),
    pytest.param("retreat-returns-town", "retreat_dialog", "return_wait", "left_click", "Town", [700, 400], (("moveTo", (700, 400)), ("click", ())), "town", id="retreat-returns-town"),
    pytest.param("retreat-returns-stage-entrance", "retreat_dialog", "return_wait", "left_click", "Stage Entrance", [700, 400], (("moveTo", (700, 400)), ("click", ())), "stage_entrance", id="retreat-returns-stage-entrance"),
    pytest.param("retreat-recovers-wait", "retreat_dialog", "recovery", "wait", None, None, (), "town", id="retreat-recovers-wait"),
    pytest.param("return-waits", "return_wait", "return_wait", "wait", None, None, (), "town", id="return-waits"),
    pytest.param("return-reaches-pre-dungeon", "return_wait", "pre_dungeon", "wait", None, None, (), "town", id="return-reaches-pre-dungeon"),
    pytest.param("return-recovers-wait", "return_wait", "recovery", "wait", None, None, (), "town", id="return-recovers-wait"),
    pytest.param("recovery-stays-wait", "recovery", "recovery", "wait", None, None, (), "town", id="recovery-stays-wait"),
    pytest.param("recovery-uses-f12", "recovery", "recovery", "press_action_key", "f12", None, (("keyDown", ("f12",)), ("keyUp", ("f12",))), "town", id="recovery-uses-f12"),
    pytest.param("recovery-reaches-pre-dungeon", "recovery", "pre_dungeon", "wait", None, None, (), "town", id="recovery-reaches-pre-dungeon"),
)


def _policy_setup(source, destination):
    """Return a hand-authored valid prefix ending at ``source``."""
    steps = []
    if source in {"entering_dungeon", "combat", "boss_reward", "loot_chest", "loot_result", "retreat_dialog", "return_wait"}:
        steps.append(_step("setup-enter", "entering_dungeon", "left_click", coordinate=[500, 400], before="pre_dungeon", after="entering_dungeon", calls=(("moveTo", (500, 400)), ("click", ()))))
    if source in {"combat", "boss_reward", "loot_chest", "loot_result", "retreat_dialog", "return_wait"}:
        steps.append(_step("setup-combat", "combat", "wait", before="entering_dungeon", after="combat"))
    if source in {"boss_reward", "loot_chest", "loot_result", "retreat_dialog", "return_wait"}:
        steps.append(_step("setup-reward", "boss_reward", "wait", before="combat", after="boss_reward"))
    if source in {"loot_chest", "loot_result", "retreat_dialog", "return_wait"}:
        steps.append(_step("setup-chest", "loot_chest", "wait", before="boss_reward", after="loot_chest"))
    if source in {"loot_result", "retreat_dialog", "return_wait"}:
        steps.append(_step("setup-loot", "loot_result", "wait", before="loot_chest", after="loot_result"))
        steps.append(_step("setup-loot-stable", "loot_result", "wait", before="loot_result", after="loot_result"))
    if source in {"retreat_dialog", "return_wait"}:
        steps.append(
            _step(
                "setup-dialog",
                "retreat_dialog",
                "press_action_key",
                text="f12",
                before="loot_result",
                after="retreat_dialog",
                calls=(("keyDown", ("f12",)), ("keyUp", ("f12",))),
            )
        )
    if source == "return_wait":
        label = "Town" if destination == "town" else "Stage Entrance"
        steps.append(_step("setup-return", "return_wait", "left_click", text=label, coordinate=[700, 400], before="retreat_dialog", after="return_wait", calls=(("moveTo", (700, 400)), ("click", ()))))
    if source == "recovery":
        steps.append(_step("setup-recovery", "recovery", "wait", before="pre_dungeon", after="recovery"))
    return steps


@pytest.mark.parametrize(
    "case_name,source,target,action,text,coordinate,calls,destination",
    _POLICY_REPLAY_EDGE_CASES,
)
def test_hand_expected_policy_edges_replay_end_to_end(
    case_name, source, target, action, text, coordinate, calls, destination
):
    policy = dn_bot.MINOTAUR_PHASE_POLICY[dn_bot.FarmState(source)]
    assert dn_bot.FarmState(target) in policy.actions_by_next_state
    assert action in policy.actions_by_next_state[dn_bot.FarmState(target)]

    raw_trace = _trace(
        *_policy_setup(source, destination),
        _step(
            f"edge-{case_name}",
            target,
            action,
            text=text,
            coordinate=coordinate,
            before=source,
            after=target,
            calls=calls,
        ),
        retreat_destination=destination,
    )
    parsed = ReplayTrace.from_dict(raw_trace)
    report = replay_trace(parsed)

    expected_setup_calls = {
        "pre_dungeon": (),
        "entering_dungeon": (("moveTo", (500, 400)), ("click", ())),
        "combat": (("moveTo", (500, 400)), ("click", ())),
        "boss_reward": (("moveTo", (500, 400)), ("click", ())),
        "loot_chest": (("moveTo", (500, 400)), ("click", ())),
        "loot_result": (("moveTo", (500, 400)), ("click", ())),
        "retreat_dialog": (
            ("moveTo", (500, 400)),
            ("click", ()),
            ("keyDown", ("f12",)),
            ("keyUp", ("f12",)),
        ),
        "return_wait": (
            ("moveTo", (500, 400)),
            ("click", ()),
            ("keyDown", ("f12",)),
            ("keyUp", ("f12",)),
            ("moveTo", (700, 400)),
            ("click", ()),
        ),
        "recovery": (),
    }
    assert report.final_state is dn_bot.FarmState(target)
    assert report.device_calls == expected_setup_calls[source] + calls


def test_replay_policy_matrix_covers_each_phase_with_hand_expected_payloads():
    sources = {case.values[1] for case in _POLICY_REPLAY_EDGE_CASES}
    assert sources == {state.value for state in dn_bot.FarmState}


@pytest.mark.parametrize(
    "name,action,text,coordinate,expected_error",
    [
        pytest.param("illegal-target", "wait", None, None, "Transisi", id="illegal-target"),
        pytest.param("illegal-action", "right_click", None, None, "Aksi", id="illegal-action"),
    ],
)
def test_replay_policy_matrix_rejects_illegal_action_or_target(
    monkeypatch, name, action, text, coordinate, expected_error
):
    executed = []
    original_execute = dn_bot.replay.execute_game_action
    monkeypatch.setattr(
        dn_bot.replay,
        "execute_game_action",
        lambda *args, **kwargs: (executed.append(True), original_execute(*args, **kwargs))[1],
    )
    if name == "illegal-target":
        raw = _trace(_step(name, "combat", action, text=text, coordinate=coordinate, before="pre_dungeon", after="pre_dungeon"))
    else:
        raw = _trace(_step(name, "pre_dungeon", action, text=text, coordinate=coordinate, before="pre_dungeon", after="pre_dungeon"))
    with pytest.raises(dn_bot.FarmSafetyStop, match=expected_error):
        replay_trace(raw)
    assert executed == []


@pytest.mark.parametrize(
    "name,label,coordinate,destination",
    [
        pytest.param("retreat-missing-label", None, [700, 400], "town", id="missing-label"),
        pytest.param("retreat-wrong-label", "Stage Entrance", [700, 400], "town", id="wrong-label"),
        pytest.param("retreat-missing-coordinate", "Town", None, "town", id="missing-coordinate"),
        pytest.param("retreat-out-of-bounds-coordinate", "Town", [1024, 400], "town", id="out-of-bounds-coordinate"),
    ],
)
def test_replay_policy_matrix_rejects_retreat_label_or_coordinate_mismatch(
    monkeypatch, name, label, coordinate, destination
):
    executed = []
    original_execute = dn_bot.replay.execute_game_action
    monkeypatch.setattr(
        dn_bot.replay,
        "execute_game_action",
        lambda *args, **kwargs: (executed.append(True), original_execute(*args, **kwargs))[1],
    )
    raw = _trace(
        *_policy_setup("retreat_dialog", destination),
        _step(name, "return_wait", "left_click", text=label, coordinate=coordinate, before="retreat_dialog", after="return_wait"),
        retreat_destination=destination,
    )
    expected_error = (
        dn_bot.ReplayTraceError
        if coordinate is not None and coordinate[0] >= 1024
        else dn_bot.FarmSafetyStop
    )
    with pytest.raises(expected_error):
        replay_trace(raw)
    expected_setup_calls = 0 if expected_error is dn_bot.ReplayTraceError else len(_policy_setup("retreat_dialog", destination))
    assert len(executed) == expected_setup_calls


def test_replay_policy_matrix_rejects_duplicate_f12(monkeypatch):
    executed = []
    original_execute = dn_bot.replay.execute_game_action
    monkeypatch.setattr(
        dn_bot.replay,
        "execute_game_action",
        lambda *args, **kwargs: (executed.append(True), original_execute(*args, **kwargs))[1],
    )
    raw = _trace(
        *_policy_setup("retreat_dialog", "town"),
        _step("duplicate-f12", "retreat_dialog", "press_action_key", text="f12", before="retreat_dialog", after="retreat_dialog"),
        retreat_destination="town",
    )
    with pytest.raises(dn_bot.FarmSafetyStop, match="F12"):
        replay_trace(raw)
    assert len(executed) == len(_policy_setup("retreat_dialog", "town"))


def test_replay_policy_matrix_rejects_state_changing_device_failure():
    raw = _trace(
        _step("state-changing-failure", "entering_dungeon", "left_click", coordinate=[500, 400], before="pre_dungeon", after="entering_dungeon", result="device_failure"),
    )
    with pytest.raises(ReplayTraceError, match="device_failure"):
        replay_trace(raw)


def test_replay_policy_matrix_covers_device_failures_before_and_after_primitives():
    before = _trace(
        _step("failure-before-primitive", "pre_dungeon", "wait", before="pre_dungeon", after="pre_dungeon", result="device_failure"),
    )
    after = _trace(
        _step("failure-after-move", "entering_dungeon", "left_click", coordinate=[500, 400], before="pre_dungeon", after="pre_dungeon", calls=(("moveTo", (500, 400)),), result="device_failure"),
    )
    assert replay_trace(before).device_calls == ()
    assert replay_trace(after).device_calls == (("moveTo", (500, 400)),)


def test_replay_policy_matrix_rejects_recovery_budget_exhaustion(monkeypatch):
    executed = []
    original_execute = dn_bot.replay.execute_game_action
    monkeypatch.setattr(
        dn_bot.replay,
        "execute_game_action",
        lambda *args, **kwargs: (executed.append(True), original_execute(*args, **kwargs))[1],
    )
    raw = _trace(
        _step("recovery-1", "recovery", "wait", before="pre_dungeon", after="recovery"),
        _step("recovery-1-exit", "pre_dungeon", "wait", before="recovery", after="pre_dungeon"),
        _step("recovery-2", "recovery", "wait", before="pre_dungeon", after="recovery"),
        _step("recovery-2-exit", "pre_dungeon", "wait", before="recovery", after="pre_dungeon"),
        _step("recovery-3", "recovery", "wait", before="pre_dungeon", after="recovery"),
    )
    with pytest.raises(dn_bot.FarmSafetyStop, match="Recovery"):
        replay_trace(raw)
    assert len(executed) == 4
