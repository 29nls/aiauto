# SECURITY.md — aiauto (Dragon Nest Vision Input)

Dokumen hidup untuk **threat model, asumsi keamanan, mitigasi yang ada, dan status temuan**.
Tujuannya: review keamanan berikutnya membaca file ini dulu dan **tidak mengulang temuan yang sudah tercatat**.

- Stempel commit terakhir yang diaudit: `89b6c5a`
- Snapshot audit detail (metodologi & pembahasan lengkap): [`security_best_practices_report.md`](./security_best_practices_report.md) (2026-08-06)
- Perbarui stempel commit dan status temuan setiap kali ada perubahan kode atau review baru.

---

## 1. Ringkasan eksekutif

`dn_bot` (package Python; entrypoint `python -m dn_bot`) adalah script otomasi desktop Windows yang sudah ter-hardening dengan baik: input dari model (semi-trusted) melewati allowlist aksi + allowlist tombol + bounds-check koordinat + clamp durasi, cek fokus window bersifat fail-closed di Windows, dan API key tidak pernah di-log.

**Tidak ada temuan Critical maupun High yang terbuka.** Sudah dimitigasi pada working tree (belum di-commit): F-01 (indirect prompt injection), F-02 (platform non-Windows ditolak — preflight + `check_target_window` fail-closed), F-03 (dependensi di-pin eksak), F-04 (CI actions di-pin SHA + least-privilege), F-05 (sanitasi judul window sebelum di-log), F-06 (detail error API dibatasi panjangnya), F-07 (actions CI di-upgrade ke major terbaru + pin SHA), F-08 (log injection via input model — aksi/nama tool/detail error SDK di-sanitasi sebelum di-log). **Tidak ada temuan terbuka.** Semua tercatat di Bagian 5.

---

## 2. Asumsi keamanan (trust boundaries)

| Boundary | Tingkat kepercayaan | Konsekuensi desain |
|---|---|---|
| **Teks dalam screenshot** (chat pemain, NPC, UI game) | **Tidak tepercaya** | Bisa berisi instruksi adversarial → potensi *indirect prompt injection*. Sudah dimitigasi: `SYSTEM_PROMPT` menandainya sebagai untrusted dengan delimiter (F-01). |
| **Model OpenRouter** | Semi-trusted | Outputnya (tool call) divalidasi ketat sebelum input fisik; bisa salah/terbujuk, tidak bisa lolos dari validasi. |
| **Konfigurasi `.env`** | Trusted (operator lokal) | Validasi tetap fail-fast dengan pesan jelas (`_int_env`). |
| **`OPENROUTER_API_KEY`** | Secret | Hanya dibaca dari env, tidak pernah di-log, `.env` di-gitignore. |
| **Aktor luar jaringan** | Di luar model | Script tidak menerima koneksi masuk; satu-satunya I/O jaringan adalah HTTPS keluar ke OpenRouter. |
| **Pengguna operator** | Trusted | Emergency stop + batas langkah adalah jaring pengaman kesalahan, bukan proteksi terhadap operator. |

**Asumsi platform & operasi:**
- **Windows-only.** `preflight_configuration` menolak platform non-Windows saat startup, dan `check_target_window` sendiri bersifat fail-closed di non-Windows (`raise FocusLost`) — pemanggilan programatik tanpa preflight juga ditolak (F-02 fixed).
- Bot dijalankan **dengan pengawasan operator**, bukan headless/unattended.
- Ini **eksperimen, bukan alat produksi**; input sintetis bisa memicu anti-cheat walau tidak menghindarinya.
- Model yang digunakan adalah model OpenRouter (disarankan `:free`) yang mendukung vision + tool calling.

---

## 3. Threat model

### 3.1 Aset

1. **Kendali input fisik** (mouse/keyboard) pada mesin operator — aset utama yang dilindungi.
2. **API key OpenRouter** — secret; kompromi = biaya/misuse atas akun operator.
3. **Akun game / karakter** — bisa diblokir publisher; risiko ToS, bukan teknis.
4. **Sesi konteks** (riwayat + screenshot) — sensitivitas rendah, dikirim ke pihak ketiga (OpenRouter).

### 3.2 Aktor

- **Adversarial content dalam game** (teks NPC/player) → mencoba memanipulasi model via gambar.
- **Model itu sendiri** (salah/berhalusinasi/dibujuk) → mengusulkan aksi berbahaya.
- **Supply chain** (dependensi pip, actions CI) → kompromi saat instalasi/build.
- **Miskonfigurasi operator** → input terkirim ke aplikasi salah.

### 3.3 Vektor serangan & kontrol

| Vektor | Kontrol utama | Lokasi | Status |
|---|---|---|---|
| **Prompt injection via screenshot** | Delimiter `<untrusted_screenshot>` + larangan menuruti instruksi dari dalam gambar + berhenti saat ambigu | `SYSTEM_PROMPT` | ✅ F-01 dimitigasi (verifikasi live tetap perlu) |
| Tool call berbahaya dari model | Allowlist 7 aksi + `additionalProperties: False` + tolak tool lain | `DRAGON_NEST_TOOL`, `extract_tool_requests` | ✅ |
| Region capture salah baca (mis-map koordinat) | Cek ukuran screenshot aktual ≠ region terkonfigurasi → `ValueError` | `capture_screen_base64` | ✅ |
| Koordinat di luar gambar / di padding / di area stop | Bounds 1024×768 + tolak padding + tolak pojok 0–5 | `_physical_point` | ✅ |
| Tombol tak diizinkan | Allowlist `MOVE_KEYS` / `ACTION_KEYS` | `_validate_key` | ✅ |
| Durasi ekstrem / non-finite | Clamp 0.05–2.0, tolak `NaN`/`inf` | `execute_game_action` | ✅ |
| Input ke aplikasi salah | Cek fokus fail-closed (`DN_WINDOW_TITLE` wajib); non-Windows ditolak eksplisit | `check_target_window` | ✅ (F-02 fixed — fail-closed penuh) |
| Aksi berulang / replikasi | 1 aksi per screenshot; sesi ≤ 10 langkah; retry hanya membungkus *request*, bukan aksi | `run_dn_bot`, `_call_openrouter` | ✅ |
| Tombol macet tertekan | `try/finally` menjamin `keyUp` | `_press_key` | ✅ |
| Key/secret bocor ke log | Key hanya dari env; tidak pernah di-log | `get_openrouter_client` | ✅ |
| Sink berbahaya (eval/exec/subprocess/file write) | Tidak ada sama sekali (0 kemunculan) | seluruh file | ✅ |
| Deserialisasi tidak aman | Hanya `json.loads` stdlib, output divalidasi | `extract_tool_requests` | ✅ |
| Konteks membesar tak terkendali | `MAX_CONTEXT_MESSAGES=8` | `_compact_messages` | ✅ |
| Log injection via input model (aksi/nama tool/detail SDK di pesan error) | `_sanitize_log_text` diterapkan pada nilai dari model (aksi, nama tool) + detail error SDK sebelum masuk pesan yang di-log | `input_control.py`, `orchestrator.py`, `api.py` | ✅ F-08 fixed |

---

## 4. Mitigasi yang ada (detail + lokasi)

Referensi berikut (nama fungsi, dengan nomor baris bila tersedia) merujuk kode pada stempel `89b6c5a`. **Sejak restrukturisasi package `dn_bot/`, kode berpindah dari `app_dn.py` ke modul-modul:** `config.py` (konstanta/env/preflight), `safety.py` (emergency stop, cek fokus, sanitasi log), `capture.py` (screenshot/koordinat), `input_control.py` (aksi fisik), `api.py` (OpenRouter/retry/kontrak tool), `orchestrator.py` (run_dn_bot). Nama fungsi tidak berubah dan sengaja diprioritaskan daripada nomor baris karena lebih tahan terhadap pergeseran kode; periksa ulang lokasi saat kode berubah.

1. **Emergency stop dua lapis**
   - `check_emergency_stop` — kursor di pojok kiri atas (0–5, 0–5) → `EmergencyStop`; dicek sebelum tiap aksi, tiap interval `_safe_sleep` (0.05 s), dan tiap langkah sesi.
   - `pydirectinput.FAILSAFE = True` — failsafe bawaan library sebagai lapisan kedua.
   - `_physical_point` menolak koordinat yang memetakan ke area fisik 0–5.
2. **Cek fokus fail-closed (Windows)** — `check_target_window`: `DN_WINDOW_TITLE` kosong → `FocusLost`; judul aktif tak cocok → `FocusLost`. Semua aksi dan tiap sleep interval melewati cek ini.
3. **Validasi input berlapis** — `_physical_point` (integer ketat, bukan `bool`, bounds, tolak padding letterbox, clamp ke region fisik), `_validate_key` (allowlist), clamp durasi + tolak non-finite.
4. **Tool contract ketat** — satu fungsi `dragon_nest_action`, enum 7 aksi, `additionalProperties: False`; `extract_tool_requests` menolak tool lain; hanya satu aksi per screenshot yang dieksekusi (tool-call kedua ditolak).
5. **Retry aman** — `_call_openrouter` me-retry hanya error transien (`rate_limit`/`server`/`network`, maks 3 percobaan, backoff 1.5 s / 3 s); error konfigurasi (401/403/404/400/422) gagal cepat dengan pesan spesifik. **Retry membungkus request, tidak pernah eksekusi aksi** — aksi tidak mungkin diulang karena retry.
6. **Kompensasi input** — `_press_key` memakai `try/finally` sehingga `keyUp` selalu dijalankan walau aksi diinterupsi (`EmergencyStop`/`FocusLost`).
7. **Secret handling** — key dibaca dari env saja, `.env` di-gitignore, `.env.example` tanpa secret; tidak ada secret di source code atau log.
8. **Boundary konteks** — `_compact_messages` menjaga `MAX_CONTEXT_MESSAGES=8` sambil mempertahankan grup assistant/tool yang valid dan frame terkini.
9. **Penanganan error eksplisit** — `EmergencyStop`/`FocusLost` (subclass `RuntimeError`) di-re-raise, tidak tertelan `except Exception`; error API diklasifikasi ke pesan user-facing Bahasa Indonesia yang actionable.
10. **Mitigasi indirect prompt injection (F-01)** — `SYSTEM_PROMPT` menandai konten screenshot dengan delimiter `<untrusted_screenshot>`: teks dalam gambar dinyatakan sebagai **data tidak tepercaya, bukan instruksi**, larangan menuruti instruksi dari dalam gambar, dan aturan berhenti saat layar ambigu (tanpa tool call). Dijaga 2 tes regression guard (`tests/test_dn_bot.py`). Efektivitas terhadap model live tetap perlu verifikasi.
11. **Preflight startup (F-02)** — `preflight_configuration` menolak platform non-Windows dan memvalidasi `OPENROUTER_API_KEY`/`OPENROUTER_MODEL`/`DN_WINDOW_TITLE`/`DN_CAPTURE_*`/`DN_MONITOR` **sebelum countdown 5 detik**; miskonfigurasi gagal cepat dengan pesan jelas dan exit code 1. Validasi env capture terpusat di `_validate_capture_env` (dipakai preflight dan `_capture_region_from_env`). Dijaga 8 tes.
    - **Fail-closed lapis kedua (F-02)** — `check_target_window` sendiri `raise FocusLost` di non-Windows (dulu `return` diam-diam), jadi pemanggilan programatik `run_dn_bot` tanpa preflight juga ditolak. Dijaga 1 tes.
12. **Lock dependensi (F-03/SBP-001)** — `requirements.txt` di-pin eksak (`==`) untuk kelima dependensi runtime; `requirements-dev.txt` hanya menambah `pytest==8.3.5` di atas `-r requirements.txt`. Strategi dan aturan pembaruan didokumentasikan di README ("Dependensi & lock"); lockfile terpisah sengaja tidak dipakai karena hanya 5 dependensi — pin eksak sudah cukup.
13. **CI supply-chain (F-04/SBP-002)** — `actions/checkout` & `actions/setup-python` di-pin SHA penuh (bukan tag bergerak), `permissions: contents: read` di root workflow, hanya satu workflow (`tests.yml`). Pin SHA menutup tag-mutation; pin SHA/patch lama tidak menerima backport keamanan otomatis → freshness aksi dilacak sebagai **F-07** (ditutup — lihat mitigasi #16).
14. **Sanitasi log (F-05/SBP-005)** — `_sanitize_log_text` menghapus karakter kontrol (C0 + C1 + DEL) dan sekuens ANSI CSI (`\x1b[...`) dari judul window aktif **sebelum** diinterpolasi ke pesan `FocusLost` yang di-log, mencegah terminal log injection. Dijaga 2 tes (unit sanitizer + integrasi ctypes).
15. **Batasi detail error API (F-06/SBP-006)** — `_call_openrouter` memotong `detail` SDK ke maks `API_ERROR_DETAIL_MAX = 500` karakter dengan suffix `... (terpotong)` sebelum masuk pesan `RuntimeError`, dan rantai exception di-suppress (`raise ... from None`) agar pesan SDK mentah yang tidak terpotong tidak bocor ke log via traceback `log.exception` — mencegah log berisik dan metadata request tersimpan verbatim. Klasifikasi actionable (`API_ERROR_MESSAGES[kind]`) tidak tersentuh. Dijaga 2 tes (detail panjang terpotong + chain di-suppress via `__cause__ is None`/`__suppress_context__`; detail pendek utuh).
16. **Freshness actions CI (F-07)** — `actions/checkout` v4.2.1 → **v7.0.1** (`3d3c42e5aac5ba805825da76410c181273ba90b1`) dan `actions/setup-python` v5.6.0 → **v7.0.0** (`5fda3b95a4ea91299a34e894583c3862153e4b97`), SHA penuh di-resolve dari remote; jalur v4 membawa backport BREAKING sehingga major terbaru dipilih (sesuai plan 008/017). Diverifikasi actionlint + yaml-lint exit 0; run CI GitHub adalah verifikasi final untuk major bump.
17. **Sanitasi input model di pesan error (F-08)** — nilai dari model yang masuk ke pesan error diperlakukan seperti nilai tak tepercaya lain (perluasan F-05 yang hanya mencakup judul window): aksi tak dikenal (`Aksi tidak diizinkan: …` di `input_control.py` dan wrapper `RuntimeError` di `orchestrator.py`) dan nama tool tak dikenal (`Tool tidak diizinkan: …` di `api.py`) di-strip karakter kontrol/ANSI via `_sanitize_log_text` sebelum di-log via traceback `log.exception`; detail error SDK ikut disanitasi setelah truncation F-06. Dijaga 5 tes regresi + demo mekanis (LEAK False untuk ketiga vektor).

---

## 5. Status temuan (checklist anti-duplikasi)

> **Aturan:** review berikutnya TIDAK melaporkan ulang item berstatus ✅ FIXED, ➖ REJECTED, atau 🔵 OVERRIDE — hanya yang 🔴 OPEN.

> **Catatan untuk reviewer:** laporan `security_best_practices_report.md` menyebut "2 Medium" di executive summary-nya, padahal isinya mencantumkan 3 temuan Medium (SBP-001, SBP-002, SBP-003). Inkonsistensi ada di laporan asli; SECURITY.md berikut ini benar menandai F-02 (SBP-003) sebagai Medium.

### 🔴 Terbuka

Tidak ada temuan terbuka per 2026-08-06 (F-01..F-07 semuanya fixed/mitigated).

### ✅ Fixed / sudah benar (jangan dilaporkan ulang)

| ID | Temuan lama | Status |
|---|---|---|
| **SBP-004** | Parsing env raw `int(os.getenv(...))` tanpa pesan jelas | ✅ **Fixed** — `_int_env` (baris 139) fail-fast dengan pesan jelas; laporan lama menulis sebelum fix ini. |
| **F-05** | Log injection via judul window: `title_buffer.value!r` diinterpolasi mentah ke pesan lalu di-log (SBP-005) | ✅ **Fixed** — `_sanitize_log_text` (sebelum `check_target_window`) menghapus karakter kontrol (C0/C1/DEL) + sekuens ANSI CSI dari judul window aktif sebelum diinterpolasi ke pesan `FocusLost`; sanitasi dilakukan sebelum perbandingan casefold. Dijaga 2 tes. |
| **F-06** | Detail error API verbose ikut di-log (SBP-006) | ✅ **Fixed** — `_call_openrouter` memotong `detail` SDK ke maks 500 karakter (`API_ERROR_DETAIL_MAX`, config.py) dengan suffix `... (terpotong)` sebelum masuk pesan `RuntimeError`; klasifikasi actionable (`API_ERROR_MESSAGES[kind]`) tetap utuh. Dijaga 2 tes (`error_detail`). |
| **F-07** | Versi actions CI ketinggalan (pin SHA/patch tidak menerima backport) | ✅ **Fixed** — `actions/checkout` di-upgrade v4.2.1 → **v7.0.1** (`3d3c42e…`) dan `actions/setup-python` v5.6.0 → **v7.0.0** (`5fda3b9…`), SHA penuh di-resolve dari remote (bukan tag bergerak). Jalur v4 membawa backport BREAKING (`allow-unsafe-pr-checkout` default) sehingga lompat ke major terbaru lebih bersih. Diverifikasi actionlint + yaml-lint exit 0, 62 tes lokal lolos; run CI GitHub adalah verifikasi final. |
| **F-08** | Log injection via input model: aksi tool call / nama tool tak dikenal / detail error SDK di-embed mentah ke pesan error yang di-log via traceback `log.exception` (F-05 hanya mencakup judul window) | ✅ **Fixed** — `_sanitize_log_text` diterapkan pada aksi (`Aksi tidak diizinkan: …` di `input_control.py` + wrapper `RuntimeError` di `orchestrator.py`), nama tool (`Tool tidak diizinkan: …` di `api.py`), dan detail error SDK (setelah truncation F-06). Dijaga 5 tes regresi; demo mekanis mengonfirmasi LEAK False untuk ketiga vektor. |
| **F-01** | Indirect prompt injection via teks screenshot (VERIFY-001) | ✅ **Mitigated** (working tree, belum di-commit) — `SYSTEM_PROMPT` kini menandai konten gambar dengan delimiter `<untrusted_screenshot>` + larangan menuruti instruksi dari dalam gambar + aturan berhenti saat layar ambigu. Dijaga oleh 2 tes regression guard. Efektivitas terhadap model live tetap perlu verifikasi (Bagian 6). |
| **F-02** | Cek fokus **fail-open** di non-Windows (SBP-003) | ✅ **Fixed (fail-closed penuh)** — dua lapis: (1) `preflight_configuration` menolak platform non-Windows sebelum countdown (RuntimeError); (2) `check_target_window` sendiri kini `raise FocusLost` di non-Windows (bukan `return` diam-diam) sehingga pemanggilan programatik `run_dn_bot` tanpa preflight pun ditolak. Dijaga 2 tes. |
| **F-03** | Dependensi runtime tidak di-pin, tanpa lock file (SBP-001) | ✅ **Fixed** — `requirements.txt` di-pin eksak (`openai==2.53.0`, `pydirectinput==1.0.4`, `mss==10.2.0`, `pillow==12.3.0`, `python-dotenv==1.2.2`), diverifikasi 51/51 tes di venv bersih; strategi lock/constraints didokumentasikan di README ("Dependensi & lock"). |
| **F-04** | CI actions di-pin ke tag bergerak tanpa least-privilege (SBP-002) | ✅ **Fixed** — `actions/checkout` di-pin SHA `eef6144…` (v4.2.1), `actions/setup-python` di-pin SHA `a26af69…` (v5.6.0), `permissions: contents: read` di root workflow. SHA diverifikasi ulang dari remote 2026-08-06 (40-hex, persis cocok dengan tag-nya). Catatan: SHA immutable menutup tag-mutation, **tetapi pin SHA/patch lama tidak otomatis menerima backport keamanan** — enforcement pwn-request checkout (2026-06-18) masuk v4.4.0+, bukan ke pin v4.2.1; tidak eksploitabel oleh workflow ini (tanpa `pull_request_target`), tapi freshness aksi dilacak sebagai **F-07**. |
| Semua kontrol Bagian 3.3 yang bertanda ✅ | Allowlist, bounds, fail-closed, retry aman, keyUp terjamin, secret handling | ✅ Terverifikasi pada stempel `89b6c5a` (unit test + audit `security-best-practices`). |

### ➖ Rejected / by-design (jangan dilaporkan ulang)

| ID | Item | Alasan |
|---|---|---|
| **OVR-01** | Retry memakai `time.sleep` polos, bukan `_safe_sleep` | Disengaja: `_safe_sleep` melempar `EmergencyStop`/`FocusLost` (subclass `RuntimeError`) yang akan tertelan `except Exception` di `_call_openrouter` dan salah diklasifikasi sebagai error API. |
| **OVR-02** | Fail-open non-Windows | **Superseded** — F-02 kini fail-closed penuh (preflight + `check_target_window`); tidak ada lagi jalur yang berjalan di non-Windows tanpa penolakan eksplisit. |
| **BYD-01** | `move_camera` dua panggilan `moveTo` (center → target) | Keputusan terdokumentasi (komentar kode + README): anchor ke tengah agar tak bergantung posisi cursor sebelumnya dan tak menumpuk drift. |
| **BYD-02** | Screenshot berisi konten pemain lain (chat, nama akun) dikirim ke OpenRouter | Risiko privasi Low yang diterima: data hanya dikirim ke OpenRouter (HTTPS), bukan publik; operator memilih region capture. |

---

## 6. Batasan yang disengaja

- **Bukan proteksi terhadap operator**, bukan alat anti-cheat, bukan sistem produksi.
- Input sintetis dapat tetap memicu anti-cheat walau script tidak menghindarinya — risiko ToS ada di luar kendali teknis script.
- Kualitas *vision* dan kepatuhan model terhadap prompt hanya bisa diverifikasi penuh dengan **uji live** (game nyata); suite tes offline tidak bisa membuktikan mitigasi F-01 berfungsi.

---

## 7. Checklist review berikutnya

1. Baca file ini + `security_best_practices_report.md` — jangan ulangi 🔴/✅/➖ yang tercatat.
2. Periksa hanya: (a) kode yang berubah sejak stempel `89b6c5a`, (b) status 🔴 yang berpindah (tidak ada yang terbuka per 2026-08-06), (c) vektor baru yang tidak ada di Bagian 3.3. (F-01…F-08 sudah mitigated/fixed; jangan dilaporkan ulang.)
3. Setelah selesai, perbarui: stempel commit, status temuan, dan tambahkan temuan baru (jika ada) dengan ID berikutnya (F-08…).
4. Jangan pernah menulis nilai secret ke dokumen ini — hanya `file:line` + tipe kredensial + rekomendasi rotasi.
