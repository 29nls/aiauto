import os
import pytest
from types import SimpleNamespace
from unittest.mock import patch

import dn_bot
from PIL import Image


class _FakeAPIError(Exception):
    """Mirrors openai.APIStatusError subclasses (e.g. RateLimitError)."""

    def __init__(self, message="boom", status_code=None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


class _FakeTimeoutError(Exception):
    """Mirrors openai.APITimeoutError: no status_code attribute."""


def _fake_client(create):
    return SimpleNamespace(
        chat=SimpleNamespace(completions=SimpleNamespace(create=create))
    )


def _sdk_response(content=None, tool_calls=()):
    """SDK-shaped response with a message that carries text + tool calls."""
    return SimpleNamespace(
        choices=[
            SimpleNamespace(
                message=SimpleNamespace(content=content, tool_calls=list(tool_calls))
            )
        ]
    )


def _sdk_tool_call(call_id, arguments):
    """SDK-shaped tool call object for dragon_nest_action."""
    return SimpleNamespace(
        id=call_id,
        function=SimpleNamespace(name="dragon_nest_action", arguments=arguments),
    )


def test_openrouter_client_uses_configured_openrouter_base_url():
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key"},
        clear=False,
    ):
        client = dn_bot.get_openrouter_client()

    assert client.api_key == "test-key"
    assert str(client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"


def test_move_camera_anchors_at_center_before_absolute_endpoint(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    calls = []
    with patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control.pydirectinput, "position", return_value=(900, 700)
    ), patch.object(
        dn_bot.input_control.pydirectinput, "moveTo", side_effect=lambda *point: calls.append(point)
    ), patch.object(
        dn_bot.input_control.pydirectinput, "moveRel"
    ) as move_rel, patch.object(dn_bot.input_control, "_safe_sleep"), patch.object(
        dn_bot.input_control, "check_emergency_stop"
    ):
        dn_bot.execute_game_action("move_camera", coordinate=[800, 600], frame=frame)

    assert calls == [(512, 384), (800, 600)]
    move_rel.assert_not_called()


def test_repeated_move_camera_calls_reanchor_before_each_endpoint(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    calls = []
    with patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control.pydirectinput, "position", return_value=(12, 700)
    ), patch.object(
        dn_bot.input_control.pydirectinput, "moveTo", side_effect=lambda *point: calls.append(point)
    ), patch.object(
        dn_bot.input_control, "_safe_sleep"
    ), patch.object(dn_bot.input_control, "check_emergency_stop"):
        dn_bot.execute_game_action("move_camera", coordinate=[800, 600], frame=frame)
        dn_bot.execute_game_action("move_camera", coordinate=[200, 300], frame=frame)

    assert calls == [(512, 384), (800, 600), (512, 384), (200, 300)]


def test_move_camera_rejects_padding_before_moving_cursor(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1920, "height": 1080})
    with patch.object(
        dn_bot.input_control, "check_target_window"
    ), patch.object(dn_bot.input_control, "check_emergency_stop"), patch.object(
        dn_bot.input_control.pydirectinput, "moveTo"
    ) as move_to, patch.object(dn_bot.input_control, "_safe_sleep"):
        with pytest.raises(ValueError, match="padding"):
            dn_bot.execute_game_action("move_camera", coordinate=[512, 95], frame=frame)

    move_to.assert_not_called()


def test_move_camera_rejects_missing_coordinate(capture_region):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    with patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control, "check_emergency_stop"
    ):
        with pytest.raises(ValueError, match="coordinate"):
            dn_bot.execute_game_action("move_camera", frame=frame)


@pytest.mark.parametrize("duration", ["slow", float("nan"), float("inf")])
def test_execute_game_action_rejects_invalid_duration(capture_region, duration):
    frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
    with patch.object(dn_bot.input_control, "check_target_window"), patch.object(
        dn_bot.input_control.pydirectinput, "position", return_value=(100, 100)
    ):
        with pytest.raises(ValueError, match="duration"):
            dn_bot.execute_game_action("wait", duration=duration, frame=frame)


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


def test_classify_api_error_kinds():
    assert dn_bot._classify_api_error(_FakeAPIError(status_code=401)) == "auth"
    assert dn_bot._classify_api_error(_FakeAPIError(status_code=403)) == "auth"
    assert dn_bot._classify_api_error(_FakeAPIError(status_code=404)) == "not_found"
    assert dn_bot._classify_api_error(_FakeAPIError(status_code=400)) == "invalid_request"
    assert dn_bot._classify_api_error(_FakeAPIError(status_code=422)) == "invalid_request"
    assert dn_bot._classify_api_error(_FakeAPIError(status_code=429)) == "rate_limit"
    assert dn_bot._classify_api_error(_FakeAPIError(status_code=408)) == "network"
    assert dn_bot._classify_api_error(_FakeAPIError(status_code=500)) == "server"
    assert dn_bot._classify_api_error(_FakeAPIError(status_code=503)) == "server"
    assert dn_bot._classify_api_error(_FakeAPIError(status_code=409)) == "http"
    assert dn_bot._classify_api_error(_FakeTimeoutError()) == "network"
    assert dn_bot._classify_api_error(Exception("bukan error API")) == "unknown"


def test_call_openrouter_retries_rate_limit_then_succeeds():
    attempts = {"count": 0}

    def create(**payload):
        attempts["count"] += 1
        if attempts["count"] < 3:
            raise _FakeAPIError("rate limited", 429)
        return _sdk_response(content="baik")

    sleeps = []
    with patch.object(
        dn_bot.api.time, "sleep", side_effect=lambda seconds: sleeps.append(seconds)
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

    with patch.object(dn_bot.api.time, "sleep"):
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

    with patch.object(dn_bot.api.time, "sleep"):
        with pytest.raises(RuntimeError, match=expected_text):
            dn_bot._call_openrouter(_fake_client(create), "test/free", [])

    assert attempts["count"] == 1


def test_call_openrouter_truncates_long_error_detail():
    long_detail = "x" * (dn_bot.config.API_ERROR_DETAIL_MAX + 100)

    def create(**payload):
        raise _FakeAPIError(long_detail, 401)

    with patch.object(dn_bot.api.time, "sleep"):
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


def test_call_openrouter_preserves_short_error_detail():
    short_detail = "config problem"

    def create(**payload):
        raise _FakeAPIError(short_detail, 401)

    with patch.object(dn_bot.api.time, "sleep"):
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

    with patch.object(dn_bot.api.time, "sleep"):
        result = dn_bot._call_openrouter(_fake_client(create), "test/free", [])

    assert result == dn_bot.ModelReply(text="baik", tool_requests=[])
    assert attempts["count"] == 2


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
    ), patch.object(dn_bot.orchestrator.time, "sleep"):
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
    ), patch.object(dn_bot.orchestrator.time, "sleep"):
        dn_bot.run_dn_bot("go", max_steps=1)

    assert attempts["count"] == 2
    execute.assert_called_once_with(
        action="wait",
        coordinate=None,
        text=None,
        duration=dn_bot.MOVE_DURATION,
        frame=frame,
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
            "OPENROUTER_API_KEY": "test-key",
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
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
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
            "OPENROUTER_API_KEY": "test-key",
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
            "OPENROUTER_API_KEY": "test-key",
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
            "OPENROUTER_API_KEY": "test-key",
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


def test_preflight_accepts_valid_configuration():
    with patch.dict(
        os.environ,
        {
            "OPENROUTER_API_KEY": "test-key",
            "OPENROUTER_MODEL": "test/free",
            "DN_WINDOW_TITLE": "Dragon Nest",
        },
        clear=True,
    ):
        dn_bot.preflight_configuration()


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

    with patch.object(dn_bot.api.time, "sleep"):
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
    )
