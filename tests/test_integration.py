"""End-to-end integration tests for the ``run_dn_bot`` loop (offline).

Jaring pengaman sebelum refactor arsitektur besar (plan 016): menjalankan loop
penuh capture -> pesan -> adapter -> aksi -> frame baru dengan fake yang
menggantikan capture, API, dan emergency check, tetapi mengeksekusi adapter
(``_call_openai``) dan kontrak ``messages.py`` ASLI.

Sejak seam input device (kandidat #4, plan 012/015) selesai, satu tes
(``test_integration_real_input_sequence_via_recorder``) mengeksekusi
``execute_game_action`` ASLI dengan ``RecordingDevice`` dan meng-assert urutan
input fisik; tes lainnya tetap memakai mock ``execute`` di level orchestrator
karena menguji mekanik loop (frame flow, urutan role, penolakan aksi kedua),
bukan jalur input.

Fake capture mengembalikan ``Frame`` nyata (via fixture ``capture_region``)
dengan encoded unik per panggilan, sehingga kontrak antar lapisan
(capture -> pesan -> frame yang dipakai aksi -> frame segar) benar-benar diuji.
"""

import os
from types import SimpleNamespace
from unittest.mock import ANY, call, patch

import dn_bot
from conftest import RecordingDevice, _sdk_response, _sdk_tool_call


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
        {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test/free"},
        clear=False,
    ), patch.object(
        dn_bot.orchestrator, "get_openai_client", return_value=client
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
        device=ANY,
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
        {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test/free"},
        clear=False,
    ), patch.object(
        dn_bot.orchestrator, "get_openai_client", return_value=client
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
        {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test/free"},
        clear=False,
    ), patch.object(
        dn_bot.orchestrator, "get_openai_client", return_value=client
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
                device=ANY,
            ),
            call(
                action="wait",
                coordinate=None,
                text=None,
                duration=dn_bot.MOVE_DURATION,
                frame=produced[1],
                device=ANY,
            ),
        ]
    )


def test_integration_real_input_sequence_via_recorder(capture_region):
    """Plan 016 item 3: jalur aksi NYATA + recorder (seam 012/015 selesai).

    ``run_dn_bot`` mengeksekusi ``execute_game_action`` asli dengan
    ``RecordingDevice`` (bukan mock): urutan input fisik ``move_camera``
    (anchor tengah lalu endpoint absolut — invariant anti-drift) dan ``wait``
    (tanpa call device) di-assert langsung dari recorder. Hanya guard
    (emergency/fokus) dan ``_safe_sleep`` yang di-patch agar urutan fokus pada
    primitif input.
    """
    client, requests = _scripted_client(
        [
            _sdk_response(
                tool_calls=[
                    _sdk_tool_call(
                        "call-1",
                        '{"action": "move_camera", "coordinate": [800, 600]}',
                    )
                ]
            ),
            _sdk_response(tool_calls=[_sdk_tool_call("call-2", '{"action": "wait"}')]),
            _sdk_response(content="selesai"),
        ]
    )
    fake_capture, produced = _fake_capture(capture_region, _REGION)
    device = RecordingDevice()
    frames_used = []

    def _execute_with_recorder(*args, **kwargs):
        # Jalur aksi asli (validasi + pemetaan koordinat) dengan device recorder.
        frames_used.append(kwargs["frame"])
        return dn_bot.input_control.execute_game_action(
            *args, **{**kwargs, "device": device}
        )

    with patch.dict(
        os.environ,
        {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test/free"},
        clear=False,
    ), patch.object(
        dn_bot.orchestrator, "get_openai_client", return_value=client
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", side_effect=fake_capture
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "check_emergency_stop"
    ), patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control, "_safe_sleep"
    ), patch.object(dn_bot.orchestrator, "execute_game_action", _execute_with_recorder):
        dn_bot.run_dn_bot("arahkan kamera ke kanan, lalu tunggu", max_steps=3)

    # Urutan input fisik nyata: move_camera = anchor ke tengah (512, 384) dulu,
    # lalu endpoint absolut (800, 600); wait = tidak ada call device sama sekali.
    device.assert_calls(
        [
            ("moveTo", (512, 384)),
            ("moveTo", (800, 600)),
        ]
    )
    # Aksi dimetakan terhadap frame yang model amati: frame sesi, lalu frame
    # segar setelah capture ulang (bukan frame basi).
    assert frames_used == [produced[0], produced[1]]
    # 3 request model (move_camera, wait, stop); frame terbaru di pesan user akhir.
    assert len(requests) == 3
    assert requests[2]["messages"][-1]["content"][1]["image_url"]["url"].endswith(
        "frame-3"
    )


def test_integration_dry_run_records_actions_without_physical_input(capture_region):
    """Mode --dry-run: loop penuh (capture -> model -> aksi -> frame baru)
    berjalan melawan ``DryRunDevice`` yang merekam/meng-log urutan input yang
    dimaksud, dan adapter produksi ``pydirectinput`` TIDAK pernah dipanggil.

    Guard keselamatan emergency (``check_emergency_stop``) sengaja TIDAK
    di-patch: ia berjalan asli terhadap device dry-run (posisi kursor tetap di
    koordinat aman) dan lolos — bukti bahwa cek emergency berperilaku wajar
    dalam mode latihan. Hanya fokus jendela dan sleep yang di-patch (tidak ada
    game terfokus di CI), sama seperti tes recorder yang sudah ada.
    """
    client, requests = _scripted_client(
        [
            _sdk_response(
                tool_calls=[
                    _sdk_tool_call(
                        "call-1",
                        '{"action": "move_camera", "coordinate": [800, 600]}',
                    )
                ]
            ),
            _sdk_response(
                tool_calls=[
                    _sdk_tool_call(
                        "call-2",
                        '{"action": "left_click", "coordinate": [512, 384]}',
                    )
                ]
            ),
            _sdk_response(content="selesai"),
        ]
    )
    fake_capture, _ = _fake_capture(capture_region, _REGION)
    device = dn_bot.DryRunDevice()

    with patch.dict(
        os.environ,
        {"OPENAI_API_KEY": "test-key", "OPENAI_MODEL": "test/free"},
        clear=False,
    ), patch.object(
        dn_bot.orchestrator, "get_openai_client", return_value=client
    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", side_effect=fake_capture
    ), patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control, "_safe_sleep"
    ), patch.object(dn_bot.device.pydirectinput, "moveTo") as real_move, patch.object(
        dn_bot.device.pydirectinput, "click"
    ) as real_click, patch.object(
        dn_bot.device.pydirectinput, "rightClick"
    ) as real_right, patch.object(
        dn_bot.device.pydirectinput, "keyDown"
    ) as real_down, patch.object(
        dn_bot.device.pydirectinput, "keyUp"
    ) as real_up:
        dn_bot.run_dn_bot("rehearsal", max_steps=3, device=device)

    # Urutan input fisik yang dimaksud (pembacaan posisi dari cek keselamatan
    # disaring): move_camera = anchor tengah lalu endpoint absolut; left_click
    # = moveTo lalu click.
    physical = [entry for entry in device.calls if entry[0] != "position"]
    assert physical == [
        ("moveTo", (512, 384)),
        ("moveTo", (800, 600)),
        ("moveTo", (512, 384)),
        ("click", ()),
    ]
    # Adapter produksi tidak pernah dipanggil di seluruh sesi.
    real_move.assert_not_called()
    real_click.assert_not_called()
    real_right.assert_not_called()
    real_down.assert_not_called()
    real_up.assert_not_called()
    # Loop berjalan penuh: 3 request (move_camera, left_click, stop) dan frame
    # segar sampai di request terakhir.
    assert len(requests) == 3
    assert requests[2]["messages"][-1]["content"][1]["image_url"]["url"].endswith(
        "frame-3"
    )
