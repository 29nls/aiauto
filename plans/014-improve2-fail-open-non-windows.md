# Plan 014: Tutup fail-open cek fokus di platform non-Windows

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: Repo ini direstrukturisasi dari `app_dn.py`
> menjadi package `dn_bot/` SETELAH stamp plan ini (audit improve pada commit
> `89b6c5a` menemukan guard fail-open di `app_dn.py`). Bandingkan kutipan
> "Current state" dengan kode live di `dn_bot/`; jika tidak cocok → STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `89b6c5a`, 2026-08-06 (audit improve; kode saat itu `app_dn.py`)
- **Issue**: omit

## Why this matters

Di platform non-Windows, `check_target_window` dulu `return` diam-diam —
guard keselamatan inti (input hanya ke jendela target) mati tanpa peringatan,
sementara sisa script tetap bisa mengirim input. Prinsip keamanannya
fail-closed: jika guard tidak bisa berfungsi, sesi harus ditolak, bukan
diteruskan tanpa cek. (README menyatakan proyek Windows-only.)

## Current state

- `dn_bot/config.py` — `preflight_configuration()`:
  ```python
  if os.name != "nt":
      raise RuntimeError("Script ini hanya mendukung Windows: ... Jalankan pada Windows 10/11.")
  ```
- `dn_bot/safety.py` — `check_target_window()`:
  ```python
  if os.name != "nt":
      raise FocusLost("Script ini hanya mendukung Windows: cek fokus jendela tidak dapat berjalan ... (fail-closed). ...")
  ```
  (dulu: `if os.name != "nt": return` — sekarang fail-closed dua lapis)
- `dn_bot/orchestrator.py` — `run_dn_bot` re-raise `(EmergencyStop, FocusLost)` eksplisit; `_press_key` di `input_control.py` menjamin `keyUp` via `finally` (pola kompensasi terverifikasi).
- Tes: `test_preflight_rejects_non_windows_platform`, `test_check_target_window_fails_closed_on_non_windows` di `tests/test_dn_bot.py`.
- Konvensi: hierarki exception — `EmergencyStop`/`FocusLost` subclass `RuntimeError` di `dn_bot/config.py`; lihat AGENTS.md "Hierarki exception".

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| Guard grep | `grep -n 'os.name != "nt"' dn_bot/config.py dn_bot/safety.py` | 2 baris, keduanya `raise` |
| Tests     | `.venv/Scripts/python -m pytest -q` | 83 passed (ekspektasi "60" basi) |

## Scope

**In scope**:
- Verifikasi `dn_bot/config.py`, `dn_bot/safety.py`, `dn_bot/orchestrator.py`
- `tests/test_dn_bot.py` (tambah tes propagasi hanya jika ada celah yang ditemukan)

**Out of scope**:
- Perilaku Windows (cek fokus ctypes) — di luar temuan ini.
- Menghapus pesan duplikat preflight vs `check_target_window` — itu defense-in-depth sengaja (AGENTS.md).

## Git workflow

- Branch: `advisor/014-fail-closed-non-windows`
- Message style: conventional commits
- Do NOT push/open PR kecuali diinstruksikan.

## Steps

### Step 1: Verifikasi kedua guard fail-closed

- `grep -n 'os.name != "nt"' dn_bot/config.py dn_bot/safety.py` → 2 baris, masing-masing diikuti `raise` (bukan `return`).
- Baca propagasi di `dn_bot/orchestrator.py`: cari `except (EmergencyStop, FocusLost): raise` — `FocusLost` tidak boleh tertelan `except Exception` mana pun.
- `grep -n "except" dn_bot/api.py` → `_call_openrouter` tidak memanggil guard di blok retry.

**Verify**: grep menghasilkan baris yang sesuai; suite `83 passed` (ekspektasi "60" basi).

### Step 2: Konfirmasi tes penjaga

- `.venv/Scripts/python -m pytest -q tests/test_dn_bot.py -k "non_windows"` → 2 passed.

**Verify**: 2 passed.

## Test plan

- Tes yang ada cukup (2 tes non-Windows + propagasi via suite). Jika hierarki exception berubah di masa depan, tambahkan tes propagasi `run_dn_bot` di posix (pola: patch `dn_bot.config.os.name` dan `dn_bot.safety.os.name`, expect `FocusLost`/`RuntimeError`).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `grep -n 'os.name != "nt"'` → 2 baris dengan `raise`
- [x] `.venv/Scripts/python -m pytest -q` → 83 passed (verified via reconcile 2026-08-06)
- [ ] `plans/README.md` status row 014 diupdate
- [ ] Tidak ada file di luar in-scope yang berubah

## STOP conditions

- Guard di kode live ternyata masih `return` (drift / regresi) — stop dan laporkan, jangan perbaiki langsung tanpa instruksi.
- Verifikasi gagal dua kali setelah upaya wajar.

## Maintenance notes

- Pesan error duplikat antara preflight dan `check_target_window` adalah lapisan defense-in-depth; jangan "rapikan" tanpa mengganti kedua tes.
- Pemanggilan programatik `run_dn_bot` tanpa preflight tetap tertolak oleh lapisan kedua (`check_target_window`).
