# Security Best Practices Report — aiauto (Dragon Nest Vision Input)

**Tanggal:** 2026-08-06
**Scope:** `app_dn.py`, `test_app_dn.py`, `requirements.txt`, `requirements-dev.txt`, `.github/workflows/tests.yml`, `.env.example`, `.gitignore`
**Metodologi:** Skill `security-best-practices`

> **Catatan ketersediaan guidance:** Direktori `references/` skill ini hanya berisi panduan web-server Python (`python-django`, `python-flask`, `python-fastapi`) — **tidak ada `python-general-security.md`**, dan proyek ini adalah script desktop Python polos (bukan aplikasi web). Laporan ini disusun berdasarkan best-practice keamanan Python yang well-known, bukan panduan web-server yang tidak relevan.

## Executive Summary

`app_dn.py` adalah script otomasi lokal yang sudah ter-hardening dengan baik: input dari model (semi-trusted) melewati allowlist + bounds check yang ketat, cek fokus window bersifat fail-closed, dan API key tidak pernah di-log. **Tidak ditemukan temuan Critical maupun High.** Ada **2 temuan Medium** (supply-chain dependencies, CI actions tidak di-pin) dan **3 temuan Low** (parsing env tanpa pesan jelas, potensi log injection via judul window, detail error API yang verbose). Semua perbaikan bersifat opsional dan tidak mengubah perilaku inti.

---

## Temuan — Severity Medium

### [SBP-001] Dependensi runtime tidak di-pin, tanpa lock file (Medium)

- **Lokasi:** `requirements.txt:1-5`; `requirements-dev.txt:1-2`
- **Masalah:** Semua dependensi runtime memakai lower bound (`openai>=1.40.0`, `pydirectinput>=1.0.4`, `mss>=9.0.1`, `pillow>=10.0.0`, `python-dotenv>=1.0.0`) dan tidak ada lock file. Instalasi fresh checkout bisa menarik versi masa depan yang belum diaudit; build tidak reproducible.
- **Dampak:** Dependency yang dikompromikan di masa depan bisa ikut terinstal; risiko supply-chain dan "works on my machine".
- **Rekomendasi:** Pin versi eksak (`==`) di `requirements.txt`, atau buat file constraints/lock; untuk keamanan lebih, `pip install --require-hashes`. (`pytest==8.3.5` di `requirements-dev.txt` sudah di-pin.)

### [SBP-002] CI actions di-pin ke tag yang bergerak, tanpa least-privilege (Medium)

- **Lokasi:** `.github/workflows/tests.yml` (`actions/checkout@v4`, `actions/setup-python@v5`); tidak ada blok `permissions:`
- **Masalah:** Tag mayor (`@v4`, `@v5`) adalah referensi yang bisa berubah (minor/release baru) — praktik supply-chain yang disarankan adalah pin ke SHA penuh. Selain itu workflow tidak mendeklarasikan `permissions: contents: read` (least privilege).
- **Dampak:** Action yang dikompromikan atau di-retag bisa menginjeksi langkah berbahaya; token workflow berjalan dengan permission default.
- **Rekomendasi:** Pin actions ke commit SHA penuh (dengan komentar versi), dan tambahkan `permissions: contents: read`.

### [SBP-003] Cek fokus window fail-open di platform non-Windows (Medium)

- **Lokasi:** `app_dn.py:107-109` — `def check_target_window(): if os.name != "nt": return`
- **Masalah:** Di platform selain Windows, cek keamanan fokus jendela **dilewati diam-diam** (`return` tanpa log), sementara sisa script tetap berjalan dan bisa mengirim input.
- **Dampak:** Di lingkungan yang tidak didukung, guard keselamatan inti tidak aktif tanpa peringatan — melanggar prinsip fail-closed untuk cek keselamatan.
- **Rekomendasi:** Tolak berjalan di platform non-Windows, atau minimal log warning eksplisit bahwa cek fokus dinonaktifkan. Jika sengaja dibiarkan (proyek ini Windows-only per README), dokumentasikan sebagai override.

---

## Temuan — Severity Low

### [SBP-004] Parsing environment tanpa pesan error yang actionable (Low)

- **Lokasi:** `app_dn.py:151-165` — `int(os.getenv(...))` di `_capture_region_from_env` dan `int(os.getenv("DN_MONITOR", "1"))`
- **Masalah:** Nilai env yang salah format (mis. typo di `.env`) melempar `ValueError` mentah → traceback membingungkan, bukan pesan konfigurasi yang jelas. (Pola pesan jelas sudah ada untuk kasus env tidak lengkap di fungsi yang sama.)
- **Dampak:** Developer experience buruk saat miskonfigurasi; potensi kebingungan kecil. Bukan serangan (nilai env dikendalikan operator).
- **Rekomendasi:** Validasi dengan pesan jelas per variabel, mengikuti pola pesan `DN_CAPTURE_LEFT/TOP/WIDTH/HEIGHT harus diisi semuanya.`

### [SBP-005] Potensi log injection via judul window (Low)

- **Lokasi:** `app_dn.py:119-122` (pesan `FocusLost` menginterpolasi `title_buffer.value`) → di-log di `app_dn.py:702` (`log.warning("Sesi dihentikan: %s", error)`)
- **Masalah:** Judul window foreground bisa mengandung karakter kontrol/ANSI escape yang diteruskan mentah ke log terminal.
- **Dampak:** Injeksi escape sequence ke terminal operator lokal (kerusakan tampilan, klaim palsu). Serangan memerlukan kemampuan mengubah judul window foreground di mesin lokal — eksploitability rendah.
- **Rekomendasi:** Strip karakter kontrol (mis. `\x1b`, newline) dari nilai sebelum diinterpolasi ke log.

### [SBP-006] Detail error API dicantumkan verbatim ke log (Low)

- **Lokasi:** `app_dn.py:488-495` (`detail = getattr(error, "message", None) or str(error)`; di-raise sebagai `RuntimeError`) → di-log di `app_dn.py:604` (`log.exception`)
- **Masalah:** Pesan error SDK bisa sangat panjang dan berisi metadata request; dimasukkan mentah ke log.
- **Dampak:** Log berisik; tidak ada kebocoran secret terkonfirmasi (API key tidak pernah di-log).
- **Rekomendasi:** Pertahankan pesan klasifikasi yang actionable, batasi panjang `detail` (mis. 500 karakter).

---

## Verifikasi yang Lolos (Best Practices Sudah Dipatuhi)

- **Input validation secure-by-default:** argumen tool call dari model (semi-trusted) melewati allowlist aksi, allowlist tombol, bounds-check koordinat 1024×768, penolakan area padding/emergency corner, dan clamp durasi — `execute_game_action` (app_dn.py:302), `_physical_point` (app_dn.py:221), `_validate_key` (app_dn.py:274).
- **Fail-closed:** `DN_WINDOW_TITLE` kosong → `FocusLost` ditolak (app_dn.py:110-113); kegagalan API/aksi menghentikan sesi.
- **Secret handling:** API key hanya dari env (app_dn.py:420), tidak pernah di-log; `.env` di `.gitignore`.
- **Tidak ada sink berbahaya:** 0 kemunculan `eval`/`exec`/`pickle`/`yaml.load`/`subprocess`/`os.system`/`shell=True`; tidak ada file write; tidak ada request HTTP dengan input interpolasi.
- **Deserialisasi aman:** satu-satunya `json.loads` (app_dn.py:514) memakai stdlib aman, output divalidasi.
- **Retry membungkus hanya request** (`_call_openrouter`, app_dn.py:472) — aksi tidak pernah diulang.

---

## Override yang Disengaja (untuk didokumentasikan)

1. **Backoff retry memakai `time.sleep` polos**, bukan `_safe_sleep` — keputusan desain: `_safe_sleep` melempar `EmergencyStop`/`FocusLost` (subclass `RuntimeError`) yang akan tertelan oleh `except Exception` di `_call_openrouter` dan salah diklasifikasi sebagai error API. Disarankan menambahkan komentar di kode menjelaskan alasan ini.
2. **Fail-open non-Windows** (SBP-003) — konsisten dengan README yang menyatakan Windows-only, tapi sebaiknya dituliskan eksplisit sebagai override.
