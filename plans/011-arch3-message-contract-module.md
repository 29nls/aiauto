# Plan 011 — Kandidat #3: module kontrak wire-shape pesan (implement)

- **Temuan:** Bentuk pesan OpenAI-compatible **tersebar** di beberapa modul: `_image_block` (capture.py), frame teks user (`orchestrator.py:96-99` dan `:198-203`), `assistant_message` + tool-calls dict (`orchestrator.py:128-142`), tool result (`orchestrator.py:186-194`), parser tool (`extract_tool_requests` di api.py). Tidak ada satu pemilik kontrak → perubahan wire-shape memaksa edit di banyak tempat + tes.
- **Status:** ✅ **Done** (2026-08-06) — **Verified (reconcile 2026-08-06)**: `dn_bot/messages.py` memiliki semua wire-shape; grep role dict mentah di orchestrator/capture = 0; suite penuh **72 passed** (ekspektasi "67" basi).

## Konteks

Prinsip: satu module (`dn_bot/messages.py` — atau `wire.py`/`contract.py`, pilih nama sesuai konvensi `dn_bot/`) yang mendefinisikan fungsi pembangun + tipe untuk semua bentuk pesan. Semua modul lain memanggil kontrak, tidak menyusun dict mentah.

## Keadaan saat ini (bukti)

- `dn_bot/capture.py` — `_image_block(encoded) -> {"type": "image_url", ...}` (baris ~29).
- `dn_bot/orchestrator.py:96-99` — `{"role": "user", "content": [{"type": "text", "text": "Current screenshot."}, _image_block(...)]}`.
- `dn_bot/orchestrator.py:128-142` — `assistant_message` + `tool_calls` list dari object SDK.
- `dn_bot/orchestrator.py:186-194` — `{"role": "tool", "tool_call_id": ..., "content": ...}`.
- `dn_bot/api.py` — `extract_tool_requests` (parse tool calls), `DRAGON_NEST_TOOL` (schema), `SYSTEM_PROMPT`.

## Langkah

1. Buat `dn_bot/messages.py` (bebas-cycle; hanya bergantung `config`/`typing`):
   ```python
   def user_text(content: str) -> dict                      # {"role": "user", "content": str}
   def frame_message(encoded: str, text: str) -> dict       # user msg: teks + image block
   def image_block(encoded: str) -> dict                    # pindah dari capture.py
   def assistant_message(text: str, tool_calls: list[dict]) -> dict
   def tool_result(tool_call_id: str, content: str) -> dict
   ```
   Sertakan docstring tipe (wire-shape) per fungsi.
2. `capture.py` — hapus `_image_block` (pindah ke messages; re-export/alias jika tes memakainya, lalu update tes).
3. `orchestrator.py` — bangun semua pesan via kontrak; hapus dict mentah.
4. `api.py` — gunakan kontrak untuk pesan tool result bila relevan; `extract_tool_requests` tetap (parser), tapi output `ToolRequest` (lihat plan 010).
5. Update `dn_bot/__init__.py` re-export sesuai API baru.
6. Perbarui tes yang mengimpor `_image_block` / menyusun shape.

## Verifikasi (machine-checkable)

```bash
python -m pytest -q                                       # 72 passed (verified 2026-08-06)
grep -rn '"role": "tool"\|"role": "user"' dn_bot/orchestrator.py dn_bot/capture.py | wc -l   # 0 di modul non-kontrak (semua lewat messages.py)
```

## Batas scope

- IN: `dn_bot/messages.py` (baru), `capture.py`, `orchestrator.py`, `api.py`, `__init__.py`, tes.
- OUT: perubahan wire-shape aktual yang dikirim ke model (kontrak = pemusatan, bukan perubahan konten).
- OUT: sistem tool schema (`DRAGON_NEST_TOOL`) — tetap di api.py kecuali dibutuhkan bersama.

## Rencana tes

- Tes shape kontrak: setiap fungsi membangun dict dengan kunci/tipe yang tepat (unit, tanpa mock).
- Tes kompatibilitas: pesan yang dibangun kontrak tetap memenuhi assert di `test_run_dn_bot_bounds_history_and_pairs_recent_tool_calls` (pasangan `tool_call_id`, urutan role).

## Catatan pemeliharaan

Kontrak = satu tempat edit saat format OpenAI-compatible berubah (mis. image block, tool call id fields). Jangan bypass kontrak dengan dict mentah di modul lain — guard via grep di verifikasi.
