"""dn_bot: Vision-assisted input experiment for Dragon Nest on Windows.

This project uses a vision-capable model through the official OpenAI API plus a narrow,
allow-listed tool. It does not bypass anti-cheat, inject into the game, or
guarantee that a particular Dragon Nest client accepts synthetic input.

Run the bot with ``python -m dn_bot``.
"""

from __future__ import annotations

from . import (
    api,
    capture,
    config,
    device,
    farm,
    input_control,
    messages,
    orchestrator,
    safety,
)
from .api import (
    API_ERROR_MESSAGES,
    DRAGON_NEST_TOOL,
    MINOTAUR_TOOL,
    SYSTEM_PROMPT,
    _RETRYABLE_API_KINDS,
    _call_openai,
    _call_openrouter,
    _classify_api_error,
    extract_tool_requests,
    get_openai_client,
    get_openrouter_client,
)
# Capture is deterministic: `capture_screen_base64` returns an immutable
# `Frame` (encoded JPEG + region + geometry) and coordinate mapping takes that
# frame explicitly. There are no module-level capture globals left to patch.
from .capture import (
    Frame,
    InvalidCoordinateError,
    _geometry_for_region,
    _letterbox,
    _physical_point,
    capture_screen_base64,
)
from .messages import (
    ModelReply,
    ToolRequest,
    assistant_message,
    frame_message,
    image_block,
    tool_calls_wire,
    tool_result,
    user_text,
)
from .config import (
    ACTION_COOLDOWN,
    ACTION_KEYS,
    API_MAX_ATTEMPTS,
    API_RETRY_BASE_DELAY,
    COORDINATE_MAX_RETRIES_DEFAULT,
    COORDINATE_MAX_RETRIES_ENV,
    MAX_CONTEXT_MESSAGES,
    MAX_STEPS_PER_SESSION,
    RETREAT_DESTINATIONS,
    RETREAT_DESTINATION_ENV,
    MOVE_DURATION,
    MOVE_KEYS,
    DEFAULT_PROVIDER,
    PROVIDER_ENV,
    BASE_URL_ENV,
    PROVIDER_BASE_URLS,
    OPENROUTER_BASE_URL,
    OPENAI_BASE_URL,
    START_DELAY_SECONDS,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    CaptureGeometry,
    EmergencyStop,
    FocusLost,
    _int_env,
    _validate_capture_env,
    log,
    preflight_configuration,
    resolve_coordinate_max_retries,
    resolve_provider,
    resolve_base_url,
    resolve_retreat_destination,
    validate_retreat_destination,
)
from .device import DeviceInput, DryRunDevice, PyDirectInputDevice
from .farm import (
    FarmObservationClaim,
    FarmPhasePolicy,
    FarmProfile,
    FarmSafetyStop,
    FarmState,
    FarmWatchdog,
    MINOTAUR_PHASE_POLICY,
    MINOTAUR_PROFILE,
    farm_action_values,
    farm_state_values,
)
from .input_control import _press_key, _validate_key, execute_game_action
from .orchestrator import _compact_messages, _new_session_id, run_dn_bot
from .safety import (
    _safe_sleep,
    _sanitize_log_text,
    check_emergency_stop,
    check_target_window,
)
from .replay import (
    ReplayDeviceCall,
    ReplayExpected,
    ReplayMismatch,
    ReplayReport,
    ReplayResult,
    ReplayStep,
    ReplayTrace,
    ReplayTraceError,
    load_replay_trace,
    replay_trace,
)

__all__ = [
    # Modules
    "api",
    "capture",
    "config",
    "device",
    "farm",
    "input_control",
    "messages",
    "orchestrator",
    "safety",
    # Core types & exceptions
    "CaptureGeometry",
    "EmergencyStop",
    "FocusLost",
    "InvalidCoordinateError",
    # Constants
    "ACTION_COOLDOWN",
    "ACTION_KEYS",
    "API_MAX_ATTEMPTS",
    "API_RETRY_BASE_DELAY",
    "MAX_CONTEXT_MESSAGES",
    "MAX_STEPS_PER_SESSION",
    "COORDINATE_MAX_RETRIES_DEFAULT",
    "COORDINATE_MAX_RETRIES_ENV",
    "RETREAT_DESTINATIONS",
    "RETREAT_DESTINATION_ENV",
    "MOVE_DURATION",
    "MOVE_KEYS",
    "DEFAULT_PROVIDER",
    "PROVIDER_ENV",
    "BASE_URL_ENV",
    "PROVIDER_BASE_URLS",
    "OPENROUTER_BASE_URL",
    "OPENAI_BASE_URL",
    "START_DELAY_SECONDS",
    "TARGET_HEIGHT",
    "TARGET_WIDTH",
    # Config helpers
    "_int_env",
    "_validate_capture_env",
    "preflight_configuration",
    "resolve_coordinate_max_retries",
    "resolve_provider",
    "resolve_base_url",
    "resolve_retreat_destination",
    "validate_retreat_destination",
    # Capture
    "Frame",
    "InvalidCoordinateError",
    "_geometry_for_region",
    "_letterbox",
    "_physical_point",
    "capture_screen_base64",
    # Message contract (wire-shape)
    "ModelReply",
    "ToolRequest",
    "assistant_message",
    "frame_message",
    "image_block",
    "tool_calls_wire",
    "tool_result",
    "user_text",
    # Safety
    "_safe_sleep",
    "_sanitize_log_text",
    "check_emergency_stop",
    "check_target_window",
    # Device seam
    "DeviceInput",
    "DryRunDevice",
    "PyDirectInputDevice",
    # Farming workflow
    "FarmObservationClaim",
    "FarmPhasePolicy",
    "FarmProfile",
    "FarmSafetyStop",
    "FarmState",
    "FarmWatchdog",
    "MINOTAUR_PHASE_POLICY",
    "MINOTAUR_PROFILE",
    "farm_action_values",
    "farm_state_values",
    # Input
    "_press_key",
    "_validate_key",
    "execute_game_action",
    # API
    "API_ERROR_MESSAGES",
    "DRAGON_NEST_TOOL",
    "MINOTAUR_TOOL",
    "SYSTEM_PROMPT",
    "_RETRYABLE_API_KINDS",
    "_call_openai",
    "_call_openrouter",
    "_classify_api_error",
    "extract_tool_requests",
    "get_openai_client",
    "get_openrouter_client",
    # Orchestration
    "_compact_messages",
    "_new_session_id",
    "run_dn_bot",
    # Replay
    "ReplayDeviceCall",
    "ReplayExpected",
    "ReplayMismatch",
    "ReplayReport",
    "ReplayResult",
    "ReplayStep",
    "ReplayTrace",
    "ReplayTraceError",
    "load_replay_trace",
    "replay_trace",
    # Logging
    "log",
]
