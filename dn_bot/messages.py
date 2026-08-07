"""Wire-shape message contract for the OpenAI-compatible API.

Satu-satunya pemilik bentuk pesan yang dikirim ke (dan diterima dari)
OpenAI: image block, pesan user berisi frame, pesan assistant dengan
tool-calls, tool result, dan tipe hasil polos dari adapter (``ModelReply``).
Module lain memanggil kontrak ini alih-alih menyusun dict mentah, sehingga
perubahan format pesan cukup diedit di satu tempat.

Module ini bebas-cycle: hanya bergantung pada stdlib (``json``, ``typing``).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class ToolRequest:
    """Satu tool call dari model, sudah tervalidasi dan terurai.

    ``input`` adalah hasil ``json.loads`` dari ``arguments`` SDK, sudah
    dipastikan berupa object JSON. ``extract_tool_requests`` menjamin nama
    tool selalu ``dragon_nest_action`` sebelum tipe ini dibuat.
    """

    id: str
    input: dict[str, Any]


@dataclass(frozen=True)
class ModelReply:
    """Hasil polos dari adapter OpenAI: teks + tool requests terurai.

    Tidak mengandung bentuk object SDK; ``api._call_openai`` mengembalikan
    tipe ini sehingga orchestrator tidak pernah menyentuh object SDK.
    """

    text: str
    tool_requests: list[ToolRequest]


def user_text(content: str) -> dict[str, Any]:
    """Wire-shape pesan user berisi teks saja."""
    return {"role": "user", "content": content}


def image_block(encoded: str) -> dict[str, Any]:
    """Wire-shape content block gambar (data URI JPEG base64)."""
    return {
        "type": "image_url",
        "image_url": {"url": f"data:image/jpeg;base64,{encoded}"},
    }


def frame_message(encoded: str, text: str) -> dict[str, Any]:
    """Wire-shape pesan user berisi teks keterangan + blok gambar screenshot."""
    return {
        "role": "user",
        "content": [
            {"type": "text", "text": text},
            image_block(encoded),
        ],
    }


def tool_calls_wire(tool_requests: list[ToolRequest]) -> list[dict[str, Any]]:
    """Wire-shape list ``tool_calls`` untuk pesan assistant di riwayat.

    ``arguments`` diserialisasi ulang dari ``input`` yang sudah terurai; nama
    tool selalu ``dragon_nest_action`` karena parser menolak tool lain.
    """
    return [
        {
            "id": request.id,
            "type": "function",
            "function": {
                "name": "dragon_nest_action",
                "arguments": json.dumps(request.input),
            },
        }
        for request in tool_requests
    ]


def assistant_message(
    text: str, tool_calls: list[dict[str, Any]]
) -> dict[str, Any]:
    """Wire-shape pesan assistant dengan tool_calls opsional."""
    message: dict[str, Any] = {"role": "assistant", "content": text}
    if tool_calls:
        message["tool_calls"] = tool_calls
    return message


def tool_result(tool_call_id: str, content: str) -> dict[str, Any]:
    """Wire-shape pesan tool result untuk satu tool_call."""
    return {"role": "tool", "tool_call_id": tool_call_id, "content": content}
