# Plan 010 — Kandidat #2: adapter OpenRouter hasil model polos (implement)

- **Temuan:** `_call_openrouter` mengembalikan **object SDK mentah** (`openai` response); `run_dn_bot` lalu mengakses `response.choices[0].message` + `extract_tool_requests` — boundary api.py bocor ke orchestrator, tes harus meniru bentuk SDK (`_FakeAPIError`, `_fake_client`), dan wire-shape respon tidak dimiliki oleh satu tempat.
- **Status:** ✅ **Done** (2026-08-06) — **Verified (reconcile 2026-08-06)**: 0 `response.choices`/`.tool_calls` di orchestrator; `_call_openrouter` → `ModelReply`, parse di luar retry; suite penuh **72 passed** (ekspektasi "67" basi — suite tumbuh via seam + integration).

## Konteks

Goal: `_call_openrouter` mengembalikan data polos (tool requests + teks), bukan object SDK — sehingga orchestrator tidak tahu bentuk SDK, tes tidak perlu fake SDK yang rapuh, dan kontrak dipusatkan. **Kerjakan setelah plan 011 (kontrak wire-shape)** agar tipe hasil berasal dari module kontrak.

## Keadaan saat ini (bukti)

- `dn_bot/api.py` — `_call_openrouter(...) -> Any` (return `response` SDK mentah); `extract_tool_requests(message)` mengurai `message.tool_calls` dari object SDK.
- `dn_bot/orchestrator.py:124-144` — membangun `assistant_message` dengan membaca `response.choices[0].message.tool_calls` / `.content` langsung (object SDK).
- Tes: `_fake_client`, `_FakeAPIError`, `_FakeTimeoutError` di `tests/test_dn_bot.py` meniru bentuk SDK.

## Langkah

1. (Setelah 011) Definisikan tipe hasil polos di module kontrak, mis.:
   ```python
   @dataclass(frozen=True)
   class ModelReply:
       text: str
       tool_requests: list[ToolRequest]   # id + input (dict terurai)
   ```
2. `_call_openrouter` mengembalikan `ModelReply`:
   - Parse `response.choices[0].message` di dalam api.py (bukan orchestrator).
   - `extract_tool_requests` tetap dipakai sebagai parser internal (validasi allowlist tool + JSON).
3. `run_dn_bot` mengonsumsi `ModelReply`: `reply.tool_requests`, `reply.text` — hapus pembacaan langsung `response.choices[0].message` dan pembangunan `assistant_message` dari SDK di orchestrator (pindahkan ke kontrak/api).
4. Perbarui tes: `_fake_client` tetap bisa meniru SDK (adapter masih menerima object SDK), tetapi **orchestrator-level tes** tidak lagi meniru bentuk respon — mock `_call_openrouter` mengembalikan `ModelReply` polos.

## Verifikasi (machine-checkable)

```bash
python -m pytest -q                                                       # 72 passed (verified 2026-08-06)
grep -rn "response.choices\|\.choices\[0\]" dn_bot/orchestrator.py        # kosong
```

## Batas scope

- IN: `dn_bot/api.py`, `dn_bot/orchestrator.py`, module kontrak (011), tes terkait.
- OUT: jaringan/retry (tidak berubah), sistem tool schema.
- OUT: kandidat #4 (seam input) — orthogonal.

## Rencana tes

- Adaptasi `test_call_openrouter_*` → assert hasil `ModelReply` (bukan object).
- Adaptasi `test_run_dn_bot_bounds_history...` → mock `_call_openrouter`/adapter mengembalikan `ModelReply`; hapus fake `choices/message/tool_calls` di level orchestrator.
- Tambah tes unit parser `ModelReply` (tool JSON valid, tool tak dikenal, arguments non-JSON).

## Catatan pemeliharaan

Boundary yang benar: api.py satu-satunya tempat menyentuh object SDK. Jika `openai` SDK berubah bentuk (mis. versi baru), hanya api.py + tes adapter yang berubah.
