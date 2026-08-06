"""Shared fixtures for the offline ``dn_bot`` test suite.

The project root is importable because ``pytest.ini`` sets ``pythonpath = .``;
no manual ``sys.path`` manipulation is needed here.
"""

from types import SimpleNamespace

import pytest

import dn_bot


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


@pytest.fixture
def capture_region():
    """Build an immutable :class:`dn_bot.Frame` for a given capture region.

    Capture is deterministic: ``capture_screen_base64`` returns a ``Frame``
    (encoded JPEG + letterbox geometry) and coordinate mapping takes that frame
    explicitly. There are no module-level capture globals left to patch.

    Usage::

        def test_something(capture_region):
            frame = capture_region({"left": 0, "top": 0, "width": 1024, "height": 768})
            dn_bot._physical_point([512, 384], frame)
    """

    def apply(region, encoded=""):
        return dn_bot.Frame(
            encoded=encoded,
            geometry=dn_bot._geometry_for_region(region),
        )

    return apply
