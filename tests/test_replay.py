import json

import pytest

import dn_bot
from dn_bot.replay import ReplayMismatch, ReplayTrace, ReplayTraceError, replay_trace


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


def test_replay_runs_golden_path_without_openrouter_or_physical_input():
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
    with pytest.raises(dn_bot.FarmSafetyStop):
        replay_trace(invalid_claim)

    invalid_action = _trace(_step("bad-action", "pre_dungeon", "press_action_key", text="f12"))
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
