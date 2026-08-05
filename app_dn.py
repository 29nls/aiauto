"""Vision-assisted input experiment for Dragon Nest on Windows.

This project uses a vision-capable model through OpenRouter plus a narrow,
allow-listed tool. It does not bypass anti-cheat, inject into the game, or
guarantee that a particular Dragon Nest client accepts synthetic input.
"""

from __future__ import annotations

import base64
import io
import json
import logging
import math
import os
import sys
import time
from dataclasses import dataclass
from typing import Any, Optional, Sequence

import mss
import pydirectinput
from dotenv import load_dotenv
from openai import OpenAI
from PIL import Image

load_dotenv()

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("DN-Bot")

# PyDirectInput's failsafe is an emergency mechanism, not an anti-cheat feature.
pydirectinput.FAILSAFE = True
pydirectinput.PAUSE = 0.03

TARGET_WIDTH = 1024
TARGET_HEIGHT = 768
MAX_STEPS_PER_SESSION = 10
MAX_CONTEXT_MESSAGES = 8
ACTION_COOLDOWN = 0.15
MOVE_DURATION = 0.3
START_DELAY_SECONDS = 5
OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"


MOVE_KEYS = {"w", "a", "s", "d", "q", "e"}
ACTION_KEYS = {
    "f",
    "space",
    "1",
    "2",
    "3",
    "4",
    "5",
    "6",
    "7",
    "8",
    "9",
    "0",
    "shift",
}

_capture_region: Optional[dict[str, int]] = None


@dataclass(frozen=True)
class CaptureGeometry:
    """Letterbox geometry needed to reverse-map model coordinates."""

    left: int
    top: int
    width: int
    height: int
    content_width: int
    content_height: int
    offset_x: int
    offset_y: int


_capture_geometry: Optional[CaptureGeometry] = None


class EmergencyStop(RuntimeError):
    """Raised when the user activates the mouse-corner emergency stop."""


class FocusLost(RuntimeError):
    """Raised when the target-window check fails."""


def check_emergency_stop() -> None:
    """Stop before another action if the cursor is in the failsafe corner."""
    try:
        x, y = pydirectinput.position()
    except Exception as error:
        raise EmergencyStop("Tidak dapat memeriksa posisi cursor; sesi dihentikan.") from error
    if 0 <= x <= 5 and 0 <= y <= 5:
        raise EmergencyStop("Cursor berada di pojok kiri atas.")


def check_target_window() -> None:
    """Require the configured Dragon Nest window to have focus on Windows."""
    if os.name != "nt":
        return
    expected = os.getenv("DN_WINDOW_TITLE", "").strip()
    if not expected:
        raise FocusLost(
            "DN_WINDOW_TITLE wajib diisi agar input tidak terkirim ke aplikasi lain."
        )

    import ctypes

    user32 = ctypes.windll.user32
    hwnd = user32.GetForegroundWindow()
    length = user32.GetWindowTextLengthW(hwnd)
    title_buffer = ctypes.create_unicode_buffer(length + 1)
    user32.GetWindowTextW(hwnd, title_buffer, length + 1)
    if expected.casefold() not in title_buffer.value.casefold():
        raise FocusLost(
            f"Jendela aktif bukan target DN_WINDOW_TITLE={expected!r} "
            f"(aktif: {title_buffer.value!r})."
        )


def _image_block(encoded: str) -> dict[str, Any]:
    """Build the OpenAI-compatible image content block used by OpenRouter."""
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
    }


def _capture_region_from_env(screen: mss.mss) -> dict[str, int]:
    """Use an explicit game-window rectangle, or a configured monitor."""
    names = (
        "DN_CAPTURE_LEFT",
        "DN_CAPTURE_TOP",
        "DN_CAPTURE_WIDTH",
        "DN_CAPTURE_HEIGHT",
    )
    configured = [os.getenv(name) for name in names]
    if any(value is not None for value in configured):
        if not all(value is not None for value in configured):
            raise ValueError(
                "DN_CAPTURE_LEFT/TOP/WIDTH/HEIGHT harus diisi semuanya."
            )
        region = {
            name.removeprefix("DN_CAPTURE_").lower(): int(value)
            for name, value in zip(names, configured)
        }
        if region["width"] < 2 or region["height"] < 2:
            raise ValueError("DN_CAPTURE_WIDTH/HEIGHT harus minimal 2.")
        return region

    monitor_index = int(os.getenv("DN_MONITOR", "1"))
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


def capture_screen_base64() -> str:
    """Capture the game region as a centered, letterboxed 1024x768 JPEG."""
    global _capture_region, _capture_geometry

    check_target_window()
    with mss.mss() as screen:
        _capture_region = _capture_region_from_env(screen)
        captured = screen.grab(_capture_region)

    image = Image.frombytes("RGB", captured.size, captured.bgra, "raw", "BGRX")
    if image.size != (_capture_region["width"], _capture_region["height"]):
        raise ValueError(
            "Ukuran screenshot aktual berbeda dari capture region yang dikonfigurasi."
        )
    _capture_geometry = _geometry_for_region(_capture_region)
    letterboxed = _letterbox(image, _capture_geometry)
    buffer = io.BytesIO()
    letterboxed.save(buffer, format="JPEG", quality=75, optimize=True)
    return base64.b64encode(buffer.getvalue()).decode("ascii")


def _physical_point(coordinate: Sequence[Any]) -> tuple[int, int]:
    """Map a model coordinate through letterbox geometry to the physical screen."""
    if (
        not isinstance(coordinate, (list, tuple))
        or len(coordinate) != 2
        or any(isinstance(value, bool) or not isinstance(value, int) for value in coordinate)
    ):
        raise ValueError("coordinate harus berupa dua integer.")

    x, y = coordinate
    if not (0 <= x < TARGET_WIDTH and 0 <= y < TARGET_HEIGHT):
        raise ValueError("coordinate berada di luar ukuran gambar 1024x768.")

    geometry = _capture_geometry
    if _capture_region is not None and (
        geometry is None
        or (geometry.left, geometry.top, geometry.width, geometry.height)
        != tuple(_capture_region[key] for key in ("left", "top", "width", "height"))
    ):
        geometry = _geometry_for_region(_capture_region)
    elif geometry is None:
        geometry = CaptureGeometry(
            left=0,
            top=0,
            width=TARGET_WIDTH,
            height=TARGET_HEIGHT,
            content_width=TARGET_WIDTH,
            content_height=TARGET_HEIGHT,
            offset_x=0,
            offset_y=0,
        )

    if not (
        geometry.offset_x <= x < geometry.offset_x + geometry.content_width
        and geometry.offset_y <= y < geometry.offset_y + geometry.content_height
    ):
        raise ValueError("coordinate berada di area padding letterbox.")

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
        raise ValueError("coordinate terlalu dekat dengan area emergency stop.")
    return physical_x, physical_y


def _validate_key(text: Optional[str], allowed: set[str]) -> str:
    if not isinstance(text, str) or text.lower() not in allowed:
        allowed_text = ", ".join(sorted(allowed))
        raise ValueError(f"Tombol tidak diizinkan. Pilihan: {allowed_text}")
    return text.lower()


def _safe_sleep(seconds: float) -> None:
    """Sleep in short intervals so emergency/focus checks remain responsive."""
    deadline = time.monotonic() + seconds
    while True:
        check_emergency_stop()
        check_target_window()
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            return
        time.sleep(min(0.05, remaining))


def _press_key(key: str, duration: float) -> None:
    """Always release a key, including when the action is interrupted."""
    pydirectinput.keyDown(key)
    try:
        _safe_sleep(duration)
    finally:
        pydirectinput.keyUp(key)


def execute_game_action(
    action: str,
    coordinate: Optional[Sequence[Any]] = None,
    text: Optional[str] = None,
    duration: float = MOVE_DURATION,
) -> None:
    """Execute one validated action from the model's custom tool."""
    check_emergency_stop()
    check_target_window()
    try:
        duration = float(duration)
    except (TypeError, ValueError) as error:
        raise ValueError("duration harus berupa angka antara 0.05 dan 2.0.") from error
    if not math.isfinite(duration):
        raise ValueError("duration harus berupa angka antara 0.05 dan 2.0.")
    duration = max(0.05, min(duration, 2.0))

    if action == "mouse_move":
        if coordinate is None:
            raise ValueError("mouse_move membutuhkan coordinate.")
        pydirectinput.moveTo(*_physical_point(coordinate))
    elif action in {"left_click", "right_click"}:
        if coordinate is None:
            raise ValueError(f"{action} membutuhkan coordinate.")
        pydirectinput.moveTo(*_physical_point(coordinate))
        if action == "left_click":
            pydirectinput.click()
        else:
            pydirectinput.rightClick()
    elif action == "press_move_key":
        _press_key(_validate_key(text, MOVE_KEYS), duration)
    elif action == "press_action_key":
        _press_key(_validate_key(text, ACTION_KEYS), min(duration, 1.0))
    elif action == "move_camera":
        if coordinate is None:
            raise ValueError("move_camera membutuhkan coordinate.")
        x, y = _physical_point(coordinate)
        center_x, center_y = _physical_point((TARGET_WIDTH // 2, TARGET_HEIGHT // 2))
        pydirectinput.moveRel(x - center_x, y - center_y)
    elif action == "wait":
        _safe_sleep(duration)
    else:
        raise ValueError(f"Aksi tidak diizinkan: {action}")

    _safe_sleep(ACTION_COOLDOWN)


DRAGON_NEST_TOOL = {
    "type": "function",
    "function": {
        "name": "dragon_nest_action",
        "description": (
            "Execute one cautious, allow-listed action in the focused Dragon Nest "
            "window. Coordinates refer to the 1024x768 screenshot. Click actions "
            "must include the intended coordinate. Use only after inspecting the "
            "latest screenshot."
        ),
        "parameters": {
            "type": "object",
            "properties": {
                "action": {
                    "type": "string",
                    "enum": [
                        "mouse_move",
                        "left_click",
                        "right_click",
                        "press_move_key",
                        "press_action_key",
                        "move_camera",
                        "wait",
                    ],
                },
                "coordinate": {
                    "type": "array",
                    "items": {"type": "integer"},
                    "minItems": 2,
                    "maxItems": 2,
                },
                "text": {"type": "string"},
                "duration": {"type": "number", "minimum": 0.05, "maximum": 2.0},
            },
            "required": ["action"],
            "additionalProperties": False,
        },
    },
}

SYSTEM_PROMPT = """Kamu adalah vision agent untuk eksperimen kontrol input Dragon Nest.

Keselamatan:
- Ini bukan alat anti-cheat dan tidak boleh digunakan untuk menghindari deteksi,
  eksploitasi, PvP, farming otomatis, atau melanggar Terms of Service.
- Gunakan hanya satu aksi per tool call, jangan mengulang aksi tanpa screenshot baru,
  dan berhenti jika layar tidak jelas, game kehilangan fokus, atau ada dialog risiko.
- Jangan pernah memilih coordinate [0, 0] atau area pojok kiri atas.
- Area padding hitam di luar gambar game bukan target yang valid; pilih coordinate di dalam content game.

Aturan aksi:
- `press_move_key` hanya untuk w/a/s/d/q/e.
- `press_action_key` hanya untuk f, space, 0-9, atau shift.
- `mouse_move` memakai coordinate absolut pada screenshot 1024x768.
- `move_camera` memakai coordinate sebagai arah relatif dari titik tengah screenshot.
- `wait` dipakai untuk loading atau animasi.
- Jangan membuat asumsi tentang NPC atau target yang tidak terlihat.
"""


def get_openrouter_client() -> OpenAI:
    """Create an OpenAI-compatible client pointed at OpenRouter."""
    api_key = os.getenv("OPENROUTER_API_KEY")
    if not api_key:
        raise RuntimeError(
            "OPENROUTER_API_KEY belum diatur. Copy .env.example menjadi .env "
            "dan isi API key secara lokal."
        )

    return OpenAI(base_url=OPENROUTER_BASE_URL, api_key=api_key)


def extract_tool_requests(message: Any) -> list[dict[str, Any]]:
    """Parse OpenRouter/OpenAI function calls into validated-loop inputs."""
    requests = []
    for call in getattr(message, "tool_calls", None) or []:
        if call.function.name != "dragon_nest_action":
            raise ValueError(f"Tool tidak diizinkan: {call.function.name}")
        try:
            tool_input = json.loads(call.function.arguments)
        except json.JSONDecodeError as error:
            raise ValueError("Argument tool bukan JSON yang valid.") from error
        if not isinstance(tool_input, dict):
            raise ValueError("Argument tool harus berupa object JSON.")
        requests.append({"id": call.id, "input": tool_input})
    return requests


def _compact_messages(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Bound history while preserving valid assistant/tool groups and latest frame."""
    if not messages:
        return messages

    instruction = messages[0]
    current_frame = messages[-1]
    history = messages[1:-1]
    turns: list[list[dict[str, Any]]] = []
    index = 0
    while index < len(history):
        message = history[index]
        if message.get("role") != "assistant" or not message.get("tool_calls"):
            index += 1
            continue

        end = index + 1
        while end < len(history) and history[end].get("role") == "tool":
            end += 1
        turns.append(history[index:end])
        index = end

    budget = MAX_CONTEXT_MESSAGES - 2
    selected: list[list[dict[str, Any]]] = []
    for turn in reversed(turns):
        if len(turn) > budget:
            # Do not fall back to older context when the newest complete turn
            # cannot fit; stale action history is less useful than no history.
            break
        selected.insert(0, turn)
        budget -= len(turn)

    compacted = [instruction]
    for turn in selected:
        compacted.extend(turn)
    compacted.append(current_frame)
    return compacted[-MAX_CONTEXT_MESSAGES:]


def run_dn_bot(instruction: str, max_steps: int = MAX_STEPS_PER_SESSION) -> None:
    """Run a bounded screenshot -> OpenRouter -> validated action loop."""
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValueError("Instruction harus berupa teks yang tidak kosong.")
    if (
        isinstance(max_steps, bool)
        or not isinstance(max_steps, int)
        or not 1 <= max_steps <= MAX_STEPS_PER_SESSION
    ):
        raise ValueError(
            f"max_steps harus berupa integer antara 1 dan {MAX_STEPS_PER_SESSION}."
        )

    model = os.getenv("OPENROUTER_MODEL", "").strip()
    if not model:
        raise RuntimeError(
            "OPENROUTER_MODEL belum diatur. Pilih model OpenRouter yang "
            "mendukung vision dan tool calling."
        )

    client = get_openrouter_client()
    messages: list[dict[str, Any]] = [
        {"role": "user", "content": instruction},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": "Current screenshot."},
                _image_block(capture_screen_base64()),
            ],
        },
    ]

    for step in range(1, max_steps + 1):
        check_emergency_stop()
        log.info("Langkah %s/%s", step, max_steps)
        messages = _compact_messages(messages)

        try:
            response = client.chat.completions.create(
                model=model,
                max_tokens=1024,
                messages=[{"role": "system", "content": SYSTEM_PROMPT}, *messages],
                tools=[DRAGON_NEST_TOOL],
                tool_choice="auto",
            )
        except Exception:
            log.exception("OpenRouter API gagal; sesi dihentikan tanpa aksi tambahan.")
            return

        try:
            message = response.choices[0].message
            tool_calls = message.tool_calls or []
            assistant_message = {
                "role": "assistant",
                "content": message.content or "",
            }
            if tool_calls:
                assistant_message["tool_calls"] = [
                    {
                        "id": call.id,
                        "type": "function",
                        "function": {
                            "name": call.function.name,
                            "arguments": call.function.arguments,
                        },
                    }
                    for call in tool_calls
                ]
            messages.append(assistant_message)
            tool_requests = extract_tool_requests(message)
        except (IndexError, AttributeError, TypeError, ValueError):
            log.exception("Respons model tidak valid; sesi dihentikan tanpa aksi tambahan.")
            return

        if not tool_requests:
            log.info("Model tidak meminta aksi lagi; sesi selesai.")
            return

        for index, request in enumerate(tool_requests):
            if index > 0:
                result = "Aksi ditolak: hanya satu aksi per screenshot yang diizinkan."
                log.warning(result)
            else:
                action = request["input"].get("action")
                try:
                    execute_game_action(
                        action=action,
                        coordinate=request["input"].get("coordinate"),
                        text=request["input"].get("text"),
                        duration=request["input"].get("duration", MOVE_DURATION),
                    )
                    result = f"Aksi {action!r} berhasil dijalankan."
                    log.info("Aksi: %s", action)
                except (EmergencyStop, FocusLost):
                    raise
                except Exception as error:
                    log.exception("Aksi gagal; sesi dihentikan tanpa aksi tambahan.")
                    raise RuntimeError(f"Aksi {action!r} gagal: {error}") from error

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": request["id"],
                    "content": result,
                }
            )

        # A fresh screenshot is a separate user message after the tool results.
        # This avoids asking the model to act on a stale frame.
        messages.append(
            {
                "role": "user",
                "content": [
                    {"type": "text", "text": "Current screenshot after the action."},
                    _image_block(capture_screen_base64()),
                ],
            }
        )
        messages = _compact_messages(messages)

    log.warning("Sesi berhenti karena mencapai batas langkah.")


if __name__ == "__main__":
    print(
        "\nDragon Nest AI Agent\n"
        "Gunakan hanya di lingkungan yang diizinkan oleh Terms of Service game.\n"
        "Emergency stop: gerakkan kursor ke pojok kiri atas atau tekan Ctrl+C.\n"
    )
    print(f"Fokus jendela game dalam {START_DELAY_SECONDS} detik...")
    for remaining in range(START_DELAY_SECONDS, 0, -1):
        print(f"{remaining}...", flush=True)
        time.sleep(1)

    try:
        run_dn_bot(
            "Amati screenshot. Jika ada NPC yang jelas terlihat dan aman untuk "
            "didekati, dekati secara perlahan lalu gunakan F untuk interaksi. "
            "Jika tujuan tidak jelas, jangan melakukan aksi.",
        )
    except (EmergencyStop, FocusLost) as error:
        log.warning("Sesi dihentikan: %s", error)
    except KeyboardInterrupt:
        log.info("Sesi dihentikan oleh pengguna (Ctrl+C).")
    except Exception:
        log.exception("Error fatal; tidak ada aksi tambahan yang dijalankan.")
