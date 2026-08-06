import importlib
import os
import re
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest
from types import SimpleNamespace
from unittest.mock import ANY, call, patch

import dn_bot
import dn_bot.__main__
from conftest import RecordingDevice, _sdk_response, _sdk_tool_call
from PIL import Image


class _FakeAPIError(Exception):
    """Mirrors openai.APIStatusError subclasses (e.g. RateLimitError)."""

    def __init__(self, message="boom", status_code=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class _FakeTimeoutError(Exception):
    """Mirrors openai.APITimeoutError: no status_code attribute."""


# Realistic OpenRouter key shape that passes the preflight format check (T7).
_VALID_API_KEY = "sk-or-v1-0123456789abcdef0123456789abcdef0123456789"


def _fake_client(create):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )




def test_openrouter_client_passes_configured_base_url_api_key_and_timeout():
    """Guard: the client is constructed with base_url, api_key, and a bounded
    timeout (not the SDK default) — the exact T1 hardening."""
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key"},
        clear=True,
    ), patch.object(dn_bot.api, "OpenAI") as mock_openai:
        dn_bot.get_openrouter_client()

    mock_openai.assert_called_once_with(
        base_url=dn_bot.config.OPENROUTER_BASE_URL,
        api_key="test-key",
        timeout=dn_bot.config.OPENROUTER_TIMEOUT_DEFAULT,
    )


def test_openrouter_client_honors_custom_timeout_env():
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_TIMEOUT": "30",
        },
        clear=True,
    ), patch.object(dn_bot.api, "OpenAI") as mock_openai:
        dn_bot.get_openrouter_client()

    mock_openai.assert_called_once_with(
        base_url=dn_bot.config.OPENROUTER_BASE_URL,
        api_key="test-key",
        timeout=30,
    )


@pytest.mark.parametrize(
    "value,expected_text",
    [
        ("abc", "bilangan bulat"),
        ("0", "positif"),
        ("-5", "positif"),
    ],
    ids=["non-integer", "zero", "negative"],
)
def test_openrouter_client_rejects_invalid_timeout_env(value, expected_text):
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_TIMEOUT": value,
        },
        clear=True,
    ), patch.object(dn_bot.api, "OpenAI"):
        with pytest.raises(ValueError, match=expected_text):
            dn_bot.get_openrouter_client()


def test_move_camera_anchors_at_center_before_absolute_endpoint(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    device = RecordingDevice()
    with patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control, "check_emergency_stop"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        dn_bot.execute_game_action(
            "move_camera", coordinate=[800, 600], frame=frame, device=device
        )

    # Camera movement is anchored at the screenshot center first; the
    # protocol has no moveRel method, so only moveTo calls can be recorded.
    device.assert_calls([("moveTo", (512, 384)), ("moveTo", (800, 600))])


def test_repeated_move_camera_calls_reanchor_before_each_endpoint(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    device = RecordingDevice()
    with patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control, "check_emergency_stop"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        dn_bot.execute_game_action(
            "move_camera", coordinate=[800, 600], frame=frame, device=device
        )
        dn_bot.execute_game_action(
            "move_camera", coordinate=[200, 300], frame=frame, device=device
        )

    device.assert_calls(
        [
            ("moveTo", (512, 384)),
            ("moveTo", (800, 600)),
            ("moveTo", (512, 384)),
            ("moveTo", (200, 300)),
        ]
    )


def test_move_camera_rejects_padding_before_moving_cursor(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1920, "height": 1080})
    device = RecordingDevice()
    with patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "check_emergency_stop"), patch.object(
        dn_bot.input_control, "_safe_sleep"
    ):
        with pytest.raises(ValueError, match="padding"):
            dn_bot.execute_game_action(
                "move_camera", coordinate=[512, 95], frame=frame, device=device
            )

    device.assert_calls([])


def test_move_camera_rejects_missing_coordinate(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    device = RecordingDevice()
    with patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control, "check_emergency_stop"
    ):
        with pytest.raises(ValueError, match="coordinate"):
            dn_bot.execute_game_action("move_camera", frame=frame, device=device)

    device.assert_calls([])


@pytest.mark.parametrize("duration", ["slow", float("nan"), float("inf")])
def test_execute_game_action_rejects_invalid_duration(capture_region, duration):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    device = RecordingDevice()  # position() returns a non-corner default
    with patch.object(dn_bot.input_control, "check_target_window"):
        with pytest.raises(ValueError, match="duration"):
            dn_bot.execute_game_action(
                "wait", duration=duration, frame=frame, device=device
            )

    # The real emergency-stop guard ran first: it read the cursor once.
    device.assert_calls([("position", ())])


def test_execute_game_action_sanitizes_unknown_action_in_error(capture_region):
    """Aksi tak dikenal dari model disanitasi sebelum masuk pesan error (F-05)."""
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    with patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control, "check_emergency_stop"
    ), patch.object(dn_bot.input_control, "_safe_sleep"):
        with pytest.raises(ValueError, match="Aksi tidak diizinkan") as error_info:
            dn_bot.execute_game_action(
                "\x1b[31mINJECT\x1b[0m", frame=frame, device=RecordingDevice()
            )
    assert "\x1b" not in str(error_info.value)


@pytest.mark.parametrize(
    "instruction,max_steps",
    [(None, 1), ("go", 1.5)],
)
def test_run_dn_bot_rejects_non_string_instruction_and_non_integer_steps(
    instruction, max_steps
):
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ):
        with pytest.raises(ValueError):
            dn_bot.run_dn_bot(instruction, max_steps=max_steps)


def test_run_dn_bot_bounds_history_and_pairs_recent_tool_calls():
    def response(call_id, action):
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id=call_id,
                                function=SimpleNamespace(
                                    name="dragon_nest_action",
                                    arguments='{"action":"%s"}' % action,
                                ),
                            )
                        ],
                    )
                )
            ]
        )

    responses = iter(
        [
            response("call-1", "wait"),
            response("call-2", "wait"),
            response("call-3", "wait"),
        ]
    )
    requests = []
    client = SimpleNamespace(
        chat=SimpleNamespace(
            completions=SimpleNamespace(
                create=lambda **payload: (requests.append(payload), next(responses))[1]
            )
        )
    )

    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client", return_value=client    ), patch.object(
        dn_bot.orchestrator,
        "capture_screen_base64",
        side_effect=[
            SimpleNamespace(encoded="frame-0"),
            SimpleNamespace(encoded="frame-1"),
            SimpleNamespace(encoded="frame-2"),
            SimpleNamespace(encoded="frame-3"),
        ],
    ), patch.object(dn_bot.orchestrator, "execute_game_action"), patch.object(
        dn_bot.orchestrator, "check_emergency_stop"
    ):
        dn_bot.run_dn_bot("keep this instruction", max_steps=3)

    assert len(requests) == 3
    for index, request in enumerate(requests):
        messages = request["messages"]
        assert len(messages) <= 1 + dn_bot.MAX_CONTEXT_MESSAGES
        assert messages[0] == {"role": "system", "content": dn_bot.SYSTEM_PROMPT}
        assert messages[1]["content"] == "keep this instruction"

        image_messages = [
            message
            for message in messages
            if isinstance(message.get("content"), list)
            and any(block.get("type") == "image_url" for block in message["content"])
        ]
        assert len(image_messages) == 1
        image_url = image_messages[0]["content"][1]["image_url"]["url"]
        assert image_url.endswith("frame-%s" % index)
        assert all(
            "frame-%s" % old_index not in image_url
            for old_index in range(index)
        )
        assert image_messages[0] is messages[-1]

        for message_index, message in enumerate(messages):
            if message.get("role") != "assistant" or "tool_calls" not in message:
                continue
            tool_messages = []
            next_index = message_index + 1
            while (
                next_index < len(messages)
                and messages[next_index].get("role") == "tool"
            ):
                tool_messages.append(messages[next_index])
                next_index += 1
            assert [call["id"] for call in message["tool_calls"]] == [
                tool["tool_call_id"] for tool in tool_messages
            ]


def test_compaction_drops_older_turns_instead_of_newest_oversized_turn():
    messages = [
        {"role": "user", "content": "instruction"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": "old-call",
                    "type": "function",
                    "function": {
                        "name": "dragon_nest_action",
                        "arguments": "{}",
                    },
                }
            ],
        },
        {"role": "tool", "tool_call_id": "old-call", "content": "old result"},
        {
            "role": "assistant",
            "content": "",
            "tool_calls": [
                {
                    "id": f"new-call-{index}",
                    "type": "function",
                    "function": {
                        "name": "dragon_nest_action",
                        "arguments": "{}",
                    },
                }
                for index in range(dn_bot.MAX_CONTEXT_MESSAGES)
            ],
        },
        *[
            {
                "role": "tool",
                "tool_call_id": f"new-call-{index}",
                "content": "new result",
            }
            for index in range(dn_bot.MAX_CONTEXT_MESSAGES)
        ],
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Current screenshot."},
                {"type": "image_url", "image_url": {"url": "frame-new"}},
            ],
        },
    ]

    compacted = dn_bot._compact_messages(messages)

    assert compacted[0] == {"role": "user", "content": "instruction"}
    assert compacted[-1]["content"][1]["image_url"]["url"] == "frame-new"
    assert not any(message.get("tool_call_id") == "old-call" for message in compacted)
    assert not any(
        message.get("tool_call_id", "").startswith("new-call-")
        for message in compacted
    )


def test_16_9_geometry_records_vertical_letterbox_padding():
    geometry = dn_bot._geometry_for_region(
        {"left": 137, "top": 83, "width": 1920, "height": 1080}
    )

    assert (geometry.content_width, geometry.content_height) == (1024, 576)
    assert (geometry.offset_x, geometry.offset_y) == (0, 96)


def test_2_to_1_geometry_records_vertical_letterbox_padding():
    geometry = dn_bot._geometry_for_region(
        {"left": 37, "top": 61, "width": 1000, "height": 500}
    )

    assert (geometry.content_width, geometry.content_height) == (1024, 512)
    assert (geometry.offset_x, geometry.offset_y) == (0, 128)


def test_letterbox_preserves_content_and_padding_for_16_9_image():
    image = Image.new("RGB", (16, 9), (255, 0, 0))
    geometry = dn_bot._geometry_for_region(
        {"left": 0, "top": 0, "width": 16, "height": 9}
    )

    result = dn_bot._letterbox(image, geometry)

    assert result.size == (dn_bot.TARGET_WIDTH, dn_bot.TARGET_HEIGHT)
    assert result.getpixel((512, 95)) == (0, 0, 0)
    assert result.getpixel((512, 96))[0] > 200
    assert result.getpixel((512, 671))[0] > 200
    assert result.getpixel((512, 672)) == (0, 0, 0)


def test_letterboxed_16_9_center_maps_to_nontrivial_capture_region(capture_region):
    frame = capture_region({"left": 137, "top": 83, "width": 1920, "height": 1080})

    physical = dn_bot._physical_point([512, 384], frame)

    assert physical == (1097, 623)


@pytest.mark.parametrize("coordinate", [[512, 95], [512, 672]], ids=["top", "bottom"])
def test_letterboxed_padding_is_not_clickable(capture_region, coordinate):
    frame = capture_region({"left": 137, "top": 83, "width": 1920, "height": 1080})

    with pytest.raises(ValueError, match="padding"):
        dn_bot._physical_point(coordinate, frame)


def test_nontrivial_2_to_1_region_maps_content_edges(capture_region):
    frame = capture_region({"left": 37, "top": 61, "width": 1000, "height": 500})

    assert dn_bot._physical_point([512, 384], frame) == (537, 311)
    assert dn_bot._physical_point([0, 128], frame) == (37, 61)
    assert dn_bot._physical_point([1023, 639], frame) == (1036, 560)


@pytest.mark.parametrize("coordinate", [[0, 127], [0, 640]], ids=["top", "bottom"])
def test_nontrivial_region_padding_is_not_clickable(capture_region, coordinate):
    frame = capture_region({"left": 37, "top": 61, "width": 1000, "height": 500})

    with pytest.raises(ValueError, match="padding"):
        dn_bot._physical_point(coordinate, frame)


def test_scaled_physical_emergency_corner_is_rejected(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1920, "height": 1080})

    with pytest.raises(ValueError, match="emergency stop"):
        dn_bot._physical_point([0, 96], frame)


def test_negative_monitor_coordinates_are_not_emergency_corner(capture_region):
    frame = capture_region({"left": -1920, "top": -1080, "width": 1920, "height": 1080})

    assert dn_bot._physical_point([512, 384], frame) == (-960, -540)


def test_physical_point_rejects_non_integer_coordinates(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})

    with pytest.raises(ValueError, match="dua integer"):
        dn_bot._physical_point([1.5, 10], frame)


def test_capture_region_reads_full_explicit_rect_from_env():
    with patch.dict(
        os.environ,
        {
            "DN_CAPTURE_LEFT": "137",
            "DN_CAPTURE_TOP": "83",
            "DN_CAPTURE_WIDTH": "1920",
            "DN_CAPTURE_HEIGHT": "1080",
        },
        clear=True,
    ):
        region = dn_bot.capture._capture_region_from_env(SimpleNamespace(monitors=[]))

    assert region == {"left": 137, "top": 83, "width": 1920, "height": 1080}


def test_capture_region_requires_all_rect_vars():
    with patch.dict(
        os.environ,
        {
            "DN_CAPTURE_LEFT": "137",
            "DN_CAPTURE_TOP": "83",
            "DN_CAPTURE_WIDTH": "1920",
        },
        clear=True,
    ):
        try:
            dn_bot.capture._capture_region_from_env(SimpleNamespace(monitors=[]))
        except ValueError as error:
            assert "DN_CAPTURE_LEFT/TOP/WIDTH/HEIGHT" in str(error)
        else:
            raise AssertionError("Partial rect must be rejected")


def test_capture_region_rejects_non_integer_rect_value():
    with patch.dict(
        os.environ,
        {
            "DN_CAPTURE_LEFT": "137",
            "DN_CAPTURE_TOP": "83",
            "DN_CAPTURE_WIDTH": "lebar",
            "DN_CAPTURE_HEIGHT": "1080",
        },
        clear=True,
    ):
        try:
            dn_bot.capture._capture_region_from_env(SimpleNamespace(monitors=[]))
        except ValueError as error:
            assert "DN_CAPTURE_WIDTH harus berupa bilangan bulat" in str(error)
            assert "lebar" in str(error)
        else:
            raise AssertionError("Non-integer rect value must be rejected")


def test_capture_region_rejects_non_integer_monitor():
    with patch.dict(
        os.environ,
        {"DN_MONITOR": "dua"},
        clear=True,
    ):
        try:
            dn_bot.capture._capture_region_from_env(SimpleNamespace(monitors=[{}]))
        except ValueError as error:
            assert "DN_MONITOR harus berupa bilangan bulat" in str(error)
        else:
            raise AssertionError("Non-integer monitor must be rejected")


def test_capture_region_reads_valid_monitor():
    screen = SimpleNamespace(
        monitors=[
            {"left": 0, "top": 0, "width": 3840, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
            {"left": 1920, "top": 0, "width": 1920, "height": 1080},
        ]
    )
    with patch.dict(os.environ, {"DN_MONITOR": "2"}, clear=True):
        region = dn_bot.capture._capture_region_from_env(screen)

    assert region == {"left": 1920, "top": 0, "width": 1920, "height": 1080}


def test_capture_region_defaults_to_monitor_one():
    screen = SimpleNamespace(
        monitors=[
            {"left": 0, "top": 0, "width": 3840, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]
    )
    with patch.dict(os.environ, {}, clear=True):
        region = dn_bot.capture._capture_region_from_env(screen)

    assert region == {"left": 0, "top": 0, "width": 1920, "height": 1080}


def test_capture_region_rejects_monitor_out_of_range():
    screen = SimpleNamespace(
        monitors=[
            {"left": 0, "top": 0, "width": 3840, "height": 1080},
            {"left": 0, "top": 0, "width": 1920, "height": 1080},
        ]
    )
    with patch.dict(os.environ, {"DN_MONITOR": "5"}, clear=True):
        try:
            dn_bot.capture._capture_region_from_env(screen)
        except ValueError as error:
            assert "antara 1 dan 1" in str(error)
        else:
            raise AssertionError("Out-of-range monitor must be rejected")


def test_capture_region_rejects_empty_rect_value():
    with patch.dict(
        os.environ,
        {
            "DN_CAPTURE_LEFT": "137",
            "DN_CAPTURE_TOP": "83",
            "DN_CAPTURE_WIDTH": "",
            "DN_CAPTURE_HEIGHT": "1080",
        },
        clear=True,
    ):
        try:
            dn_bot.capture._capture_region_from_env(SimpleNamespace(monitors=[]))
        except ValueError as error:
            assert "DN_CAPTURE_WIDTH harus berupa bilangan bulat" in str(error)
        else:
            raise AssertionError("Empty rect value must be rejected")


def test_int_env_returns_none_when_unset_and_no_default():
    with patch.dict(os.environ, {}, clear=True):
        assert dn_bot._int_env("DN_CAPTURE_LEFT") is None


def test_image_block_builds_openai_image_url_data_uri():
    block = dn_bot.image_block("abc123")

    assert block == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,abc123"},
    }


def test_extract_tool_requests_rejects_unknown_tool():
    message = SimpleNamespace(
        tool_calls=[
            SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(name="other_tool", arguments="{}"),
            )
        ]
    )

    try:
        dn_bot.extract_tool_requests(message)
    except ValueError as error:
        assert "Tool tidak diizinkan" in str(error)
    else:
        raise AssertionError("Unknown tool should be rejected")


def test_extract_tool_requests_rejects_malformed_json():
    message = SimpleNamespace(
        tool_calls=[
            SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(
                    name="dragon_nest_action", arguments="not-json"
                ),
            )
        ]
    )

    try:
        dn_bot.extract_tool_requests(message)
    except ValueError as error:
        assert "JSON" in str(error)
    else:
        raise AssertionError("Malformed tool JSON should be rejected")


def test_extract_tool_requests_sanitizes_unknown_tool_name():
    """Nama tool tak dikenal dari model disanitasi sebelum masuk pesan error (F-05)."""
    message = SimpleNamespace(
        tool_calls=[
            SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(
                    name="\x1b[31mevil_tool\x1b[0m", arguments="{}"
                ),
            )
        ]
    )
    with pytest.raises(ValueError, match="Tool tidak diizinkan") as error_info:
        dn_bot.extract_tool_requests(message)
    assert "\x1b" not in str(error_info.value)


def test_extract_tool_requests_reads_openrouter_function_call():
    message = SimpleNamespace(
        tool_calls=[
            SimpleNamespace(
                id="call-1",
                function=SimpleNamespace(
                    name="dragon_nest_action",
                    arguments='{"action":"wait","duration":0.1}',
                ),
            )
        ]
    )

    requests = dn_bot.extract_tool_requests(message)

    assert requests == [
        dn_bot.ToolRequest(id="call-1", input={"action": "wait", "duration": 0.1})
    ]


@pytest.mark.parametrize(
    "error,expected_kind",
    [
        (_FakeAPIError(status_code=401), "auth"),
        (_FakeAPIError(status_code=403), "auth"),
        (_FakeAPIError(status_code=404), "not_found"),
        (_FakeAPIError(status_code=400), "invalid_request"),
        (_FakeAPIError(status_code=422), "invalid_request"),
        (_FakeAPIError(status_code=429), "rate_limit"),
        (_FakeAPIError(status_code=408), "network"),
        (_FakeAPIError(status_code=500), "server"),
        (_FakeAPIError(status_code=503), "server"),
        (_FakeAPIError(status_code=409), "http"),
        (_FakeTimeoutError(), "network"),
        (Exception("bukan error API"), "unknown"),
    ],
    ids=[
        "401-auth",
        "403-auth",
        "404-not_found",
        "400-invalid_request",
        "422-invalid_request",
        "429-rate_limit",
        "408-network",
        "500-server",
        "503-server",
        "409-http",
        "timeout-network",
        "unknown",
    ],
)
def test_classify_api_error_kinds(error, expected_kind):
    assert dn_bot._classify_api_error(error) == expected_kind


def test_call_openrouter_retries_rate_limit_then_succeeds():
    attempts = {"count": 0}

    def create(**payload):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _FakeAPIError("rate limited", 429)
        return _sdk_response(content="baik")

    sleeps = []
    with patch.object(
        dn_bot.api, "_safe_sleep", side_effect=lambda seconds: sleeps.append(seconds)
    ):
        result = dn_bot._call_openrouter(_fake_client(create), "test/free", [])

    assert result == dn_bot.ModelReply(text="baik", tool_requests=[])
    assert attempts["count"] == 3
    assert sleeps == [dn_bot.API_RETRY_BASE_DELAY, dn_bot.API_RETRY_BASE_DELAY * 2]


def test_call_openrouter_stops_after_max_attempts():
    attempts = {"count": 0}

    def create(**payload):
        attempts["count"] += 1
        raise _FakeAPIError("rate limited", 429)

    with patch.object(dn_bot.api, "_safe_sleep"):
        try:
            dn_bot._call_openrouter(_fake_client(create), "test/free", [])
        except RuntimeError as error:
            assert "429" in str(error)
        else:
            raise AssertionError("Retries should be exhausted into a RuntimeError")

    assert attempts["count"] == dn_bot.API_MAX_ATTEMPTS


@pytest.mark.parametrize(
    "status_code,expected_text",
    [(401, "OPENROUTER_API_KEY"), (404, "OPENROUTER_MODEL")],
)
def test_call_openrouter_does_not_retry_configuration_errors(status_code, expected_text):
    attempts = {"count": 0}

    def create(**payload):
        attempts["count"] += 1
        raise _FakeAPIError("config problem", status_code)

    with patch.object(dn_bot.api, "_safe_sleep"):
        with pytest.raises(RuntimeError, match=expected_text):
            dn_bot._call_openrouter(_fake_client(create), "test/free", [])

    assert attempts["count"] == 1


def test_call_openrouter_truncates_long_error_detail():
    long_detail = "x" * (dn_bot.config.API_ERROR_DETAIL_MAX + 100)

    def create(**payload):
        raise _FakeAPIError(long_detail, 401)

    with patch.object(dn_bot.api, "_safe_sleep"):
        try:
            dn_bot._call_openrouter(_fake_client(create), "test/free", [])
        except RuntimeError as error:
            truncated = long_detail[: dn_bot.config.API_ERROR_DETAIL_MAX]
            assert "... (terpotong)" in str(error)
            assert truncated in str(error)
            assert long_detail not in str(error)
            assert error.__cause__ is None  # not chained via `from error`
            assert error.__suppress_context__ is True  # chain suppressed: no traceback leak
        else:
            raise AssertionError("Config errors must surface as RuntimeError")


def test_call_openrouter_sanitizes_sdk_error_detail():
    """Detail error SDK disanitasi (F-05) selain dibatasi panjangnya (F-06)."""
    def create(**payload):
        raise _FakeAPIError("\x1b[31mhostile detail\x1b[0m", 401)

    with patch.object(dn_bot.api, "_safe_sleep"):
        try:
            dn_bot._call_openrouter(_fake_client(create), "test/free", [])
        except RuntimeError as error:
            assert "\x1b" not in str(error)
            assert "hostile detail" in str(error)
        else:
            raise AssertionError("Config errors must surface as RuntimeError")


def test_check_emergency_stop_raises_in_failsafe_corner():
    """Boundary: (0,0) dan (5,5) di dalam pojok failsafe; (6,6) di luar."""
    for corner in [(0, 0), (5, 5)]:
        with pytest.raises(dn_bot.EmergencyStop):
            dn_bot.check_emergency_stop(RecordingDevice(position=corner))
    # Tepat di luar pojok (6,6) bukan emergency stop.
    dn_bot.check_emergency_stop(RecordingDevice(position=(6, 6)))


class _RaisingDevice:
    """Device whose position() raises a domain error (seam simulation)."""

    def __init__(self, error):
        self.error = error

    def position(self):
        raise self.error


@pytest.mark.parametrize(
    "error",
    [
        dn_bot.EmergencyStop("pojok kiri atas"),
        dn_bot.FocusLost("fokus hilang"),
    ],
    ids=["emergency-stop", "focus-lost"],
)
def test_check_emergency_stop_propagates_domain_errors_unchanged(error):
    """Guard: EmergencyStop/FocusLost from the device seam propagate with their
    original instance/message — never rewrapped by the broad except (survey
    candidate #2, mirroring the _call_openrouter re-raise pattern)."""
    with pytest.raises(type(error), match=re.escape(str(error))) as error_info:
        dn_bot.check_emergency_stop(_RaisingDevice(error))
    assert error_info.value is error


def test_backoff_sleep_aborts_immediately_on_emergency_corner():
    """Backoff sleep aborts before the first interval if the corner is already hit."""
    with patch.object(dn_bot.safety, "check_target_window"), patch.object(
        dn_bot.safety.time, "sleep"
    ) as sleep_mock:
        with pytest.raises(dn_bot.EmergencyStop):
            dn_bot.safety._safe_sleep(2, device=RecordingDevice(position=(0, 0)))

    sleep_mock.assert_not_called()  # aborted before sleeping even once


def test_backoff_sleep_detects_emergency_mid_delay():
    """Backoff sleep aborts when the corner is hit during the delay."""
    device = RecordingDevice(position=(100, 100))

    def _hit_corner_mid_sleep(_seconds):
        device.set_position((0, 0))

    with patch.object(dn_bot.safety, "check_target_window"), patch.object(
        dn_bot.safety.time, "sleep", side_effect=_hit_corner_mid_sleep
    ):
        with pytest.raises(dn_bot.EmergencyStop):
            dn_bot.safety._safe_sleep(2, device=device)


def test_backoff_sleep_completes_when_no_emergency():
    """Backoff sleep runs the full duration in short intervals when no abort."""
    sleeps = []
    device = RecordingDevice(position=(100, 100))
    with patch.object(dn_bot.safety, "check_target_window"), patch.object(
        dn_bot.safety.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)
    ):
        dn_bot.safety._safe_sleep(0.05, device=device)

    assert sleeps
    assert all(0 < seconds <= 0.05 for seconds in sleeps)
    # The safety checks kept consulting the device's cursor throughout the delay.
    assert ("position", ()) in device.calls


def test_call_openrouter_preserves_short_error_detail():
    short_detail = "config problem"

    def create(**payload):
        raise _FakeAPIError(short_detail, 401)

    with patch.object(dn_bot.api, "_safe_sleep"):
        try:
            dn_bot._call_openrouter(_fake_client(create), "test/free", [])
        except RuntimeError as error:
            assert short_detail in str(error)
            assert "terpotong" not in str(error)
        else:
            raise AssertionError("Config errors must surface as RuntimeError")


def test_call_openrouter_retries_network_timeout_then_succeeds():
    attempts = {"count": 0}

    def create(**payload):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise _FakeTimeoutError("timed out")
        return _sdk_response(content="baik")

    with patch.object(dn_bot.api, "_safe_sleep"):
        result = dn_bot._call_openrouter(_fake_client(create), "test/free", [])

    assert result == dn_bot.ModelReply(text="baik", tool_requests=[])
    assert attempts["count"] == 2


def test_call_openrouter_timeout_errors_retry_then_surface_as_network():
    """A timeout-class error maps to network (retryable), not unknown.

    Guard: a request that exceeds OPENROUTER_TIMEOUT raises an SDK timeout
    error; the taxonomy must classify it as a retryable network failure, so
    the retry loop retries it and, when exhausted, surfaces the actionable
    network message instead of the unknown-kind fallback.
    """
    attempts = {"count": 0}

    def create(**payload):
        attempts["count"] += 1
        raise _FakeTimeoutError("timed out")

    with patch.object(dn_bot.api, "_safe_sleep"):
        with pytest.raises(
            RuntimeError, match=dn_bot.api.API_ERROR_MESSAGES["network"]
        ) as error_info:
            dn_bot._call_openrouter(_fake_client(create), "test/free", [])

    assert attempts["count"] == dn_bot.API_MAX_ATTEMPTS
    assert "timed out" in str(error_info.value)


def test_call_openrouter_propagates_emergency_during_backoff():
    """EmergencyStop from the backoff sleep aborts the session, unretried.

    Guard: the retry loop must not classify/wrap the emergency error into a
    RuntimeError — the user hitting the failsafe corner mid-delay stops the
    session immediately with no further request.
    """
    attempts = {"count": 0}

    def create(**payload):
        attempts["count"] += 1
        raise _FakeAPIError("rate limited", 429)

    with patch.object(
        dn_bot.api, "_safe_sleep", side_effect=dn_bot.EmergencyStop("pojok kiri atas")
    ):
        with pytest.raises(dn_bot.EmergencyStop):
            dn_bot._call_openrouter(_fake_client(create), "test/free", [])

    assert attempts["count"] == 1  # no retry after the emergency abort


def test_call_openrouter_propagates_focus_lost_during_backoff():
    """FocusLost from the backoff sleep aborts the session, unretried."""
    attempts = {"count": 0}

    def create(**payload):
        attempts["count"] += 1
        raise _FakeAPIError("server error", 500)

    with patch.object(
        dn_bot.api, "_safe_sleep", side_effect=dn_bot.FocusLost("fokus hilang")
    ):
        with pytest.raises(dn_bot.FocusLost):
            dn_bot._call_openrouter(_fake_client(create), "test/free", [])

    assert attempts["count"] == 1  # no retry after the focus abort


def test_run_dn_bot_stops_after_retries_without_running_actions():
    attempts = {"count": 0}

    def create(**payload):
        attempts["count"] += 1
        raise _FakeAPIError("rate limited", 429)

    client = _fake_client(create)
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client", return_value=client    ), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=SimpleNamespace(encoded="frame")
    ), patch.object(dn_bot.orchestrator, "execute_game_action") as execute, patch.object(
        dn_bot.orchestrator, "check_emergency_stop"
    ), patch.object(dn_bot.api, "_safe_sleep"):
        dn_bot.run_dn_bot("go", max_steps=1)

    assert attempts["count"] == dn_bot.API_MAX_ATTEMPTS
    execute.assert_not_called()


def test_run_dn_bot_retried_call_runs_action_exactly_once():
    attempts = {"count": 0}

    def create(**payload):
        attempts["count"] += 1
        if attempts["count"] == 1:
            raise _FakeAPIError("rate limited", 429)
        return SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(
                        content=None,
                        tool_calls=[
                            SimpleNamespace(
                                id="call-1",
                                function=SimpleNamespace(
                                    name="dragon_nest_action",
                                    arguments='{"action":"wait"}',
                                ),
                            )
                        ],
                    )
                )
            ]
        )

    frame = SimpleNamespace(encoded="frame")
    client = _fake_client(create)
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client", return_value=client), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(dn_bot.orchestrator, "execute_game_action") as execute, patch.object(
        dn_bot.orchestrator, "check_emergency_stop"
    ), patch.object(dn_bot.api, "_safe_sleep"):
        dn_bot.run_dn_bot("go", max_steps=1)

    assert attempts["count"] == 2
    execute.assert_called_once_with(
        action="wait",
        coordinate=None,
        text=None,
        duration=dn_bot.MOVE_DURATION,
        frame=frame,
        device=ANY,
    )


def test_system_prompt_marks_screenshot_content_as_untrusted():
    """Guard: screenshot content is explicitly marked untrusted with delimiters."""
    prompt = dn_bot.SYSTEM_PROMPT
    assert "<untrusted_screenshot>" in prompt
    assert "</untrusted_screenshot>" in prompt
    assert "tidak tepercaya" in prompt.lower()
    assert "bukan instruksi" in prompt.lower()


def test_system_prompt_stops_on_ambiguous_screen():
    """Guard: ambiguous screens must end the session without a tool call."""
    prompt = dn_bot.SYSTEM_PROMPT.lower()
    assert "ambigu" in prompt
    assert "tidak ada tool call" in prompt


def test_preflight_rejects_non_windows_platform():
    with patch.object(dn_bot.config.os, "name", "posix"):
        try:
            dn_bot.preflight_configuration()
        except RuntimeError as error:
            assert "Windows" in str(error)
        else:
            raise AssertionError("Non-Windows platform must be rejected")


def test_check_target_window_fails_closed_on_non_windows():
    with patch.object(dn_bot.safety.os, "name", "posix"):
        try:
            dn_bot.check_target_window()
        except dn_bot.FocusLost as error:
            assert "Windows" in str(error)
        else:
            raise AssertionError(
                "Focus check must be fail-closed on non-Windows platforms"
            )


def test_sanitize_log_text_strips_ansi_and_control_chars():
    assert dn_bot._sanitize_log_text("\x1b[31mRED\x1b[0m") == "RED"
    assert dn_bot._sanitize_log_text("line1\nline2\tend\x07") == "line1line2end"
    assert (
        dn_bot._sanitize_log_text("Dragon Nest — 冒险者") == "Dragon Nest — 冒险者"
    )


def test_check_target_window_sanitizes_hostile_window_title():
    import ctypes

    user32 = ctypes.windll.user32

    def _write_title(_hwnd, buf, _length):
        buf.value = "\x1b[31mOther Window\x1b[0m"

    with patch.dict(os.environ, {"DN_WINDOW_TITLE": "Dragon Nest"}), patch.object(
        user32, "GetForegroundWindow", return_value=1
    ), patch.object(user32, "GetWindowTextLengthW", return_value=40), patch.object(
        user32, "GetWindowTextW", side_effect=_write_title
    ):
        try:
            dn_bot.check_target_window()
        except dn_bot.FocusLost as error:
            assert "\x1b" not in str(error)
            assert "Other Window" in str(error)
        else:
            raise AssertionError("Focus mismatch must raise FocusLost")


def test_preflight_requires_openrouter_api_key():
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_MODEL": "test/free",
            "DN_WINDOW_TITLE": "Dragon Nest",
        },
        clear=True,
    ):
        try:
            dn_bot.preflight_configuration()
        except RuntimeError as error:
            assert "OPENROUTER_API_KEY" in str(error)
        else:
            raise AssertionError("Missing API key must be rejected")


def test_preflight_requires_openrouter_model():
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": _VALID_API_KEY,
            "DN_WINDOW_TITLE": "Dragon Nest",
        },
        clear=True,
    ):
        try:
            dn_bot.preflight_configuration()
        except RuntimeError as error:
            assert "OPENROUTER_MODEL" in str(error)
        else:
            raise AssertionError("Missing model must be rejected")


def test_preflight_requires_window_title():
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": _VALID_API_KEY, "OPENROUTER_MODEL": "test/free"},
        clear=True,
    ):
        try:
            dn_bot.preflight_configuration()
        except RuntimeError as error:
            assert "DN_WINDOW_TITLE" in str(error)
        else:
            raise AssertionError("Missing window title must be rejected")


def test_preflight_rejects_partial_capture_rect():
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": _VALID_API_KEY,
            "OPENROUTER_MODEL": "test/free",
            "DN_WINDOW_TITLE": "Dragon Nest",
            "DN_CAPTURE_LEFT": "137",
            "DN_CAPTURE_TOP": "83",
            "DN_CAPTURE_WIDTH": "1920",
        },
        clear=True,
    ):
        try:
            dn_bot.preflight_configuration()
        except ValueError as error:
            assert "DN_CAPTURE_LEFT/TOP/WIDTH/HEIGHT" in str(error)
        else:
            raise AssertionError("Partial capture rect must be rejected")


def test_preflight_rejects_non_integer_capture_value():
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": _VALID_API_KEY,
            "OPENROUTER_MODEL": "test/free",
            "DN_WINDOW_TITLE": "Dragon Nest",
            "DN_CAPTURE_LEFT": "137",
            "DN_CAPTURE_TOP": "83",
            "DN_CAPTURE_WIDTH": "lebar",
            "DN_CAPTURE_HEIGHT": "1080",
        },
        clear=True,
    ):
        try:
            dn_bot.preflight_configuration()
        except ValueError as error:
            assert "DN_CAPTURE_WIDTH harus berupa bilangan bulat" in str(error)
        else:
            raise AssertionError("Non-integer capture value must be rejected")


def test_preflight_rejects_invalid_monitor():
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": _VALID_API_KEY,
            "OPENROUTER_MODEL": "test/free",
            "DN_WINDOW_TITLE": "Dragon Nest",
            "DN_MONITOR": "dua",
        },
        clear=True,
    ):
        try:
            dn_bot.preflight_configuration()
        except ValueError as error:
            assert "DN_MONITOR harus berupa bilangan bulat" in str(error)
        else:
            raise AssertionError("Non-integer monitor must be rejected")


@pytest.mark.parametrize(
    "api_key,expected_text",
    [
        ("sk-or-v1-your-key-here", "placeholder"),
        ("sk-or-v1-abc", "sk-or-v1"),
        ("test-key", "tampak tidak valid"),
    ],
    ids=["placeholder", "too-short-prefix", "no-prefix"],
)
def test_preflight_rejects_invalid_api_key_format(api_key, expected_text):
    """Clearly-invalid keys fail fast at preflight with an actionable message
    instead of surfacing as a 401 at runtime (T7)."""
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": api_key,
            "OPENROUTER_MODEL": "test/free",
            "DN_WINDOW_TITLE": "Dragon Nest",
        },
        clear=True,
    ):
        with pytest.raises(RuntimeError, match=expected_text) as error_info:
            dn_bot.preflight_configuration()

    assert ".env" in str(error_info.value)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("sk-or-v1-" + "a" * 48, True),
        (
            "sk-or-v1-"
            + "a"
            * (dn_bot.config.OPENROUTER_KEY_MIN_LENGTH - len(dn_bot.config.OPENROUTER_KEY_PREFIX)),
            True,
        ),
        (
            "sk-or-v1-"
            + "a"
            * (dn_bot.config.OPENROUTER_KEY_MIN_LENGTH - len(dn_bot.config.OPENROUTER_KEY_PREFIX) - 1),
            False,
        ),
        ("sk-or-v1-your-key-here", False),
        ("sk-or-v1-abc", False),
        ("test-key", False),
        ("", False),
    ],
    ids=[
        "valid",
        "exact-minimum",
        "below-minimum",
        "placeholder",
        "too-short",
        "no-prefix",
        "empty",
    ],
)
def test_is_plausible_openrouter_key(value, expected):
    """Shape check is conservative: never rejects a real key, always catches
    the clearly-invalid values (boundary included)."""
    assert dn_bot.config._is_plausible_openrouter_key(value) is expected


def test_preflight_accepts_valid_configuration():
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": _VALID_API_KEY,
            "OPENROUTER_MODEL": "test/free",
            "DN_WINDOW_TITLE": "Dragon Nest",
        },
        clear=True,
    ):
        dn_bot.preflight_configuration()


def test_default_instruction_used_when_nothing_set():
    with patch.dict(os.environ, {}, clear=True):
        instruction = dn_bot.__main__._resolve_instruction(None)

    assert instruction == dn_bot.config.DEFAULT_INSTRUCTION
    # Byte-identical to the pre-T3 hardcoded text (no-args behavior unchanged).
    assert instruction == (
        "Amati screenshot. Jika ada NPC yang jelas terlihat dan aman untuk "
        "didekati, dekati secara perlahan lalu gunakan F untuk interaksi. "
        "Jika tujuan tidak jelas, jangan melakukan aksi."
    )


def test_env_instruction_used_when_set():
    with patch.dict(os.environ, {"DN_INSTRUCTION": "dekati merchant"}, clear=True):
        instruction = dn_bot.__main__._resolve_instruction(None)

    assert instruction == "dekati merchant"


def test_cli_instruction_wins_over_env():
    with patch.dict(os.environ, {"DN_INSTRUCTION": "env-text"}, clear=True):
        instruction = dn_bot.__main__._resolve_instruction("cli-text")

    assert instruction == "cli-text"


def test_main_plumbs_cli_instruction_to_run_dn_bot():
    with patch.object(
        dn_bot.__main__, "preflight_configuration"
    ), patch.object(dn_bot.__main__.time, "sleep"), patch.object(
        dn_bot.__main__, "run_dn_bot"
    ) as run:
        dn_bot.__main__.main(["--instruction", "cli-text"])

    run.assert_called_once_with("cli-text")


def test_main_plumbs_env_instruction_when_no_flag():
    with patch.dict(
        os.environ, {"DN_INSTRUCTION": "env-text"}, clear=True
    ), patch.object(
        dn_bot.__main__, "preflight_configuration"
    ), patch.object(dn_bot.__main__.time, "sleep"), patch.object(
        dn_bot.__main__, "run_dn_bot"
    ) as run:
        dn_bot.__main__.main([])

    run.assert_called_once_with("env-text")


def test_main_uses_default_instruction_when_nothing_set():
    with patch.dict(os.environ, {}, clear=True), patch.object(
        dn_bot.__main__, "preflight_configuration"
    ), patch.object(dn_bot.__main__.time, "sleep"), patch.object(
        dn_bot.__main__, "run_dn_bot"
    ) as run:
        dn_bot.__main__.main([])

    run.assert_called_once_with(dn_bot.config.DEFAULT_INSTRUCTION)


def test_dry_run_device_logs_intended_actions_without_executing():
    """DryRunDevice logs every intended physical primitive (prefix [dry-run])
    and records it in ``calls`` — nothing is performed."""
    with patch.object(dn_bot.device.log, "info") as log_info:
        device = dn_bot.DryRunDevice()
        device.moveTo(10, 20)
        device.keyDown("w")
        device.keyUp("w")
        device.click()
        device.rightClick()

    # Each primitive logs the intended call (format string + args) — the
    # operator sees exactly what would have been performed.
    assert log_info.call_args_list == [
        call("[dry-run] moveTo(%d, %d)", 10, 20),
        call("[dry-run] keyDown(%s)", "w"),
        call("[dry-run] keyUp(%s)", "w"),
        call("[dry-run] click()"),
        call("[dry-run] rightClick()"),
    ]
    assert device.calls == [
        ("moveTo", (10, 20)),
        ("keyDown", ("w",)),
        ("keyUp", ("w",)),
        ("click", ()),
        ("rightClick", ()),
    ]


def test_dry_run_device_position_never_triggers_emergency_stop():
    """The dry-run cursor is a fixed safe coordinate, so real emergency-stop
    checks pass trivially during a rehearsal (no physical cursor can hit the
    failsafe corner; Ctrl+C remains the abort)."""
    device = dn_bot.DryRunDevice()
    assert device.position() == dn_bot.DryRunDevice.SAFE_POSITION
    dn_bot.check_emergency_stop(device)  # must not raise


def test_parse_args_accepts_dry_run_flag():
    assert dn_bot.__main__._parse_args(["--dry-run"]).dry_run is True
    assert dn_bot.__main__._parse_args([]).dry_run is False
    args = dn_bot.__main__._parse_args(["--dry-run", "--instruction", "x"])
    assert args.dry_run is True and args.instruction == "x"


def test_main_dry_run_flag_propagates_dry_run_device():
    """The --dry-run flag makes main() select the rehearsal device, so the
    session path receives a DryRunDevice instead of the production adapter."""
    with patch.object(
        dn_bot.__main__, "preflight_configuration"
    ), patch.object(dn_bot.__main__.time, "sleep"), patch.object(
        dn_bot.__main__, "run_dn_bot"
    ) as run:
        dn_bot.__main__.main(["--dry-run"])

    run.assert_called_once()
    assert isinstance(run.call_args.kwargs["device"], dn_bot.DryRunDevice)


def test_run_dn_bot_default_session_uses_production_device():
    """Non-dry-run default: the session threads the production adapter through
    both the emergency guard and the action — byte-identical behavior."""
    frame = SimpleNamespace(encoded="frame")
    replies = iter(
        [
            dn_bot.ModelReply(
                text="",
                tool_requests=[
                    dn_bot.ToolRequest(id="call-1", input={"action": "wait"})
                ],
            ),
            dn_bot.ModelReply(text="selesai", tool_requests=[]),
        ]
    )
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client"), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator,
        "_call_openrouter",
        side_effect=lambda *args, **kwargs: next(replies),
    ), patch.object(dn_bot.orchestrator, "execute_game_action") as execute, patch.object(
        dn_bot.orchestrator, "check_emergency_stop"
    ) as emergency:
        dn_bot.run_dn_bot("go", max_steps=2)

    device = execute.call_args.kwargs["device"]
    assert isinstance(device, dn_bot.PyDirectInputDevice)
    # The same injected device is threaded through the emergency guard
    # (passed positionally, like the safety helpers do).
    assert emergency.call_args.args[0] is device


def test_new_session_id_is_unique_and_log_safe():
    first = dn_bot._new_session_id()
    second = dn_bot._new_session_id()
    assert first != second
    assert len(first) >= 8
    assert all(ch.isalnum() or ch == "-" for ch in first)


def test_call_openrouter_logs_request_latency():
    def create(**payload):
        return _sdk_response()

    calls = []
    with patch.object(
        dn_bot.api.log, "info", side_effect=lambda *args: calls.append(args)
    ):
        dn_bot._call_openrouter(_fake_client(create), "test/free", [])

    assert any(
        isinstance(args[0], str) and "OpenRouter request selesai" in args[0]
        for args in calls
    )


def test_recording_device_records_exact_call_sequence():
    device = RecordingDevice(position=(50, 60))
    assert device.position() == (50, 60)
    device.moveTo(1, 2)
    device.keyDown("w")
    device.keyUp("w")
    device.click()
    device.rightClick()
    device.set_position((0, 0))
    assert device.position() == (0, 0)

    device.assert_calls(
        [
            ("position", ()),
            ("moveTo", (1, 2)),
            ("keyDown", ("w",)),
            ("keyUp", ("w",)),
            ("click", ()),
            ("rightClick", ()),
            ("position", ()),
        ]
    )


def test_messages_contract_wire_shapes():
    assert dn_bot.user_text("go") == {"role": "user", "content": "go"}
    assert dn_bot.image_block("abc") == {
        "type": "image_url",
        "image_url": {"url": "data:image/jpeg;base64,abc"},
    }
    assert dn_bot.frame_message("abc", "cap") == {
        "role": "user",
        "content": [
            {"type": "text", "text": "cap"},
            {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64,abc"}},
        ],
    }
    assert dn_bot.tool_result("c1", "ok") == {
        "role": "tool",
        "tool_call_id": "c1",
        "content": "ok",
    }
    assert dn_bot.assistant_message("halo", []) == {
        "role": "assistant",
        "content": "halo",
    }
    calls = [
        {
            "id": "c1",
            "type": "function",
            "function": {
                "name": "dragon_nest_action",
                "arguments": '{"action": "wait"}',
            },
        }
    ]
    assert dn_bot.assistant_message("halo", calls) == {
        "role": "assistant",
        "content": "halo",
        "tool_calls": calls,
    }


def test_messages_tool_calls_wire_rebuilds_arguments_from_input():
    requests = [
        dn_bot.ToolRequest(id="call-1", input={"action": "wait", "duration": 0.1})
    ]

    assert dn_bot.tool_calls_wire(requests) == [
        {
            "id": "call-1",
            "type": "function",
            "function": {
                "name": "dragon_nest_action",
                "arguments": '{"action": "wait", "duration": 0.1}',
            },
        }
    ]


def test_call_openrouter_does_not_retry_malformed_response():
    attempts = {"count": 0}

    def create(**payload):
        attempts["count"] += 1
        return _sdk_response(tool_calls=[_sdk_tool_call("call-1", "not-json")])

    with patch.object(dn_bot.api, "_safe_sleep"):
        with pytest.raises(ValueError, match="JSON"):
            dn_bot._call_openrouter(_fake_client(create), "test/free", [])

    assert attempts["count"] == 1


def test_call_openrouter_parses_tool_requests_into_model_reply():
    def create(**payload):
        return _sdk_response(
            content="akan pindah",
            tool_calls=[_sdk_tool_call("call-1", '{"action": "wait"}')],
        )

    reply = dn_bot._call_openrouter(_fake_client(create), "test/free", [])

    assert reply == dn_bot.ModelReply(
        text="akan pindah",
        tool_requests=[dn_bot.ToolRequest(id="call-1", input={"action": "wait"})],
    )


def test_run_dn_bot_consumes_plain_model_reply():
    frame = SimpleNamespace(encoded="frame")
    replies = iter(
        [
            dn_bot.ModelReply(
                text="",
                tool_requests=[
                    dn_bot.ToolRequest(id="call-1", input={"action": "wait"})
                ],
            ),
            dn_bot.ModelReply(text="selesai", tool_requests=[]),
        ]
    )
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client"), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator,
        "_call_openrouter",
        side_effect=lambda *args, **kwargs: next(replies),
    ), patch.object(dn_bot.orchestrator, "execute_game_action") as execute, patch.object(
        dn_bot.orchestrator, "check_emergency_stop"
    ):
        dn_bot.run_dn_bot("go", max_steps=2)

    execute.assert_called_once_with(
        action="wait",
        coordinate=None,
        text=None,
        duration=dn_bot.MOVE_DURATION,
        frame=frame,
        device=ANY,
    )


def test_run_dn_bot_action_failure_message_is_sanitized():
    """Wrapper RuntimeError di orchestrator menyimpan aksi yang disanitasi (F-05)."""
    frame = SimpleNamespace(encoded="frame")
    replies = iter(
        [
            dn_bot.ModelReply(
                text="",
                tool_requests=[
                    dn_bot.ToolRequest(
                        id="call-1", input={"action": "\x1b[31mINJECT\x1b[0m"}
                    )
                ],
            ),
        ]
    )
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ), patch.object(dn_bot.orchestrator, "get_openrouter_client"), patch.object(
        dn_bot.orchestrator, "capture_screen_base64", return_value=frame
    ), patch.object(
        dn_bot.orchestrator,
        "_call_openrouter",
        side_effect=lambda *args, **kwargs: next(replies),
    ), patch.object(
        dn_bot.orchestrator, "execute_game_action", side_effect=ValueError("boom")
    ), patch.object(dn_bot.orchestrator, "check_emergency_stop"):
        with pytest.raises(RuntimeError, match="Aksi") as error_info:
            dn_bot.run_dn_bot("go", max_steps=1)

    assert "\x1b" not in str(error_info.value)


# --- Packaging (T4) ---

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
_PYPROJECT_PATH = _PROJECT_ROOT / "pyproject.toml"


def _entry_points_from_pyproject(text: str) -> list[tuple[str, str]]:
    """Extract (name, target) pairs from the [project.scripts] section of a
    pyproject.toml text (stdlib-only; tomllib is 3.11+, the matrix covers 3.10)."""
    section = re.search(r"\[project\.scripts\](?P<body>[\s\S]*?)(?=\n\[|\Z)", text)
    assert section, "pyproject.toml harus punya section [project.scripts]"
    entries = []
    for line in section.group("body").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        name, target = (part.strip().strip('"') for part in line.split("=", 1))
        entries.append((name, target))
    return entries


def test_pyproject_declares_dn_bot_package_and_console_script():
    """Packaging metadata resolves without a pip install: the dn-bot console
    script declared in pyproject.toml points at a real, callable main() (T4)."""
    text = _PYPROJECT_PATH.read_text(encoding="utf-8")
    # Whitespace-tolerant guard: survives cosmetic TOML reformatting.
    assert re.search(r'packages\s*=\s*\["dn_bot"\]', text)
    assert "requires-python" in text and ">=3.10" in text

    entries = _entry_points_from_pyproject(text)
    assert entries, "pyproject.toml harus mendeklarasikan minimal satu console script"
    assert any(name == "dn-bot" for name, _ in entries)
    for name, target in entries:
        module_name, _, attr = target.partition(":")
        module = importlib.import_module(module_name)
        assert callable(getattr(module, attr)), f"{name}: {target} tidak callable"


def test_pyproject_runtime_dependencies_match_requirements_txt():
    """Drift guard: pyproject.toml dependencies mirror requirements.txt exactly,
    so requirements.txt stays the single source of truth for runtime pins."""
    req_specs = {
        line.strip()
        for line in (_PROJECT_ROOT / "requirements.txt")
        .read_text(encoding="utf-8")
        .splitlines()
        if line.strip() and not line.strip().startswith("#")
    }
    text = _PYPROJECT_PATH.read_text(encoding="utf-8")
    block = re.search(
        r"\[project\][\s\S]*?dependencies = \[(?P<deps>[\s\S]*?)\]", text
    )
    assert block, "pyproject.toml harus punya blok dependencies di [project]"
    pyproject_specs = {
        match.group(1)
        for match in re.finditer(r'"([A-Za-z0-9._-]+==[^"]+)"', block.group("deps"))
    }
    assert pyproject_specs == req_specs


def test_dn_bot_runs_from_foreign_cwd_with_pythonpath():
    """Guard: 'python -m dn_bot' works when the package is importable from any
    cwd (installed, or here simulated via PYTHONPATH) — the pre-T4 cwd wart is
    gone. Uses the current interpreter; no pip install is required."""
    with tempfile.TemporaryDirectory() as tmp:
        env = {**os.environ, "PYTHONPATH": str(_PROJECT_ROOT)}
        result = subprocess.run(
            [sys.executable, "-m", "dn_bot", "--help"],
            cwd=tmp,
            env=env,
            capture_output=True,
            text=True,
            timeout=60,
        )
    assert result.returncode == 0, result.stderr
    assert "--instruction" in result.stdout
    assert "Dragon Nest" in result.stdout
