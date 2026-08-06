# Plan 012 — Kandidat #4: seam input device nyata (implement)

- **Temuan:** `input_control.py` memanggil `pydirectinput` **langsung** (9 call site); tes meng-`patch` namespace modul (`dn_bot.input_control.pydirectinput`) — coupling keras ke library, tes tidak bisa merekam urutan input secara natural, dan penggantian device (atau dry-run) butuh refactor.
- **Status:** ✅ Done (2026-08-06 — dieksekusi bersama plan 015, temuan yang sama; lihat catatan rekonsiliasi di plans/README.md). Plan ini = protocol/adapter: pydirectinput di produksi, recorder in-memory di tes.

## Konteks

Sebuah seam nyata: `DeviceInput` protocol dengan metode primitif; produksi memakai `PyDirectInputDevice`; tes memakai `RecordingDevice` (in-memory recorder) sehingga urutan input bisa di-assert langsung tanpa patch namespace.

## Keadaan saat ini (bukti)

- `dn_bot/input_control.py` — `pydirectinput.keyDown/keyUp/moveTo/click/rightClick` dipanggil langsung di `_press_key`, `execute_game_action`.
- `dn_bot/safety.py` — `pydirectinput.position()` di `check_emergency_stop`; `pydirectinput.FAILSAFE/PAUSE` di import.
- Tes — `patch.object(dn_bot.input_control, "pydirectinput", ...)` di `test_move_camera_*` dan `patch.object(dn_bot.input_control.pydirectinput, "position", ...)` di `test_execute_game_action_rejects_invalid_duration`.

## Langkah

1. Definisikan protocol (di `dn_bot/input_control.py` atau module baru `dn_bot/device.py`):
   ```python
   class DeviceInput(Protocol):
       def position(self) -> tuple[int, int]: ...
       def moveTo(self, x: int, y: int) -> None: ...
       def keyDown(self, key: str) -> None: ...
       def keyUp(self, key: str) -> None: ...
       def click(self) -> None: ...
       def rightClick(self) -> None: ...
   ```
2. Adapter produksi `PyDirectInputDevice` membungkus pydirectinput (1:1). `input_control.py` dan `safety.py` menerima device (dependency injection; default = adapter produksi) — jangan global mutable; teruskan eksplisit sejalan prinsip Frame (plan 009).
3. `RecordingDevice` (di `tests/`): menyimpan daftar `(method, args)`; `assert_calls` helper untuk tes.
4. Tes di-refactor: ganti `patch.object(...pydirectinput...)` dengan `RecordingDevice` + assert urutan `[(("moveTo", (512, 384)), ("moveTo", (800, 600)))]` — menghapus ketergantungan pada nama atribut pydirectinput.
5. `check_emergency_stop` memakai device.position() (bukan pydirectinput langsung) — tes emergency tetap bisa menyuntik posisi.

## Verifikasi (machine-checkable)

```bash
python -m pytest -q                                            # 60 passed (tes aksi pakai recorder)
grep -rn "pydirectinput" dn_bot/input_control.py               # hanya di adapter PyDirectInputDevice (0-1 call site)
```

## Batas scope

- IN: `dn_bot/input_control.py`, `dn_bot/safety.py` (position), `dn_bot/device.py` (baru), `tests/`.
- OUT: mengubah perilaku input aktual (semantik aksi tetap).
- OUT: kandidat #2/#3 (plan 010/011) — orthogonal, boleh dikerjakan paralel.

## Rencana tes

- Unit `RecordingDevice` (order + args akurat).
- Refactor 5 tes aksi: `test_move_camera_anchors_at_center_before_absolute_endpoint`, `test_repeated_move_camera_calls_reanchor_before_each_endpoint`, `test_move_camera_rejects_padding_before_moving_cursor`, `test_execute_game_action_rejects_invalid_duration` (position), `test_move_camera_rejects_missing_coordinate` — assert recorder, bukan mock.
- Pertahankan `test_scaled_physical_emergency_corner_is_rejected` (safety) dengan device stubbed.

## Catatan pemeliharaan

Dengan seam ini, dry-run (recorder) bisa dipakai di produksi untuk mode simulasi di masa depan; penggantian library input (mis. ke library lain) = implementasi protocol baru, tanpa menyentuh logika aksi. Jangan kembali memanggil pydirectinput langsung di luar adapter.
