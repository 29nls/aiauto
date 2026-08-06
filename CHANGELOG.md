# Changelog

Semua perubahan penting pada proyek ini akan didokumentasikan di file ini.

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/), dan proyek ini menganut [Semantic Versioning](https://semver.org/lang/id/).

## [Unreleased]

### Added

- Package `dn_bot/` baru: 6 modul bebas-cycle (`config`, `safety`, `capture`, `input_control`, `api`, `orchestrator`) + `__init__` re-export + `__main__` entrypoint, menggantikan file tunggal `app_dn.py`.
- Konfigurasi pytest di `pytest.ini` (`testpaths = tests`, `pythonpath = .`) — `python -m pytest` berjalan tanpa argumen dari root proyek.
- `tests/test_integration.py`: 3 tes integration end-to-end loop `run_dn_bot` (fake capture `Frame` nyata dengan encoded unik + fake client SDK-shaped direplay melalui adapter asli) — alur penuh 2 langkah, satu aksi per siklus, dan aksi siklus berikutnya dimetakan ke frame segar; jaring pengaman sebelum refactor arsitektur (plan 016).
- Fixture `capture_region` di `tests/conftest.py` untuk me-pin global state capture (`_capture_region`/`_capture_geometry`) per tes.
- `SECURITY.md` baru: threat model, asumsi, mitigasi, dan daftar temuan (F-01..F-07) agar review keamanan berikutnya tidak mengulang temuan yang sama.
- `dn_bot/device.py` baru: seam input device — `DeviceInput` protocol + `PyDirectInputDevice` adapter (satu-satunya modul yang mengimpor `pydirectinput`); `RecordingDevice` in-memory di `tests/conftest.py` meng-assert urutan input tanpa patch namespace library (kandidat arsitektur #4, plan 012/015).
- Packaging setuptools via `pyproject.toml` baru: metadata paket (`version 0.2.0.dev0`, `requires-python >= 3.10`), console script `dn-bot = dn_bot.__main__:main`, dan runtime `dependencies` yang memirror `requirements.txt` (tetap source of truth — tes drift `test_pyproject_runtime_dependencies_match_requirements_txt` mencegah divergence). Setelah `pip install -e .`, `python -m dn_bot` berfungsi dari folder mana pun dan tersedia `dn-bot`; wart direktori kerja di README dihapus (temuan survey T4).

### Changed

- Restrukturisasi penuh dari script tunggal `app_dn.py` menjadi package `dn_bot/` dengan entrypoint `python -m dn_bot`.
- `capture.py`: global state tersembunyi (`_capture_region`/`_capture_geometry`) dihapus — diganti `Frame` immutable eksplisit (encoded JPEG + geometry) yang diteruskan ke `_physical_point` dan `execute_game_action` (prinsip determinism; kandidat arsitektur #1).
- `dn_bot/messages.py` baru: satu module kontrak wire-shape pesan OpenAI-compatible (`user_text`, `image_block`, `frame_message`, `assistant_message`, `tool_result`, `tool_calls_wire`) + tipe polos `ToolRequest`/`ModelReply` — tidak ada lagi dict pesan mentah di orchestrator/capture (kandidat arsitektur #3).
- Adapter OpenRouter (`_call_openrouter`) kini mengembalikan `ModelReply` polos (teks + tool requests terurai) dan mem-parse respons SDK di luar loop retry; `api.py` menjadi satu-satunya modul yang menyentuh object SDK, `extract_tool_requests` mengembalikan `list[ToolRequest]` (kandidat arsitektur #2).
- `input_control.py`/`safety.py`: `execute_game_action`, `check_emergency_stop`, dan `_safe_sleep` menerima device via dependency injection (default = adapter produksi); device yang di-inject di-thread ke seluruh guard jalur aksi — tidak ada lagi panggilan `pydirectinput` langsung di luar adapter (kandidat arsitektur #4).
- `tests/test_integration.py`: tes integration ke-4 (`test_integration_real_input_sequence_via_recorder`, plan 016 item 3) mengeksekusi `execute_game_action` asli dengan `RecordingDevice` — urutan input fisik `move_camera`/`wait` di-assert langsung dari recorder, bukan mock.
- Suite offline dimigrasi ke `tests/` dan dirapikan ke idiom pytest: 5 loop `for` di-parametrize (`@pytest.mark.parametrize` dengan id deskriptif), blok `try/except` menjadi `pytest.raises`, dan sys.path hack di conftest digantikan opsi `pythonpath`.
- Workflow CI (`tests.yml`) diperbarui untuk layout package.
- `README.md`: usage `python -m dn_bot`, struktur file, section "Dependensi & lock", klausa working-directory, dan catatan `pytest.ini`.
- `get_openrouter_client` kini memasang timeout bawaan 60 detik (env `OPENROUTER_TIMEOUT`, bilangan bulat positif dalam detik) pada client OpenRouter; request yang hang dibatasi dan diklasifikasi sebagai error jaringan (retryable) oleh loop retry, sehingga sesi tidak terkunci hingga batas default SDK (~600 s × 3 percobaan) tanpa responsivitas (temuan survey T1).
- Retry backoff di `_call_openrouter` kini **responsif terhadap emergency**: jeda antar percobaan memakai `safety._safe_sleep` (interval ≤50 ms dengan cek pojok failsafe + fokus jendela tiap tick), jadi pengguna bisa menghentikan sesi di tengah backoff — `EmergencyStop`/`FocusLost` diteruskan keluar loop tanpa dibungkus menjadi error API (temuan survey T2).
- Tujuan sesi kini dapat dikonfigurasi: env `DN_INSTRUCTION` atau flag CLI `--instruction` (stdlib argparse; precedence **CLI > env > `DEFAULT_INSTRUCTION`** di config.py). Perilaku no-args tetap byte-identical dengan teks bawaan sebelumnya (temuan survey T3).
- Preflight kini menolak `OPENROUTER_API_KEY` yang jelas tidak valid — tanpa prefix `sk-or-v1-` atau terlalu pendek (`OPENROUTER_KEY_MIN_LENGTH`), termasuk placeholder `.env.example` — dengan pesan actionable sebelum countdown, bukan menunggu 401 saat runtime (temuan survey T7).
- Workflow CI (`tests.yml`) kini menjalankan matrix Python **3.10 / 3.12 / 3.14** (rentang dukungan yang diklaim README; kompatibilitas wheel pin diverifikasi), plus `pip check` setelah install, `timeout-minutes: 10` per job, dan pip cache via `setup-python` — konvensi SHA penuh + least-privilege tetap (temuan survey T5).

### Removed

- `app_dn.py` dan `test_app_dn.py` dihapus (digantikan package `dn_bot/` + `tests/`).

### Security

- `check_target_window` kini **fail-closed** di platform non-Windows: menolak berjalan dengan pesan jelas, termasuk untuk pemanggilan programatik yang tidak lewat preflight (F-02/SBP-003).
- Judul window aktif di-sanitasi sebelum di-log — karakter kontrol (C0/C1) dan sekuens ANSI di-strip — untuk mencegah log injection (F-05/SBP-005).
- Detail error API dibatasi panjangnya (maks 500 karakter, suffix `... (terpotong)`) sebelum masuk pesan error yang di-log, tanpa mengubah klasifikasi actionable (F-06/SBP-006).
- Input model yang masuk ke pesan error di-sanitasi seperti nilai tak tepercaya lainnya: aksi tak dikenal (`Aksi tidak diizinkan: …`) dan nama tool tak dikenal (`Tool tidak diizinkan: …`) di-strip karakter kontrol/ANSI sebelum di-log via traceback, dan detail error SDK ikut disanitasi (perluasan F-05 ke input dari model dan data SDK).
- Versi dependensi runtime di-pin eksak (`==`) di `requirements.txt`; kebijakan lock/constraints didokumentasikan (F-03/SBP-001).
- Actions CI di-pin ke SHA commit penuh dan `permissions: contents: read` ditambahkan di workflow (F-04/SBP-002).
- Actions CI di-upgrade ke major terbaru dengan SHA penuh dari remote: `actions/checkout` v4.2.1 → v7.0.1, `actions/setup-python` v5.6.0 → v7.0.0 (F-07).

## [0.1.0] - 2026-08-06

Versi awal eksperimen vision input untuk Dragon Nest via OpenRouter + tool calling, diimplementasikan sebagai script tunggal `app_dn.py`.

### Added

- Loop orchestrator: capture → model vision OpenRouter → validasi aksi allow-listed → frame baru.
- Function call `dragon_nest_action` dengan action `mouse_move`, `left_click`, `right_click`, `press_move_key`, `press_action_key`, `move_camera`, dan `wait`; tombol, koordinat, dan durasi divalidasi sebelum input fisik via `pydirectinput`.
- Pemetaan koordinat: region capture di-letterbox ke JPEG 1024×768, padding tidak dapat diklik, titik pada area content dipetakan kembali ke koordinat fisik.
- Batas pertumbuhan context: kompaksi riwayat, maksimal 10 langkah per sesi, satu aksi fisik per siklus observasi, frame terbaru sebagai sumber visual authoritative.
- Retry/backoff terbatas untuk error transien OpenRouter (429, 5xx, koneksi) tanpa mengulang aksi; error konfigurasi gagal cepat dengan pesan penyebab spesifik.
- Preflight konfigurasi sebelum countdown 5 detik: platform Windows, `OPENROUTER_API_KEY`, `OPENROUTER_MODEL`, `DN_WINDOW_TITLE`, dan variabel `DN_CAPTURE_*`/`DN_MONITOR`.
- Observability ringan tanpa secret: session ID unik, durasi per langkah, dimensi region capture, dan latensi request model.
- Setup tes offline (`requirements-dev.txt`, `pytest`) dan workflow GitHub Actions (`tests.yml`).

### Fixed

- Pergerakan kamera di-anchor ke koordinat layar (dari titik tengah ke endpoint absolut) agar posisi kursor sebelumnya tidak memengaruhi hasil dan aksi berulang tidak mengakumulasi drift.

### Security

- Konten screenshot ditandai sebagai data **tidak tepercaya** di `SYSTEM_PROMPT` dengan delimiter eksplisit (`<untrusted_screenshot>`); layar yang ambigu atau berisi instruksi mengakhiri sesi tanpa aksi (F-01).
