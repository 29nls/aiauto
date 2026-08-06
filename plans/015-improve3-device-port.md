# Plan 015: Port lapisan input device ke seam nyata (protocol + adapter)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: Repo ini direstrukturisasi dari `app_dn.py`
> menjadi package `dn_bot/` SETELAH stamp plan ini (audit improve pada commit
> `89b6c5a` menemukan coupling langsung ke `pydirectinput` di `app_dn.py`).
> Bandingkan kutipan "Current state" dengan kode live di `dn_bot/`; jika tidak
> cocok → STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: MED
- **Depends on**: none (paralel dengan 016; 016 *lebih mudah* jika 015 selesai dulu)
- **Category**: tech-debt
- **Planned at**: commit `89b6c5a`, 2026-08-06 (audit improve; kode saat itu `app_dn.py`)
- **Issue**: omit

## Why this matters

`input_control.py` memanggil `pydirectinput` langsung (9 call site), dan tes
meng-`patch` namespace modul (`dn_bot.input_control.pydirectinput`). Ini
coupling keras ke library: urutan input tidak bisa direkam, penggantian device
atau dry-run butuh refactor, dan tes bergantung pada nama atribut library.
Sebuah seam (`DeviceInput` protocol + adapter produksi + recorder in-memory)
memisahkan logika aksi dari device, memberi mode dry-run gratis, dan membuat
tes meng-assert urutan input secara natural.

## Current state

- `dn_bot/input_control.py` — panggilan langsung: `pydirectinput.keyDown/keyUp/moveTo/click/rightClick` di `_press_key` (baris ~28) dan `execute_game_action` (baris ~64-83); 9 call site total.
- `dn_bot/safety.py` — `pydirectinput.position()` di `check_emergency_stop`; `pydirectinput.FAILSAFE = True; PAUSE = 0.03` di import.
- Tes: `patch.object(dn_bot.input_control, "pydirectinput", ...)` di `test_move_camera_anchors_at_center_before_absolute_endpoint`, `test_repeated_move_camera_calls_reanchor_before_each_endpoint`, `test_move_camera_rejects_padding_before_moving_cursor`; `patch.object(dn_bot.input_control.pydirectinput, "position", ...)` di `test_execute_game_action_rejects_invalid_duration`.
- Konvensi: Frame determinisme (plan 009) — state diteruskan eksplisit, tanpa global mutable (AGENTS.md "Frame (snapshot eksplisit — determinisme)").

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| Tests     | `.venv/Scripts/python -m pytest -q` | 117 passed (kini; 60 era app_dn.py) |
| Grep      | `grep -rn "pydirectinput" dn_bot/ --include="*.py"` | hanya di adapter |

## Scope

**In scope**:
- `dn_bot/device.py` (baru) — `DeviceInput` protocol + `PyDirectInputDevice`
- `dn_bot/input_control.py` — terima device (DI, default adapter produksi)
- `dn_bot/safety.py` — `check_emergency_stop` pakai `device.position()`
- `tests/` — `RecordingDevice` + refactor 5 tes aksi

**Out of scope**:
- Mengubah semantik aksi (perilaku input aktual tetap).
- Kandidat #2/#3 (plan 010/011) — orthogonal.
- Mode dry-run di produksi (recorder hanya untuk tes; produksi tetap adapter nyata).

## Git workflow

- Branch: `advisor/015-device-port`
- Message style: conventional commits
- Do NOT push/open PR kecuali diinstruksikan.

## Steps

### Step 1: Definisikan protocol + adapter produksi di `dn_bot/device.py`

```python
from typing import Protocol

class DeviceInput(Protocol):
    def position(self) -> tuple[int, int]: ...
    def moveTo(self, x: int, y: int) -> None: ...
    def keyDown(self, key: str) -> None: ...
    def keyUp(self, key: str) -> None: ...
    def click(self) -> None: ...
    def rightClick(self) -> None: ...

class PyDirectInputDevice:
    """Adapter produksi — membungkus pydirectinput 1:1."""
    def position(self): return pydirectinput.position()
    ...
```

**Verify**: `.venv/Scripts/python -m py_compile dn_bot/device.py` → exit 0.

### Step 2: Inject device ke `input_control.py`

- `execute_game_action(..., device: DeviceInput = PyDirectInputDevice())` — default produksi, tidak memecah call site lama; `_press_key(key, duration, device)`.
- Ganti semua `pydirectinput.X(...)` menjadi `device.X(...)`.
- PENTING: default arg `PyDirectInputDevice()` dievaluasi saat definisi fungsi (bind sekali) — konsisten dengan pola, tidak ada state mutable.

**Verify**: `grep -rn "pydirectinput" dn_bot/input_control.py` → 0 match (semua lewat `device`).

### Step 3: `check_emergency_stop` di `safety.py`

- Terima `device` (default `PyDirectInputDevice()`), pakai `device.position()`.

**Verify**: `grep -n "pydirectinput" dn_bot/safety.py` → hanya di import/FAILSAFE/PAUSE + di dalam `PyDirectInputDevice` (pindah ke device.py jika perlu).

### Step 4: `RecordingDevice` di tes + refactor 5 tes aksi

- `tests/device_recorder.py` (atau di dalam test file): mencatat `(method, args)` dan menyediakan `assert_calls(...)`.
- Ganti `patch.object(...pydirectinput...)` dengan konstruksi device recorder + assert urutan, mis. untuk move_camera: `[("moveTo", (512, 384)), ("moveTo", (800, 600))]`.

**Verify**: `.venv/Scripts/python -m pytest -q` → 117 passed (5 tes aksi memakai recorder; 60 era app_dn.py).

## Test plan

- Unit `RecordingDevice`: urutan + args akurat.
- Refactor: `test_move_camera_anchors_at_center_before_absolute_endpoint`, `test_repeated_move_camera_calls_reanchor_before_each_endpoint`, `test_move_camera_rejects_padding_before_moving_cursor`, `test_execute_game_action_rejects_invalid_duration` (position), `test_move_camera_rejects_missing_coordinate`.
- Pertahankan `test_scaled_physical_emergency_corner_is_rejected` (safety) dengan device stubbed.

## Done criteria

Machine-checkable. ALL must hold:

- [x] `grep -rn "pydirectinput" dn_bot/input_control.py` → 0 match
- [x] `grep -rn "pydirectinput" dn_bot/safety.py` → 0 match (FAILSAFE/PAUSE + semua call pindah ke `device.py`; position lewat device)
- [x] `.venv/Scripts/python -m pytest -q` → **71 passed** saat eksekusi (60 di plan adalah angka era `app_dn.py`; suite aktual 70 + 1 unit `RecordingDevice`); kini **83** setelah polesan parametrize `classify_api_error`; kini **117** setelah survey T1–T7
- [x] `plans/README.md` status row 015 diupdate
- [x] Tidak ada file di luar in-scope yang berubah (`device.py` baru; `input_control.py`, `safety.py`, `tests/`; + sinkronisasi dokumen AGENTS/CHANGELOG/README)

## STOP conditions

- `execute_game_action` signature berubah dengan cara yang memecah panggilan `run_dn_bot` (orchestrator) — pastikan default adapter menjaga kompatibilitas; jika tidak, stop dan laporkan.
- Kode live tidak cocok dengan kutipan "Current state".
- Verifikasi gagal dua kali setelah upaya wajar.

## Maintenance notes

- Seam ini membuka mode dry-run produksi dan penggantian library input tanpa menyentuh logika aksi.
- Jangan memanggil `pydirectinput` langsung di luar adapter.
- Rekonsiliasi: plan 012 (`arch4-input-device-seam.md`) di inventaris 12-temuan mencakup temuan yang sama — eksekusi salah satu, tandai yang lain REJECTED/superseded di README.
