# Plan 009 — Kandidat #1: Frame module (verify)

- **Temuan:** Global capture state tersembunyi (`_capture_region`/`_capture_geometry` module globals di `capture.py`) dibaca diam-diam oleh `_physical_point` → melanggar determinisme (aksinya tergantung state yang bisa basi). Prinsip: determinism ala Temporal workflows — tanpa hidden mutable state.
- **Status:** ✅ Done (implementasi selesai sesi ini) — **Verified (reconcile 2026-08-06)**: 0 global capture state, 0 `global`, 4 call site `_physical_point(..., frame)`.

## Konteks

`capture_screen_base64()` kini mengembalikan `Frame` immutable (dataclass frozen: `encoded` + `geometry`); `_physical_point(coordinate, frame)` dan `execute_game_action(..., *, frame)` menerima frame **eksplisit** (keyword-only wajib). Orchestrator memegang satu frame per siklus.

## Keadaan saat ini (bukti)

- `dn_bot/capture.py` — `@dataclass(frozen=True) class Frame: encoded: str; geometry: CaptureGeometry`; tidak ada module globals.
- `dn_bot/input_control.py` — `execute_game_action(..., *, frame: Frame)`; 4 call site `_physical_point(..., frame)`.
- `dn_bot/orchestrator.py` — `frame = capture_screen_base64()` awal + setelah tiap aksi; `_image_block(frame.encoded)`.
- `tests/conftest.py` — fixture `capture_region` = factory murni membangun `Frame` (tanpa patch).

## Langkah verifikasi

1. `grep -rn "_capture_region\|_capture_geometry" dn_bot/ --include="*.py"` → hanya nama fungsi `_capture_region_from_env` (bukan global).
2. `grep -rn "_physical_point(" dn_bot/ --include="*.py"` → semua call site meneruskan `frame`.
3. `grep -rn "global " dn_bot/ --include="*.py"` → tidak ada pernyataan `global` di modul package.
4. `python -m pytest -q` → 72 passed (ekspektasi "60" basi).

## Verifikasi (machine-checkable)

Empat grep di atas bersih/konsisten; suite 72 passed (verified 2026-08-06).

## Batas scope

- IN: verifikasi `dn_bot/` + suite.
- OUT: kandidat #2/#3/#4 (plan 010/011/012) — terpisah.

## Rencana tes

Tes yang ada memetakan frame eksplisit (15 situs). Jika refactor global state dicoba lagi ke depan, guard: tes harus tetap memakai fixture `capture_region` (factory), bukan patch modul.

## Catatan pemeliharaan

Frame adalah satu-satunya sumber kebenaran mapping. Jangan menghidupkan kembali global mutable; state bersama apa pun harus diteruskan eksplisit (AGENTS.md "Frame (snapshot eksplisit — determinisme)").
