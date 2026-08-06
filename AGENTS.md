# AGENTS.md — Konvensi proyek untuk agen coding

Panduan bagi agen AI yang mengerjakan repo ini. Seluruh pola di bawah **terverifikasi dari kode aktual** (`dn_bot/`, `tests/`) pada 2026-08-06.

## Ringkasan proyek

Eksperimen vision input untuk Dragon Nest: screenshot region game → model vision OpenRouter (tool calling) → aksi fisik terbatas via `pydirectinput`. **Windows-only** (cek fokus jendela + input fisik bergantung API Windows). Otomasi game online — hanya untuk lingkungan/akun yang diizinkan publisher.

## Arsitektur & struktur

- Package `dn_bot/` (bukan script tunggal); entrypoint `python -m dn_bot` (`dn_bot/__main__.py`).
- DAG import **bebas-cycle**: `config` (tanpa dependensi internal) dan `messages` (hanya stdlib `json`/`typing`) ← semua; `safety` ← `config`; `capture` ← (config, safety); `api` ← (config, messages); `input_control` ← (safety, capture); `orchestrator` ← semua (top-level loop). Setiap modul memakai `from __future__ import annotations`.
- `dn_bot/__init__.py` re-export API publik; `dn_bot.capture.*` adalah satu-satunya tempat patch global capture (lihat "Global state capture").
- Tes di `tests/` (pytest), konfigurasi di `pytest.ini` (`testpaths = tests`, `pythonpath = .`) → jalankan `python -m pytest` dari root proyek.
- Konstanta module-level di `config.py` (TARGET 1024×768, MAX_STEPS 10, MAX_CONTEXT_MESSAGES 8, dll). Jangan hardcode di modul lain.

## Konvensi kode

- **Bahasa**: identifier, nama fungsi, dan komentar teknis dalam **Inggris**; pesan error, pesan log, dan docstring deskriptif dalam **Bahasa Indonesia** (konsisten dengan README/SECURITY.md).
- **Type hints** di semua fungsi publik; docstring ringkas dengan bagian `Raises:` saat fungsi bisa melempar.
- **Hierarki exception** (terverifikasi):
  - `ValueError` untuk input tak valid (pesan actionable, Bahasa Indonesia).
  - `RuntimeError` untuk error konfigurasi/platform. `EmergencyStop` dan `FocusLost` adalah subclass `RuntimeError` yang didefinisikan di `config.py`.
  - Exception domain (`EmergencyStop`/`FocusLost`) **harus bisa menembus semua lapisan**: jangan pernah menempatkan pemanggil yang bisa melemparnya di dalam `except Exception` lebar yang menelannya — re-raise eksplisit `(EmergencyStop, FocusLost)` di lapisan yang menangkapnya (`run_dn_bot`), dan gunakan `finally` (bukan `except`) untuk kompensasi (lihat pola `_press_key`). Pola anti (OVR-01) pernah terjadi: helper domain-raising di dalam blok retry `except Exception` — jangan ulangi.
  - `_call_openrouter` menangkap `Exception` **hanya** di sekitar panggilan request, mengklasifikasikan, lalu melempar `RuntimeError` (konversi, bukan penelan).
  - **Wrapper aksi (`orchestrator.py:170`, `raise RuntimeError(...) from error`) sengaja mempertahankan chain** — bukan inkonsistensi F-06. `error` di sini hanya pesan validasi pendek (`ValueError` dari `execute_game_action`) atau error runtime `pydirectinput`, tidak pernah pesan SDK yang verbose seperti di `_call_openrouter`; `from None` (untuk log hygiene F-06) karena itu tidak diperlukan di sini, dan chain justru berguna sebagai konteks debugging. Jangan ubah menjadi `from None` tanpa alasan baru.

## Pola keselamatan (terverifikasi)

- **`check_emergency_stop()`** — failsafe pojok kiri atas (0–5 px); dipanggil sebelum tiap aksi dan setiap tick `_safe_sleep`. Jangan pernah menonaktifkan `pydirectinput.FAILSAFE`.
- **`check_target_window()`** — **fail-closed di non-Windows**: `raise FocusLost` (bukan return diam-diam), termasuk untuk pemanggilan programatik tanpa preflight. Perbandingan pakai `casefold`; judul window di-`_sanitize_log_text` **sebelum** interpolasi ke pesan yang di-log.
- **`_safe_sleep(seconds)`** — tidur dalam interval ≤50 ms sambil re-check `check_emergency_stop` + `check_target_window` tiap tick agar sesi responsif terhadap interupsi.
- **Pola kompensasi `try/finally` `_press_key`** (WAJIB dipertahankan — `input_control.py`):

  ```python
  def _press_key(key: str, duration: float) -> None:
      """Always release a key, including when the action is interrupted."""
      pydirectinput.keyDown(key)
      try:
          _safe_sleep(duration)
      finally:
          pydirectinput.keyUp(key)
  ```

  - `keyUp` **dijamin** berjalan meski `_safe_sleep` melempar (`EmergencyStop`/`FocusLost` saat sleep) — key fisik tidak pernah tertahan.
  - Gunakan `finally`, **bukan** `except`: menangkap exception kontrol di sini adalah bug (menelan sinyal stop). `finally` murni kompensasi, tidak mengubah alur exception.
  - Jika pola ini diubah, semua tes aksi tombol + propagasi `EmergencyStop`/`FocusLost` harus tetap lolos.
- **`_sanitize_log_text`** — menghapus karakter kontrol (C0 `\x00-\x1f`, C1 `\x80-\x9f`, DEL) dan sekuens ANSI CSI (`\x1b[...`) dari **nilai tak tepercaya** (judul window) sebelum masuk pesan log → cegah terminal log injection.

## Validasi input (semua input model = tak tepercaya)

- Aksi di-allowlist keras di `execute_game_action` + skema tool (`additionalProperties: False`); `extract_tool_requests` menolak tool tak dikenal (`Tool tidak diizinkan`).
- Tombol: `_validate_key(text, allowed)` terhadap `MOVE_KEYS` (w/a/s/d/q/e) atau `ACTION_KEYS` (f, space, 0–9, shift), di-lowercase.
- Durasi: `float()` → `isfinite()` → clamp [0.05, 2.0].
- Koordinat: dua integer (bukan bool), dalam 1024×768, **bukan** area padding letterbox, **bukan** pojok kiri atas (emergency corner).
- `move_camera`: endpoint absolut; cursor di-anchor ke titik tengah screenshot **setiap** aksi (invariant anti-drift) — jangan ubah tanpa mengganti tes terkait.

## Kontrak pesan (`messages.py`)

- Satu-satunya pemilik **wire-shape** pesan OpenAI-compatible: `user_text`, `image_block`, `frame_message` (teks + gambar), `assistant_message` (+ `tool_calls`), `tool_result`, dan `tool_calls_wire` (rebuild tool_calls dari `ToolRequest`). Tipe polos: `ToolRequest(id, input)` dan `ModelReply(text, tool_requests)`.
- **Jangan bypass kontrak** dengan dict pesan mentah (`{"role": ...}`) di modul lain — guard via grep. `api.py` adalah satu-satunya modul yang menyentuh object SDK; `_call_openrouter` mengembalikan `ModelReply` polos dan mem-parse respons **di luar** loop retry (error isi respons tidak boleh di-retry maupun diklasifikasi sebagai error API).

## Orkestrasi (`orchestrator.py`)

- `run_dn_bot`: loop terbatas (default `max_steps=10`), **satu aksi fisik per siklus** observasi, screenshot baru sebagai pesan user setelah tiap aksi — jangan bertindak pada frame basi.
- `_compact_messages`: batasi ke `MAX_CONTEXT_MESSAGES`, pertahankan instruction awal + frame terbaru + grup assistant/tool **lengkap** (pasangan `tool_call_id`); jika turn terbaru tidak muat, berhenti (tidak fallback ke konteks yang lebih lama).
- Retry `_call_openrouter`: maks 3 attempt (2 retry), **hanya** kind transien (`rate_limit`/`server`/`network`), backoff eksponensial (base 1.5 s). Retry membungkus request, **tidak pernah** eksekusi aksi → aksi tidak pernah diulang. Error konfigurasi (auth/not_found/invalid_request) gagal cepat.
- Observability tanpa secret: session ID (`%Y%m%d-%H%M%S` + uuid hex 6), durasi per langkah, dimensi region, latensi request. API key/token/konten percakapan tidak pernah di-log.

## Frame (snapshot eksplisit — determinisme)

- **Tidak ada global capture state.** `capture_screen_base64()` mengembalikan `Frame` immutable (dataclass frozen: `encoded` JPEG + `geometry` letterbox — geometry meng-embed batas region fisik), semua dibangun bersama di satu titik.
- `_physical_point(coordinate, frame)` dan `execute_game_action(..., *, frame)` menerima frame **eksplisit** — pemetaan koordinat adalah fungsi murni dari frame, tidak pernah bergantung pada state tersembunyi (prinsip determinisme ala Temporal workflows).
- Orchestrator memegang satu `frame` per siklus: capture awal → diteruskan ke aksi → capture ulang setelah aksi. Aksi selalu dimetakan terhadap frame yang persis model amati.
- Fixture `capture_region` di `tests/conftest.py` adalah **factory murni** (membangun `Frame` dari region; tidak ada yang di-patch lagi).
- Jangan menghidupkan kembali global mutable untuk capture — state bersama apa pun harus diteruskan eksplisit.

## Konvensi tes

- Suite offline murni: tanpa game, tanpa mouse fisik, tanpa OpenRouter. `_FakeAPIError`/`_FakeTimeoutError`/`_fake_client` menyimulasikan SDK.
- **Aturan patch**: patch pada **namespace modul si pemanggil** tempat nama di-lookup saat runtime (mis. `dn_bot.input_control.check_target_window`, `dn_bot.input_control.pydirectinput`, `dn_bot.api.time.sleep`), bukan modul definisi.
- Loop `for` di-parametrize (`@pytest.mark.parametrize` + `ids` deskriptif); ekspektasi error pakai `pytest.raises`.
- Jumlah target saat ini: **70 tes**.
- `tests/test_integration.py`: tes **integration end-to-end loop** `run_dn_bot` — fake capture mengembalikan `Frame` nyata dengan encoded unik (bukan SimpleNamespace), fake client SDK-shaped direplay melalui adapter asli (`_call_openrouter` + kontrak `messages.py`), hanya `execute_game_action`/`check_emergency_stop`/env yang di-patch. Jaring pengaman sebelum refactor arsitektur (plan 016).

## Env & config

- `.env` dimuat relatif cwd (`load_dotenv()` di `config.py`) → jalankan dari **root proyek**; dari folder lain gagal dengan `ImportError` atau preflight.
- `preflight_configuration()` dijalankan **sebelum** countdown 5 detik: Windows, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `DN_WINDOW_TITLE`, variabel `DN_CAPTURE_*`/`DN_MONITOR`. `_int_env` memberi pesan jelas untuk nilai non-integer.

## Dependensi & CI

- `requirements.txt`: **pin eksak `==`** (5 dependensi runtime); `requirements-dev.txt` = `-r requirements.txt` + `pytest==8.3.5`. Tanpa lockfile (keputusan sadar) → beralih ke `constraints.txt` dari `pip freeze` jika dependensi bertambah.
- `.github/workflows/tests.yml`: actions di-pin **SHA penuh** (bukan tag bergerak), `permissions: contents: read`, jalankan `compileall` + pytest.

## Git & shared checkout

- **Jangan commit tanpa diminta.** Sebelum operasi git consequential: cek reflog/refs dan branch saat ini; prefer forward-fix; gunakan `--force-with-lease` bila perlu force; hindari staging luas (`git add -A`). Jangan menimpa perubahan yang bukan milikmu.

## Follow-up pending (sesi ini)

- [x] **F-06 (Low — SELESAI)** — `_call_openrouter` memotong `detail` SDK ke `API_ERROR_DETAIL_MAX = 500` karakter (config.py) dengan suffix `... (terpotong)` sebelum masuk pesan `RuntimeError` yang di-log; 2 tes regresi (detail panjang vs pendek).
- [x] **F-07 (Low — SELESAI)** — `actions/checkout` v4.2.1 → **v7.0.1** (`3d3c42e…`) dan `actions/setup-python` v5.6.0 → **v7.0.0** (`5fda3b9…`), SHA penuh dari remote; actionlint + yaml-lint exit 0; 62 tes lokal lolos; run CI GitHub adalah verifikasi final.
- [ ] **Verifikasi fresh venv** (rencana user): `python -m venv` baru → `pip install -r requirements-dev.txt` → `pytest -q` → harapannya **67 passed** (membuktikan pin versi di lingkungan bersih).
- [ ] **Commit worktree** — package restructure + pytest idiom + SECURITY/README/CHANGELOG/AGENTS belum di-commit.
- [ ] **Opsional: `constraints.txt`** dari `pip freeze` untuk mengunci dependensi transitif (httpx, pydantic) — langkah lanjutan yang didokumentasikan di README "Dependensi & lock".
- [x] **Kandidat arsitektur #1 (SELESAI — Frame module)**: global capture state (`_capture_region`/`_capture_geometry`) diganti `Frame` immutable eksplisit.
- [x] **Kandidat arsitektur #2 (SELESAI — adapter polos)**: `_call_openrouter` mengembalikan `ModelReply` (teks + `list[ToolRequest]`), parsing SDK hanya di `api.py`; orchestrator tidak menyentuh object SDK.
- [x] **Kandidat arsitektur #3 (SELESAI — kontrak wire-shape)**: `dn_bot/messages.py` memiliki semua bentuk pesan; tidak ada dict mentah di orchestrator/capture.
- [ ] **Kandidat arsitektur #4 (dari grilling, tersisa)**: Seam input device nyata — adapter `pydirectinput` di produksi, recorder in-memory di tes.
- [ ] **Polesan tes opsional** — parametrize `test_classify_api_error_kinds` (12 kasus status→kind); CI cukup `python -m pytest -q` (testpaths sudah di `pytest.ini`).

## Dokumen terkait

- `README.md` — usage, struktur file, dependensi & lock, troubleshooting.
- `SECURITY.md` — threat model, asumsi, mitigasi, status temuan F-01..F-07 (aturan: jangan laporkan ulang item ✅ Fixed).
- `CHANGELOG.md` — Keep a Changelog; `[Unreleased]` berisi kerja worktree saat ini, `[0.1.0]` baseline committed.
