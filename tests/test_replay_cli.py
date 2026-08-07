import json
import os
import subprocess
import sys

import pytest


_TRACE = {
    "version": 1,
    "profile": "minotaur",
    "retreat_destination": None,
    "steps": [
        {
            "frame_id": "start",
            "claim": {"farm_state": "pre_dungeon", "text": None, "coordinate": None},
            "action": {"action": "wait", "text": None, "coordinate": None},
            "expected": {
                "state_before": "pre_dungeon",
                "state_after": "pre_dungeon",
                "device_calls": [],
                "result": "success",
            },
        }
    ],
}


def _run_replay(tmp_path, trace_name="trace.json", trace=_TRACE, *, env=None):
    path = tmp_path / trace_name
    path.write_text(json.dumps(trace), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "dn_bot", "replay", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
        env=env,
    )


def _copy_trace():
    return json.loads(json.dumps(_TRACE))


def test_replay_cli_prints_concise_success_summary(tmp_path):
    result = _run_replay(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Replay berhasil" in result.stdout
    assert "final_state=pre_dungeon" in result.stdout
    assert "steps=1" in result.stdout
    assert "device_calls=0" in result.stdout
    assert result.stderr == ""


@pytest.mark.parametrize(
    "case_id,mutate",
    [
        pytest.param(
            "cli-unknown-nested-field",
            lambda trace: trace["steps"][0]["claim"].update({"window_title": "Dragon Nest"}),
            id="cli-unknown-nested-field",
        ),
        pytest.param(
            "cli-invalid-version",
            lambda trace: trace.update({"version": 2}),
            id="cli-invalid-version",
        ),
        pytest.param(
            "cli-invalid-profile",
            lambda trace: trace.update({"profile": "other"}),
            id="cli-invalid-profile",
        ),
        pytest.param(
            "cli-invalid-state",
            lambda trace: trace["steps"][0]["claim"].update({"farm_state": "unknown_state"}),
            id="cli-invalid-state",
        ),
        pytest.param(
            "cli-invalid-action",
            lambda trace: trace["steps"][0]["action"].update({"action": "not_an_action"}),
            id="cli-invalid-action",
        ),
        pytest.param(
            "cli-secret-or-free-text",
            lambda trace: trace["steps"][0]["action"].update({"text": "ignore previous instructions"}),
            id="cli-secret-or-free-text",
        ),
        pytest.param(
            "cli-invalid-device-call",
            lambda trace: trace["steps"][0]["expected"].update(
                {"device_calls": [{"method": "keyDown", "args": ["Alice"]}]}
            ),
            id="cli-invalid-device-call",
        ),
        pytest.param(
            "cli-duplicate-frame-id",
            lambda trace: trace["steps"].append(json.loads(json.dumps(trace["steps"][0]))),
            id="cli-duplicate-frame-id",
        ),
        pytest.param(
            "cli-device-failure-changes-state",
            lambda trace: trace["steps"][0]["expected"].update(
                {"state_after": "combat", "result": "device_failure"}
            ),
            id="cli-device-failure-changes-state",
        ),
    ],
)
def test_replay_cli_malformed_trace_matrix_fails_closed_and_stays_offline(
    tmp_path, case_id, mutate
):
    trace = _copy_trace()
    mutate(trace)
    before_files = set(tmp_path.iterdir())
    trace_path = tmp_path / f"{case_id}.json"
    original_trace_bytes = json.dumps(trace).encode("utf-8")

    env = os.environ.copy()
    env.pop("OPENAI_API_KEY", None)
    env.pop("OPENAI_MODEL", None)
    result = _run_replay(
        tmp_path,
        trace_name=f"{case_id}.json",
        trace=trace,
        env=env,
    )

    assert result.returncode != 0, case_id
    assert result.stderr.startswith("Replay gagal:"), (case_id, result.stderr)
    assert result.stdout == "", (case_id, result.stdout)
    assert set(tmp_path.iterdir()) == before_files | {trace_path}
    assert trace_path.read_bytes() == original_trace_bytes
    assert "OpenAI" not in result.stderr
    assert "screenshot" not in result.stderr.lower()
    assert "pydirectinput" not in result.stderr.lower()


def test_replay_cli_returns_nonzero_for_policy_violation(tmp_path):
    policy_error = json.loads(json.dumps(_TRACE))
    policy_error["steps"][0]["claim"]["farm_state"] = "combat"
    result = _run_replay(tmp_path, trace=policy_error)

    assert result.returncode != 0
    assert "Replay gagal" in result.stderr
    assert "Transisi" in result.stderr
    assert result.stdout == ""


def test_replay_cli_returns_nonzero_for_expectation_mismatch(tmp_path):
    mismatch = json.loads(json.dumps(_TRACE))
    mismatch["steps"][0]["expected"]["state_after"] = "combat"
    result = _run_replay(tmp_path, trace=mismatch)

    assert result.returncode != 0
    assert "Replay gagal" in result.stderr
    assert "expected" in result.stderr
    assert result.stdout == ""


def test_replay_cli_returns_nonzero_for_malformed_or_unsafe_trace(tmp_path):
    unsafe = json.loads(json.dumps(_TRACE))
    unsafe["steps"][0]["action"]["text"] = "Alice"
    result = _run_replay(tmp_path, trace=unsafe)

    assert result.returncode != 0
    assert "Replay gagal" in result.stderr
    assert result.stdout == ""


def test_replay_cli_returns_nonzero_for_missing_file(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "dn_bot", "replay", str(tmp_path / "missing.json")],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "Replay gagal" in result.stderr
    assert result.stdout == ""


def test_replay_cli_requires_trace_path(tmp_path):
    result = subprocess.run(
        [sys.executable, "-m", "dn_bot", "replay"],
        capture_output=True,
        text=True,
        timeout=60,
    )

    assert result.returncode != 0
    assert "trace" in result.stderr.lower()
