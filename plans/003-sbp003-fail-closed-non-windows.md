# Plan 003 — SBP-003/F-02: cek fokus fail-closed di non-Windows (verify)

- **Temuan:** `check_target_window` fail-open di non-Windows (`if os.name != "nt": return` diam-diam) sementara sisa script tetap berjalan → guard keselamatan mati tanpa peringatan. Medium.
- **Status:** ✅ Fixed (fail-closed penuh dua lapis). Plan ini = verifikasi.

## Konteks

Dua lapis penolakan: (1) `preflight_configuration` menolak platform non-Windows sebelum countdown; (2) `check_target_window` sendiri kini `raise FocusLost` di non-Windows sehingga pemanggilan programatik tanpa preflight pun ditolak.

## Keadaan saat ini (bukti)

- `dn_bot/safety.py` — `check_target_window`: `if os.name != "nt": raise FocusLost(...)` (bukan `return`).
- `dn_bot/config.py` — `preflight_configuration`: `if os.name != "nt": raise RuntimeError(...)`.
- Propagasi aman: `FocusLost` di-re-raise eksplisit di `run_dn_bot`, tidak tertelan `except Exception` mana pun; `_press_key` tetap menjamin `keyUp` via `finally`.
- Tes: `test_preflight_rejects_non_windows_platform`, `test_check_target_window_fails_closed_on_non_windows`.

## Langkah verifikasi

1. `grep -n "os.name" dn_bot/safety.py dn_bot/config.py` — kedua guard `!= "nt"` melempar exception, bukan return.
2. Pastikan tidak ada `except Exception` di jalur `check_target_window` → `__main__` yang bisa menelan `FocusLost`:
   ```bash
   grep -n "except" dn_bot/orchestrator.py dn_bot/api.py
   ```
   `(EmergencyStop, FocusLost): raise` harus ada di orchestrator; `_call_openrouter` tidak memanggil guard di blok retry.
3. `python -m pytest -q` → 60 passed (termasuk 2 tes non-Windows).

## Verifikasi (machine-checkable)

`grep "os.name != \"nt\""` muncul 2x (config preflight + safety check) dengan `raise` setelahnya; suite 60 passed.

## Batas scope

- IN: `dn_bot/config.py`, `dn_bot/safety.py`, `dn_bot/orchestrator.py`.
- OUT: perilaku Windows (ctypes focus check) — di luar temuan ini.

## Rencana tes

Tes yang ada sudah menjaganya (2 tes non-Windows + propagasi). Jika ada perubahan hierarki exception ke depan, tambahkan tes propagasi `run_dn_bot` di posix.

## Catatan pemeliharaan

Pesan duplikat di preflight vs `check_target_window` = defense-in-depth sengaja (dokumentasi pola di AGENTS.md). Jangan "rapikan" menjadi satu pesan tanpa mengganti kedua tes.
