# Plan 004 — SBP-004: parsing env tanpa pesan error yang actionable (verify)

- **Temuan:** `int(os.getenv(...))` mentah melempar `ValueError` dengan traceback membingungkan saat nilai `.env` salah format. Low.
- **Status:** ✅ Fixed (via `_int_env` + `_validate_capture_env`). Plan ini = verifikasi.

## Konteks

Semua parsing integer env dipusatkan di `_int_env` yang fail-fast dengan pesan jelas per variabel; validasi env capture terpusat di `_validate_capture_env` (dipakai preflight dan `_capture_region_from_env`).

## Keadaan saat ini (bukti)

- `dn_bot/config.py` — `_int_env(name, default)`:
  ```python
  except (TypeError, ValueError):
      raise ValueError(f"{name} harus berupa bilangan bulat, bukan {raw!r}.") from None
  ```
- `_validate_capture_env`: pesan `DN_CAPTURE_LEFT/TOP/WIDTH/HEIGHT harus diisi semuanya.`, `DN_MONITOR harus berupa bilangan bulat >= 1.`
- Tes: `test_capture_region_rejects_non_integer_rect_value`, `test_capture_region_rejects_non_integer_monitor`, `test_capture_region_rejects_empty_rect_value`, `test_preflight_rejects_non_integer_capture_value`, `test_preflight_rejects_invalid_monitor`, dll.

## Langkah verifikasi

1. `grep -n "int(os.getenv" dn_bot/ --include="*.py"` → kosong (semua lewat `_int_env`).
2. Jalankan tes env: `python -m pytest -q tests/test_dn_bot.py -k "int_env or non_integer or empty_rect"` → semua pass.
3. Suite penuh `python -m pytest -q` → 60 passed.

## Verifikasi (machine-checkable)

`grep -rn "int(os.getenv" dn_bot/` tidak menghasilkan output; `-k` subset dan suite penuh lolos.

## Batas scope

- IN: `dn_bot/config.py` (`_int_env`, `_validate_capture_env`), `dn_bot/capture.py` (`_capture_region_from_env`).
- OUT: nilai env selain integer (mis. boolean) — belum ada kebutuhan.

## Rencana tes

Tes yang ada mencakup: nilai non-integer, kosong, monitor non-integer, monitor di luar rentang, rect parsial. Tidak perlu tes baru.

## Catatan pemeliharaan

Variabel env baru yang di-parse integer wajib lewat `_int_env` (konvensi AGENTS.md), bukan `int(os.getenv(...))` mentah.
