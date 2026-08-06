# Changelog

Semua perubahan penting pada proyek ini akan didokumentasikan di file ini.

Format mengikuti [Keep a Changelog](https://keepachangelog.com/id/1.1.0/), dan proyek ini menganut [Semantic Versioning](https://semver.org/lang/id/).

## [Unreleased]

### Added

- Package `dn_bot/` baru: 6 modul bebas-cycle (`config`, `safety`, `capture`, `input_control`, `api`, `orchestrator`) + `__init__` re-export + `__main__` entrypoint, menggantikan file tunggal `app_dn.py`.
- Konfigurasi pytest di `pytest.ini` (`testpaths = tests`, `pythonpath = .`) — `python -m pytest` berjalan tanpa argumen dari root proyek.
- Fixture `capture_region` di `tests/conftest.py` untuk me-pin global state capture (`_capture_region`/`_capture_geometry`) per tes.
- `SECURITY.md` baru: threat model, asumsi, mitigasi, dan daftar temuan (F-01..F-07) agar review keamanan berikutnya tidak mengulang temuan yang sama.

### Changed

- Restrukturisasi penuh dari script tunggal `app_dn.py` menjadi package `dn_bot/` dengan entrypoint `python -m dn_bot`.
- `capture.py`: global state tersembunyi (`_capture_region`/`_capture_geometry`) dihapus — diganti `Frame` immutable eksplisit (encoded JPEG + geometry) yang diteruskan ke `_physical_point` dan `execute_game_action` (prinsip determinism; kandidat arsitektur #1).
- Suite offline dimigrasi ke `tests/` dan dirapikan ke idiom pytest: 5 loop `for` di-parametrize (`@pytest.mark.parametrize` dengan id deskriptif), blok `try/except` menjadi `pytest.raises`, dan sys.path hack di conftest digantikan opsi `pythonpath`.
- Workflow CI (`tests.yml`) diperbarui untuk layout package.
- `README.md`: usage `python -m dn_bot`, struktur file, section "Dependensi & lock", klausa working-directory, dan catatan `pytest.ini`.

### Removed

- `app_dn.py` dan `test_app_dn.py` dihapus (digantikan package `dn_bot/` + `tests/`).

### Security

- `check_target_window` kini **fail-closed** di platform non-Windows: menolak berjalan dengan pesan jelas, termasuk untuk pemanggilan programatik yang tidak lewat preflight (F-02/SBP-003).
- Judul window aktif di-sanitasi sebelum di-log — karakter kontrol (C0/C1) dan sekuens ANSI di-strip — untuk mencegah log injection (F-05/SBP-005).
- Detail error API dibatasi panjangnya (maks 500 karakter, suffix `... (terpotong)`) sebelum masuk pesan error yang di-log, tanpa mengubah klasifikasi actionable (F-06/SBP-006).
- Versi dependensi runtime di-pin eksak (`==`) di `requirements.txt`; kebijakan lock/constraints didokumentasikan (F-03/SBP-001).
- Actions CI di-pin ke SHA commit penuh dan `permissions: contents: read` ditambahkan di workflow (F-04/SBP-002).

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
