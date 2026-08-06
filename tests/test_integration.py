"""End-to-end integration tests for the ``run_dn_bot`` loop (offline).

Jaring pengaman sebelum refactor arsitektur besar (plan 016): menjalankan loop
penuh capture -> pesan -> adapter -> aksi -> frame baru dengan fake yang
menggantikan capture, API, dan emergency check, tetapi mengeksekusi adapter
(``_call_openrouter``) dan kontrak ``messages.py`` ASLI. ``execute_game_action``
tetap di-mock di level orchestrator karena seam input device (kandidat #4)
belum selesai.

Fake capture mengembalikan ``Frame`` nyata (via fixture ``capture_region``)
dengan encoded unik per panggilan, sehingga kontrak antar lapisan
(capture -> pesan -> frame yang dipakai aksi -> frame segar) benar-benar diuji.
"""

import os
from types import SimpleNamespace
from unittest.mock import call, patch

import dn_bot
from conftest import _sdk_response, _sdk_tool_call


def _scripted_client(responses):
    """Fake OpenAI client whose create() records payloads and replays scripted
    SDK-shaped responses through the real adapter."""
    requests = []
    iterator = iter(responses)
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **payload: (requests.append(payload), next(iterator))[1]
            )
        )
    )
    return client, requests


def _fake_capture(capture_region, region):
    """Capture function returning real Frames with unique encodings.

    ``produced`` mencatat Frame yang pernah dikembalikan (indeks 0 = capture
    sesi, 1 = setelah aksi pertama, dst.) untuk assert frame flow.
    """
    counter = {"n": 0}
    produced = []

    def fake_capture():
        counter["n"] += 1
        frame = capture_region(region, encoded="frame-%s" % counter["n"])
        produced.append(frame)
        return frame

    return fake_capture, produced


_REGION = {"left": 0, "top": 0, "width": 1024, "height": 768}


def test_integration_full_loop_two_steps(capture_region):
    """Alur penuh: [wait, stop] -> 2 request, 1 aksi, frame segar di pesan user."""
    client, requests = _scripted_client(
        [
            _sdk_response(tool_calls=[_sdk_tool_call("call-1", '{"action": "wait"}')]),
            _sdk_response(content="selesai"),
        ]
    )
    fake_capture, produced = _fake_capture(capture_region, _REGION)

    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(
        dn_bot.orchestrator, "get_openrouter_client", return_value=client
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", side_effect=fake_capture
    ), patch.object(dn_bot.orchestrator, "execute_game_action") as execute, patch.object(
        dn_bot.orchestrator, "check_emergency_stop"
    ):
        dn_bot.run_dn_bot("gerak pelan ke kiri", max_steps=2)

    # 2 request model terkirim (langkah 1: wait, langkah 2: stop)
    assert len(requests) == 2
    # Deviasi sengaja dari plan 016 (yang menulis "frame dari capture kedua"):
    # aksi langkah 1 dimetakan terhadap frame sesi (produced[0]) yang model
    # amati saat memutuskan aksi; capture "kedua" (produced[1]) justru terjadi
    # SETELAH aksi dan diassert lewat pesan user terakhir (frame-2).
    execute.assert_called_once_with(
        action="wait",
        coordinate=None,
        text=None,
        duration=dn_bot.MOVE_DURATION,
        frame=produced[0],
    )
    # Request pertama berisi frame awal di pesan user terakhirnya
    assert requests[0]["messages"][2]["content"][1]["image_url"]["url"].endswith(
        "frame-1"
    )
    # Request kedua: urutan role lengkap + pasangan tool_call_id + frame segar
    messages = requests[1]["messages"]
    assert [m["role"] for m in messages] == [
        "system",
        "user",
        "assistant",
        "tool",
        "user",
    ]
    assistant = next(m for m in messages if m["role"] == "assistant")
    tool = next(m for m in messages if m["role"] == "tool")
    assert assistant["tool_calls"][0]["id"] == tool["tool_call_id"] == "call-1"
    assert messages[-1]["content"][1]["image_url"]["url"].endswith("frame-2")


def test_integration_rejects_second_action_per_cycle(capture_region):
    """Dua tool call dalam satu respons -> hanya aksi pertama dieksekusi."""
    client, requests = _scripted_client(
        [
            _sdk_response(
                tool_calls=[
                    _sdk_tool_call("call-1", '{"action": "wait"}'),
                    _sdk_tool_call("call-2", '{"action": "wait"}'),
                ]
            ),
            _sdk_response(content="selesai"),
        ]
    )
    fake_capture, _ = _fake_capture(capture_region, _REGION)

    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(
        dn_bot.orchestrator, "get_openrouter_client", return_value=client
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", side_effect=fake_capture
    ), patch.object(dn_bot.orchestrator, "execute_game_action") as execute, patch.object(
        dn_bot.orchestrator, "check_emergency_stop"
    ):
        dn_bot.run_dn_bot("go", max_steps=2)

    execute.assert_called_once()
    # Dua tool result: hasil aksi + penolakan aksi kedua
    tool_results = [
        m["content"] for m in requests[1]["messages"] if m["role"] == "tool"
    ]
    assert len(tool_results) == 2
    assert "hanya satu aksi per screenshot" in tool_results[1]


def test_integration_next_cycle_acts_on_fresh_frame(capture_region):
    """Aksi siklus berikutnya dimetakan terhadap frame segar, bukan frame basi."""
    client, _ = _scripted_client(
        [
            _sdk_response(tool_calls=[_sdk_tool_call("call-1", '{"action": "wait"}')]),
            _sdk_response(tool_calls=[_sdk_tool_call("call-2", '{"action": "wait"}')]),
            _sdk_response(content="selesai"),
        ]
    )
    fake_capture, produced = _fake_capture(capture_region, _REGION)

    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(
        dn_bot.orchestrator, "get_openrouter_client", return_value=client
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", side_effect=fake_capture
    ), patch.object(dn_bot.orchestrator, "execute_game_action") as execute, patch.object(
        dn_bot.orchestrator, "check_emergency_stop"
    ):
        dn_bot.run_dn_bot("go", max_steps=3)

    assert execute.call_count == 2
    execute.assert_has_calls(
        [
            call(
                action="wait",
                coordinate=None,
                text=None,
                duration=dn_bot.MOVE_DURATION,
                frame=produced[0],
            ),
            call(
                action="wait",
                coordinate=None,
                text=None,
                duration=dn_bot.MOVE_DURATION,
                frame=produced[1],
            ),
        ]
    )
