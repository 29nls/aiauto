"""Screen capture, letterbox geometry, and model-to-physical mapping."""

from __future__ import annotations

import base64
import io
import os
from dataclasses import dataclass
from typing import Any, Sequence

import mss
from PIL import Image

from .config import (
    CaptureGeometry,
    TARGET_HEIGHT,
    TARGET_WIDTH,
    _int_env,
    _validate_capture_env,
    log,
)
from .safety import check_target_window


@dataclass(frozen=True)
class Frame:
    """Immutable snapshot of one captured frame.

    Carries the encoded JPEG sent to the model plus the letterbox geometry
    needed to reverse-map model coordinates (geometry already embeds the
    physical region bounds). Passing a ``Frame`` explicitly instead of relying
    on module-level capture state keeps the session deterministic: an action
    always maps against the exact frame the model observed.
    """

    encoded: str
    geometry: CaptureGeometry


def _capture_region_from_env(screen: mss.mss) -> dict[str, int]:
    """Use an explicit game-window rectangle, or a configured monitor.

    Raises:
        ValueError: If the capture configuration is incomplete or invalid.
    """
    _validate_capture_env()
    names = (
        "DN_CAPTURE_LEFT",
        "DN_CAPTURE_TOP",
        "DN_CAPTURE_WIDTH",
        "DN_CAPTURE_HEIGHT",
    )
    configured = [os.getenv(name) for name in names]
    if any(value is not None for value in configured):
        region = {
            name.removeprefix("DN_CAPTURE_").lower(): _int_env(name)
            for name in names
        }
        return region

    monitor_index = _int_env("DN_MONITOR", "1")
    if monitor_index < 1 or monitor_index >= len(screen.monitors):
        raise ValueError(
            f"DN_MONITOR harus berada di antara 1 dan {len(screen.monitors) - 1}."
        )
    monitor = screen.monitors[monitor_index]
    return {key: int(monitor[key]) for key in ("left", "top", "width", "height")}


def _geometry_for_region(region: dict[str, int]) -> CaptureGeometry:
    """Calculate centered letterbox geometry for a physical capture region."""
    width, height = region["width"], region["height"]
    if width < 2 or height < 2:
        raise ValueError("capture region harus minimal 2x2.")
    scale = min(TARGET_WIDTH / width, TARGET_HEIGHT / height)
    content_width = max(1, round(width * scale))
    content_height = max(1, round(height * scale))
    return CaptureGeometry(
        left=region["left"],
        top=region["top"],
        width=width,
        height=height,
        content_width=content_width,
        content_height=content_height,
        offset_x=(TARGET_WIDTH - content_width) // 2,
        offset_y=(TARGET_HEIGHT - content_height) // 2,
    )


def _letterbox(image: Image.Image, geometry: CaptureGeometry) -> Image.Image:
    """Fit an image into the model frame without changing its aspect ratio."""
    resized = image.resize(
        (geometry.content_width, geometry.content_height), Image.Resampling.LANCZOS
    )
    result = Image.new("RGB", (TARGET_WIDTH, TARGET_HEIGHT), (0, 0, 0))
    result.paste(resized, (geometry.offset_x, geometry.offset_y))
    return result


def capture_screen_base64() -> Frame:
    """Capture the game region as a centered, letterboxed 1024x768 JPEG.

    Returns an immutable :class:`Frame` carrying the encoded JPEG plus the
    region and letterbox geometry it was produced from, so callers never rely
    on hidden module-level capture state.
    """
    check_target_window()
    with mss.mss() as screen:
        region = _capture_region_from_env(screen)
        log.info(
            "Capture region: %dx%d @ (%d, %d)",
            region["width"],
            region["height"],
            region["left"],
            region["top"],
        )
        captured = screen.grab(region)

    image = Image.frombytes("RGB", captured.size, captured.bgra, "raw", "BGRX")
    if image.size != (region["width"], region["height"]):
        raise ValueError(
            "Ukuran screenshot aktual berbeda dari capture region yang dikonfigurasi."
        )
    geometry = _geometry_for_region(region)
    letterboxed = _letterbox(image, geometry)
    buffer = io.BytesIO()
    letterboxed.save(buffer, format="JPEG", quality=75, optimize=True)
    return Frame(
        encoded=base64.b64encode(buffer.getvalue()).decode("ascii"),
        geometry=geometry,
    )


class InvalidCoordinateError(ValueError):
    """A model-supplied coordinate that cannot be safely mapped to the screen.

    Raised for malformed coordinates, coordinates outside the 1024x768 model
    frame, coordinates inside the letterbox padding, and coordinates that map
    onto the failsafe corner. The orchestrator treats it as a retryable model
    error: the action is never executed, the failure is reported back to the
    model, and the model is asked for a corrected coordinate.
    """


def _physical_point(coordinate: Sequence[Any], frame: Frame) -> tuple[int, int]:
    """Map a model coordinate through a frame's letterbox geometry to the screen.

    The mapping is a pure function of ``frame`` (an immutable snapshot), so the
    result never depends on hidden state captured at some other point in time.
    """
    if (
        not isinstance(coordinate, (list, tuple))
        or len(coordinate) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in coordinate)
    ):
        raise InvalidCoordinateError("coordinate harus berupa dua integer.")

    x, y = coordinate
    if not (0 <= x < TARGET_WIDTH and 0 <= y < TARGET_HEIGHT):
        raise InvalidCoordinateError("coordinate berada di luar ukuran gambar 1024x768.")

    geometry = frame.geometry
    if not (
        geometry.offset_x <= x < geometry.offset_x + geometry.content_width
        and geometry.offset_y <= y < geometry.offset_y + geometry.content_height
    ):
        raise InvalidCoordinateError("coordinate berada di area padding letterbox.")

    source_x = min(
        geometry.width - 1,
        max(0, int((x - geometry.offset_x + 0.5) * geometry.width / geometry.content_width)),
    )
    source_y = min(
        geometry.height - 1,
        max(0, int((y - geometry.offset_y + 0.5) * geometry.height / geometry.content_height)),
    )
    physical_x = geometry.left + source_x
    physical_y = geometry.top + source_y
    if 0 <= physical_x <= 5 and 0 <= physical_y <= 5:
        raise InvalidCoordinateError("coordinate terlalu dekat dengan area emergency stop.")
    return physical_x, physical_y
