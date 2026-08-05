import io
import os
from types import SimpleNamespace
from unittest.mock import patch

import app_dn
from PIL import Image


def test_openrouter_client_uses_configured_openrouter_base_url():
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key"},
        clear=False,
    ):
        client = app_dn.get_openrouter_client()

    assert client.api_key == "test-key"
    assert str(client.base_url).rstrip("/") == "https://openrouter.ai/api/v1"


def test_execute_game_action_rejects_invalid_duration():
    with patch.object(app_dn, "check_target_window"), patch.object(
        app_dn.pydirectinput, "position", return_value=(100, 100)
    ):
        for duration in ("slow", float("nan"), float("inf")):
            try:
                app_dn.execute_game_action("wait", duration=duration)
            except ValueError as error:
                assert "duration" in str(error)
            else:
                raise AssertionError("Invalid duration should be rejected")


def test_run_dn_bot_rejects_non_string_instruction_and_non_integer_steps():
    with patch.dict(
        os.environ,
        {"OPENROUTER_API_KEY": "test-key", "OPENROUTER_MODEL": "test/free"},
        clear=False,
    ):
        for instruction, max_steps in ((None, 1), ("go", 1.5)):
            try:
                app_dn.run_dn_bot(instruction, max_steps=max_steps)
            except ValueError:
                pass
            else:
                raise AssertionError("Invalid run configuration should be rejected")


def test_16_9_geometry_records_vertical_letterbox_padding():
    geometry = app_dn._geometry_for_region(
        {"left": 137, "top": 83, "width": 1920, "height": 1080}
    )

    assert (geometry.content_width, geometry.content_height) == (1024, 576)
    assert (geometry.offset_x, geometry.offset_y) == (0, 96)


def test_2_to_1_geometry_records_vertical_letterbox_padding():
    geometry = app_dn._geometry_for_region(
        {"left": 37, "top": 61, "width": 1000, "height": 500}
    )

    assert (geometry.content_width, geometry.content_height) == (1024, 512)
    assert (geometry.offset_x, geometry.offset_y) == (0, 128)


def test_letterbox_preserves_content_and_padding_for_16_9_image():
    image = Image.new("RGB", (16, 9), (255, 0, 0))
    geometry = app_dn._geometry_for_region(
        {"left": 0, "top": 0, "width": 16, "height": 9}
    )

    result = app_dn._letterbox(image, geometry)

    assert result.size == (app_dn.TARGET_WIDTH, app_dn.TARGET_HEIGHT)
    assert result.getpixel((512, 95)) == (0, 0, 0)
    assert result.getpixel((512, 96))[0] > 200
    assert result.getpixel((512, 671))[0] > 200
    assert result.getpixel((512, 672)) == (0, 0, 0)


def test_letterboxed_16_9_center_maps_to_nontrivial_capture_region():
    with patch.object(
        app_dn,
        "_capture_region",
        {"left": 137, "top": 83, "width": 1920, "height": 1080},
    ), patch.object(app_dn, "_capture_geometry", None):
        physical = app_dn._physical_point([512, 384])

    assert physical == (1097, 623)


def test_letterboxed_padding_is_not_clickable():
    with patch.object(
        app_dn,
        "_capture_region",
        {"left": 137, "top": 83, "width": 1920, "height": 1080},
    ), patch.object(app_dn, "_capture_geometry", None):
        for coordinate in ([512, 95], [512, 672]):
            try:
                app_dn._physical_point(coordinate)
            except ValueError as error:
                assert "padding" in str(error)
            else:
                raise AssertionError("Letterbox padding must not be actionable")


def test_nontrivial_2_to_1_region_maps_content_edges():
    with patch.object(
        app_dn,
        "_capture_region",
        {"left": 37, "top": 61, "width": 1000, "height": 500},
    ), patch.object(app_dn, "_capture_geometry", None):
        assert app_dn._physical_point([512, 384]) == (537, 311)
        assert app_dn._physical_point([0, 128]) == (37, 61)
        assert app_dn._physical_point([1023, 639]) == (1036, 560)


def test_nontrivial_region_padding_is_not_clickable():
    with patch.object(
        app_dn,
        "_capture_region",
        {"left": 37, "top": 61, "width": 1000, "height": 500},
    ), patch.object(app_dn, "_capture_geometry", None):
        for coordinate in ([0, 127], [0, 640]):
            try:
                app_dn._physical_point(coordinate)
            except ValueError as error:
                assert "padding" in str(error)
            else:
                raise AssertionError("Letterbox padding must not be actionable")


def test_scaled_physical_emergency_corner_is_rejected():
    with patch.object(
        app_dn,
        "_capture_region",
        {"left": 0, "top": 0, "width": 1920, "height": 1080},
    ), patch.object(app_dn, "_capture_geometry", None):
        try:
            app_dn._physical_point([0, 96])
        except ValueError as error:
            assert "emergency stop" in str(error)
        else:
            raise AssertionError("Scaled emergency corner should be rejected")


def test_negative_monitor_coordinates_are_not_emergency_corner():
    with patch.object(
        app_dn,
        "_capture_region",
        {"left": -1920, "top": -1080, "width": 1920, "height": 1080},
    ), patch.object(app_dn, "_capture_geometry", None):
        assert app_dn._physical_point([512, 384]) == (-960, -540)


def test_physical_point_rejects_non_integer_coordinates():
    try:
        app_dn._physical_point([1.5, 10])
    except ValueError as error:
        assert "dua integer" in str(error)
    else:
        raise AssertionError("Non-integer coordinates should be rejected")


def test_image_block_uses_openai_compatible_image_url_data_uri():
    block = app_dn._image_block("abc123")

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
        app_dn.extract_tool_requests(message)
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
        app_dn.extract_tool_requests(message)
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

    requests = app_dn.extract_tool_requests(message)

    assert requests == [
        {
            "id": "call-1",
            "input": {"action": "wait", "duration": 0.1},
        }
    ]
