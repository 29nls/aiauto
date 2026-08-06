# Plan 005 — SBP-005/F-05: sanitasi judul window sebelum di-log (verify)

- **Temuan:** Judul window foreground (nilai tak tepercaya) diinterpolasi mentah ke pesan `FocusLost` yang di-log → terminal log injection (ANSI escape, klaim palsu). Low.
- **Status:** ✅ Fixed — **Verified (reconcile 2026-08-06)**: sanitasi sebelum interpolasi (safety.py:67); uji C1 manual (8-bit CSI) bersih.

## Konteks

`_sanitize_log_text` menghapus karakter kontrol (C0 `\x00-\x1f`, C1 `\x80-\x9f`, DEL) dan sekuens ANSI CSI (`\x1b[...`) dari judul window **sebelum** perbandingan casefold dan interpolasi ke pesan. Layering dua regex menangani sekuens terpotong.

## Keadaan saat ini (bukti)

- `dn_bot/safety.py`:
  ```python
  _ANSI_CSI_RE = re.compile(r"\x1b\[[0-9;?]*[ -/]*[@-~]")
  _CONTROL_RE = re.compile(r"[\x00-\x1f\x7f\x80-\x9f]")
  ```
- `check_target_window`: `active_title = _sanitize_log_text(title_buffer.value)` sebelum `casefold()` dan `FocusLost(...)`.
- Tes: `test_sanitize_log_text_strips_ansi_and_control_chars` (unit, termasuk C1) + `test_check_target_window_sanitizes_hostile_window_title` (integrasi ctypes).

## Langkah verifikasi

1. `grep -n "_sanitize_log_text(title_buffer" dn_bot/safety.py` → sanitasi terjadi sebelum interpolasi.
2. Uji manual rentang C1 (8-bit CSI): `.venv/Scripts/python -c "import dn_bot; print(repr(dn_bot._sanitize_log_text('\x9b31mX')))"` → tidak ada `\x9b`/`\x1b`.
3. `python -m pytest -q` → 72 passed (termasuk 2 tes sanitasi; ekspektasi "60" basi).

## Verifikasi (machine-checkable)

Contoh di atas mencetak string tanpa karakter kontrol; suite 72 passed (verified 2026-08-06).

## Batas scope

- IN: `dn_bot/safety.py` (`_sanitize_log_text`, `check_target_window`).
- OUT: sanitasi nilai trusted (`.env` `expected`) — tidak perlu; hanya input tak tepercaya yang disanitasi.

## Rencana tes

Tes yang ada sudah cukup (unit + integrasi ctypes). Jika ada jalur log baru yang menginterpolasi nilai tak tepercaya, tambahkan sanitasi + tes mengikuti pola ini.

## Catatan pemeliharaan

Sanitasi-sebelum-casefold aman: mismatch → fail-closed; format-saja yang di-strip → cocok. Jangan memindahkan sanitasi ke setelah casefold.
