# Plan 016: Tambah tes integration loop run_dn_bot end-to-end

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: Repo ini direstrukturisasi dari `app_dn.py`
> menjadi package `dn_bot/` SETELAH stamp plan ini (audit improve pada commit
> `89b6c5a`). Bandingkan kutipan "Current state" dengan kode live di `dn_bot/`;
> jika tidak cocok → STOP.

## Status

- **Priority**: P2
- **Effort**: M
- **Risk**: LOW
- **Depends on**: `plans/015-improve3-device-port.md` (recorder device membuat tes integration lebih natural; boleh paralel jika 015 belum selesai — gunakan patch yang ada)
- **Category**: tests
- **Planned at**: commit `89b6c5a`, 2026-08-06 (audit improve; kode saat itu `app_dn.py`)
- **Issue**: omit

## Why this matters

Suite saat ini adalah unit tes dengan mock berat: fake client, frame
`SimpleNamespace`, `execute_game_action` di-mock penuh. Tidak ada tes yang
menjalankan loop `run_dn_bot` end-to-end dengan fake yang menggantikan capture,
API, DAN input sekaligus — jadi regresi pada **interaksi antar lapisan**
(capture → pesan → eksekusi → frame baru, urutan role, pasangan
`tool_call_id`) hanya tertangkap sebagian. Tes integration menutup celah ini
tanpa butuh game/OpenRouter nyata.

## Current state

- `dn_bot/orchestrator.py` — `run_dn_bot(instruction, max_steps)`:
  1. `frame = capture_screen_base64()` → pesan user (teks + `_image_block(frame.encoded)`)
  2. loop: `_compact_messages` → `_call_openrouter(client, model, messages)` → parse tool calls → `execute_game_action(..., frame=frame)` → `frame = capture_screen_base64()` → pesan user baru
- `tests/test_dn_bot.py` — `test_run_dn_bot_bounds_history_and_pairs_recent_tool_calls` (mock `capture_screen_base64` = `SimpleNamespace(encoded=...)`, mock `execute_game_action`), `test_run_dn_bot_stops_after_retries_without_running_actions`, `test_run_dn_bot_retried_call_runs_action_exactly_once`. Semua meng-mock `execute_game_action` — tidak ada tes yang mengeksekusi aksi nyata (lewat device/recorder).
- `tests/conftest.py` — fixture `capture_region` membangun `Frame` (factory).
- Konvensi: suite offline murni; pytest.ini `testpaths = tests`; 60 tes.

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| Tests     | `.venv/Scripts/python -m pytest -q` | 60 + N passed |
| New file  | `grep -rn "integration" tests/` | file baru terdaftar |

## Scope

**In scope**:
- `tests/test_integration.py` (baru) — tes end-to-end loop
- `tests/conftest.py` — fixture/fake tambahan jika perlu (mis. fake capture)

**Out of scope**:
- Mengubah kode produksi (`dn_bot/`) — kecuali ditemukan bug nyata saat tes ditulis (lapor, jangan langsung perbaiki tanpa instruksi).
- Jaringan nyata / game nyata — tetap offline.

## Git workflow

- Branch: `advisor/016-integration-tests`
- Message style: conventional commits
- Do NOT push/open PR kecuali diinstruksikan.

## Steps

### Step 1: Bangun fake capture (real `Frame`)

Fake `capture_screen_base64` mengembalikan `Frame` nyata (via fixture `capture_region` dari conftest) dengan `encoded` berbeda tiap panggilan (counter), sehingga tes bisa memverifikasi pesan "frame baru setelah aksi".

**Verify**: unit kecil di file baru — fake menghasilkan `Frame` dengan `encoded` unik.

### Step 2: Bangun fake client respons skrip

- `_fake_client(create)` yang mengembalikan `SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content=None, tool_calls=[...]))])` — skrip respons: `wait` → selesai (tanpa tool call).
- Pakai `patch.object(dn_bot.orchestrator, "get_openrouter_client", return_value=fake)` dan `patch.object(dn_bot.orchestrator, "capture_screen_base64", side_effect=fake_capture)`.

**Verify**: `.venv/Scripts/python -m pytest -q tests/test_integration.py -k "smoke"` → pass.

### Step 3: Tes integration inti

Tulis (di `tests/test_integration.py`):
1. **Alur penuh 2 langkah**: skrip `[wait, stop]` → assert: 2 request terkirim, `execute_game_action` dipanggil sekali dengan `frame` dari capture kedua (`frame.encoded` cocok), pesan user terakhir berisi frame baru, urutan role `user → assistant → tool → user` benar, pasangan `tool_call_id` benar.
2. **Hanya satu aksi per siklus**: skrip mengembalikan 2 tool call dalam satu respons → aksi kedua ditolak (pesan tool "hanya satu aksi per screenshot") dan `execute_game_action` dipanggil sekali.
3. **(Jika 015 selesai) aksi nyata via recorder**: ganti mock `execute_game_action` dengan device recorder → assert urutan input fisik untuk `move_camera`/`wait`. — **SELESAI 2026-08-06** setelah plan 012/015 (seam input device): tes ke-4 `test_integration_real_input_sequence_via_recorder` mengeksekusi `execute_game_action` ASLI dengan `RecordingDevice` (assert `[("moveTo", (512, 384)), ("moveTo", (800, 600))]` untuk `move_camera`, tanpa call untuk `wait`) + frame yang dipakai tiap aksi (`produced[0]` → `produced[1]`); guard/fokus/`_safe_sleep` di-patch agar urutan fokus pada primitif input. Suite: **72 passed** saat itu; kini **83** setelah polesan parametrize `classify_api_error`.

Model setelah: `test_run_dn_bot_bounds_history_and_pairs_recent_tool_calls` (pola assert pasangan `tool_call_id`).

**Verify**: `.venv/Scripts/python -m pytest -q` → 60 + 3 passed.

## Test plan

- File baru: `tests/test_integration.py` dengan 3 tes di atas.
- Pola: `test_run_dn_bot_bounds_history_and_pairs_recent_tool_calls` untuk struktur; `capture_region` fixture untuk membangun Frame.
- Verifikasi: `.venv/Scripts/python -m pytest -q` → semua pass, termasuk 3 tes baru.

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `tests/test_integration.py` ada dengan ≥ 3 tes
- [ ] `.venv/Scripts/python -m pytest -q` → 60 + N passed (N ≥ 3)
- [ ] `plans/README.md` status row 016 diupdate
- [ ] Tidak ada file `dn_bot/` yang berubah (kecuali bug nyata dilaporkan ke owner)

## STOP conditions

- Tes integration menemukan bug produksi → stop, tulis tes yang gagal, dan laporkan ke owner sebelum memperbaiki kode.
- Kode live tidak cocok dengan kutipan "Current state".
- Verifikasi gagal dua kali setelah upaya wajar.

## Maintenance notes

- Tes integration adalah jaring pengaman untuk refactor arsitektur (010/011/015): jika refactor berubah perilaku, tes ini menangkapnya.
- Jaga tetap offline; fake capture/client harus cukup realistis (Frame nyata, bukan SimpleNamespace) agar kontrak antar lapisan benar-benar diuji.
