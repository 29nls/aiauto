import json
import subprocess
import sys

import dn_bot


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


def _run_replay(tmp_path, trace_name="trace.json", trace=_TRACE):
    path = tmp_path / trace_name
    path.write_text(json.dumps(trace), encoding="utf-8")
    return subprocess.run(
        [sys.executable, "-m", "dn_bot", "replay", str(path)],
        capture_output=True,
        text=True,
        timeout=60,
    )


def test_replay_cli_prints_concise_success_summary(tmp_path):
    result = _run_replay(tmp_path)

    assert result.returncode == 0, result.stderr
    assert "Replay berhasil" in result.stdout
    assert "final_state=pre_dungeon" in result.stdout
    assert "steps=1" in result.stdout
    assert "device_calls=0" in result.stdout
    assert result.stderr == ""


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
