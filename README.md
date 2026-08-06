# Dragon Nest Vision Input Experiment

Proyek Python untuk eksperimen **vision model melalui OpenRouter + custom tool calling** yang membaca screenshot dan mengirim input terbatas melalui `pydirectinput` pada Windows.

> **Peringatan penting:** Otomasi game online dapat melanggar Terms of Service dan dapat menyebabkan akun atau perangkat diblokir. Jangan gunakan pada akun utama, PvP, ekonomi game, farming otomatis, atau untuk menghindari anti-cheat. Gunakan hanya pada lingkungan dan akun yang memang diizinkan oleh publisher.

## Target perangkat

- Laptop: ASUS VivoBook X442URR
- OS: Windows 10/11
- Python: 3.10 atau lebih baru
- Koneksi internet untuk OpenRouter API

Laptop ini cukup untuk eksperimen capture layar ringan, tetapi respons AI cloud memiliki latensi sehingga tidak cocok untuk combat real-time, PvP, atau situasi yang membutuhkan reaksi cepat.

## Apa yang dibutuhkan

1. Python 3.10+ untuk Windows.
2. API key OpenRouter yang disimpan lokal.
3. Model gratis OpenRouter yang mendukung **vision dan tool/function calling**. Dukungan model gratis dapat berubah; cek katalog model OpenRouter sebelum menjalankan.
4. Dragon Nest dalam mode windowed agar area capture dan input mudah diuji.
5. `mss`, `Pillow`, `openai`, `python-dotenv`, dan `pydirectinput`.
6. Izin penggunaan otomasi sesuai aturan game. Script ini **tidak** menyertakan injeksi DLL, memory editing, hooking, atau fitur untuk menghindari anti-cheat.

## Instalasi

Buka Command Prompt/PowerShell pada folder proyek:

```bat
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
```

Setelah virtual environment aktif, untuk menjalankan tes offline dari fresh checkout pasang dependency development yang juga memasang dependency runtime:

```bat
python -m pip install -r requirements-dev.txt
python -m pytest -q tests
```

Opsional — install paket itu sendiri (metadata di `pyproject.toml`) agar `python -m dn_bot` berfungsi dari **folder mana pun** dan tersedia console script `dn-bot`:

```bat
python -m pip install -e .   # editable: perubahan kode langsung terpakai tanpa install ulang
```

Edit `.env` secara lokal:

```dotenv
OPENROUTER_API_KEY=sk-or-v1-isi-api-key-di-sini
# Isi dengan model gratis yang saat ini tersedia di OpenRouter dan mendukung vision + tools.
OPENROUTER_MODEL=isi-model-free-yang-mendukung-vision-dan-tools
DN_WINDOW_TITLE=Dragon Nest
```

Jangan commit `.env`, karena berisi secret API. Jangan menaruh API key di source code.

## Dependensi & lock

`requirements.txt` memakai **pin eksak** (`==`) sebagai lock sederhana untuk kelima dependensi runtime:

```text
openai==2.53.0
pydirectinput==1.0.4
mss==10.2.0
pillow==12.3.0
python-dotenv==1.2.2
```

Aturan pemeliharaan:

- **Pemasangan deterministik (top-level)** — `pip install -r requirements.txt` selalu memasang kelima dependensi runtime pada versi yang sama persis; dependensi transitif (mis. `httpx`, `pydantic` yang ditarik `openai`) tidak di-pin dan dapat berubah, kecuali dikunci lewat `constraints.txt`.
- **`requirements-dev.txt`** menambah `pytest==8.3.5` di atas pin runtime (`-r requirements.txt`), jadi suite tes offline berjalan di versi yang identik dengan produksi.
- **Memperbarui versi** — ubah satu pin, instal di venv bersih, lalu jalankan seluruh suite tes offline sebelum menaikkan versi berikutnya. `openai` saat ini versi 2.x; kode memakai `chat.completions.create` + `tools` yang terverifikasi oleh suite tes.
- **Tanpa lockfile terpisah (sengaja)** — proyek hanya punya 5 dependensi runtime, pin eksak sudah cukup. Jika dependensi bertambah banyak atau CI memakai ekosistem berbeda, tambahkan `constraints.txt` dari `pip freeze` untuk mengunci versi transitif juga.
- **Packaging** — `pyproject.toml` memirror kelima pin runtime sebagai `dependencies` (untuk `pip install .` / `pip install -e .`); tes drift memastikan daftar di sana tidak menyimpang dari `requirements.txt`, yang tetap satu-satunya source of truth.

## Menjalankan

1. Pastikan penggunaan bot/otomasi diizinkan oleh publisher Dragon Nest.
2. Jalankan game dalam **windowed mode**.
3. Pastikan karakter berada di tempat yang aman dan tujuan eksperimen jelas.
4. Aktifkan virtual environment.
5. Jalankan:

```bat
python -m dn_bot
```

Paket `dn_bot` kini punya metadata packaging (`pyproject.toml`). Setelah `python -m pip install -e .` dijalankan sekali (lihat Instalasi), `python -m dn_bot` berfungsi dari **folder mana pun**, dan tersedia pula console script `dn-bot` yang setara. Tanpa install, perintah hanya berjalan dari root proyek (paket ditemukan lewat cwd/`PYTHONPATH`) dan dari folder lain gagal dengan `ImportError: No module named 'dn_bot'`. Catatan: `.env` tetap dimuat relatif terhadap direktori kerja (tanpa pesan jika tidak ditemukan) — jalankan dari folder yang berisi `.env` (atau set env secara langsung), karena jika tidak preflight gagal dengan pesan seperti "OPENROUTER_API_KEY belum diatur".

Sebelum countdown lima detik, script menjalankan **preflight konfigurasi**: memastikan platform Windows, `OPENROUTER_API_KEY` terisi **dan berformat wajar** (diawali `sk-or-v1-` dengan panjang minimal — placeholder di `.env.example` ditolak), `OPENROUTER_MODEL`, dan `DN_WINDOW_TITLE` terisi, serta variabel capture (`DN_CAPTURE_*`/`DN_MONITOR`) valid. Jika ada yang salah, script berhenti dengan pesan yang jelas tanpa menunggu countdown. Cek fokus jendela (`check_target_window`) juga bersifat **fail-closed di non-Windows**: menolak berjalan (bukan melewati cek diam-diam), termasuk untuk pemanggilan programatik yang tidak lewat preflight.

Tujuan sesi dapat diatur lewat flag CLI `--instruction "<teks>"` atau env `DN_INSTRUCTION` di `.env` (flag CLI menang atas env). Jika keduanya tidak diatur, dipakai teks bawaan — sama persis dengan perilaku default sebelumnya.

### Farming Minotaur berkelanjutan (`--farm-profile minotaur`)

Untuk workflow farming yang memang diizinkan oleh game/server, gunakan profil Minotaur dengan watchdog:

```bat
python -m dn_bot --farm-profile minotaur --until-stopped
```

Profil ini menjalankan alur state terstruktur: `pre_dungeon` → `entering_dungeon` → `combat` → `boss_reward` → `loot_chest` → `loot_result` → `return_navigation` → kembali ke `pre_dungeon`. Setelah boss mati, agent melewati pemilihan box/review, mencari peti loot di map, mengklik peti yang terlihat jelas, lalu memakai `F12` untuk membuka UI town/stage sebelum memulai run berikutnya. Setiap respons model wajib menyatakan state farming berikutnya; transisi yang tidak legal, layar ambigu, aksi berulang tanpa progres, state terlalu lama, atau recovery berulang akan menghentikan sesi dengan aman.

`--until-stopped` tidak menghapus guard: emergency stop, `Ctrl+C`, fokus jendela, timeout per state, dan watchdog tetap aktif. Mode ini tidak memakai koordinat hardcoded; klik peti dan UI ditentukan dari screenshot terbaru oleh model dan tetap melewati validasi aksi yang sama. Untuk rehearsal tanpa input fisik:

```bat
python -m dn_bot --farm-profile minotaur --until-stopped --dry-run
```

Profil farming harus selalu diuji dengan `--dry-run` terlebih dahulu. Jika UI game berbeda dari alur di atas, sesi lebih baik berhenti daripada melakukan klik acak.

### Mode latihan (`--dry-run`)

Untuk melatih (rehearsal) loop penuh **tanpa input fisik apa pun**, jalankan dengan flag `--dry-run`:

```bat
python -m dn_bot --dry-run
```

Mode ini menjalankan siklus capture → model → aksi → frame baru persis seperti sesi normal, tetapi aksi fisik yang dimaksud **hanya di-log dan tidak pernah dieksekusi**: setiap primitif input dicatat dengan prefix `[dry-run]` (mis. `[dry-run] moveTo(512, 384)`, `[dry-run] keyDown(f)`), sehingga cursor dan tombol tidak tersentuh sama sekali. Pemeriksaan keselamatan tetap berperilaku wajar: cek emergency stop tetap berjalan tetapi membaca posisi kursor yang disimulasikan aman (kursor tidak pernah digerakkan bot, jadi tidak pernah memicu abort — `Ctrl+C` tetap menghentikan sesi), dan cek fokus jendela (`DN_WINDOW_TITLE`) tetap berlaku. Kombinasikan dengan `--instruction "<teks>"` untuk menguji tujuan berbeda.

Script memberi waktu lima detik untuk memindahkan fokus ke jendela game. **Hak Administrator tidak selalu diperlukan dan tidak menjamin input akan diterima.** Jika client game berjalan dengan hak yang lebih tinggi daripada terminal, Windows dapat membatasi input lintas proses.

Jika pengujian yang sah di komputer kamu memang membutuhkan terminal elevated, buka Command Prompt atau VS Code dengan klik kanan → **Run as Administrator**, lalu ulangi perintah di atas. Jangan menaikkan hak akses hanya untuk mengakali proteksi game.

Untuk mencegah aksi dikirim ke aplikasi yang salah, isi `DN_WINDOW_TITLE`. Jika game hanya menempati sebagian monitor, gunakan `DN_CAPTURE_LEFT`, `DN_CAPTURE_TOP`, `DN_CAPTURE_WIDTH`, dan `DN_CAPTURE_HEIGHT` di `.env` agar screenshot dan koordinat sesuai region game. Capture akan diberi padding letterbox jika aspect ratio region bukan 4:3; area padding tidak dapat diklik. Jika tidak diisi, script memakai monitor MSS yang dipilih oleh `DN_MONITOR` (default `1`).

### Emergency stop

- Gerakkan kursor ke pojok kiri atas layar; pemeriksaan tambahan akan menghentikan sesi.
- Tekan `Ctrl+C` pada terminal.
- Jangan meninggalkan script tanpa pengawasan.

## Cara kerja

```text
Screenshot monitor
      │ mss + Pillow
      ▼
JPEG 1024x768 ──► OpenRouter vision model
                      │ OpenAI-compatible function call
                      ▼
       allow-listed input validation
                      │
                      ▼
              pydirectinput
```

- Screenshot region game dipertahankan aspect ratio-nya, lalu dipasang di tengah canvas JPEG 1024×768 dengan padding hitam dan dikirim sebagai data URI.
- Koordinat model pada area padding ditolak; koordinat pada area game dipetakan kembali memakai offset, ukuran content, dan capture region fisik.
- Prompt agent juga menandai padding sebagai area non-actionable agar model memilih titik di dalam game.
- Konten yang tampil di dalam screenshot (chat, dialog NPC, tulisan UI) diperlakukan sebagai **data tidak tepercaya**: `SYSTEM_PROMPT` menandainya dengan delimiter eksplisit (`<untrusted_screenshot>`) dan melarang menuruti instruksi yang berasal dari dalam gambar. Layar yang ambigu atau bertentangan dengan tujuan sesi mengakhiri sesi tanpa aksi.
- `openai` Python SDK diarahkan ke `https://openrouter.ai/api/v1`.
- Model hanya dapat memanggil function `dragon_nest_action` dengan action yang di-allowlist.
- Tombol, koordinat, dan durasi divalidasi sebelum input dikirim.
- `move_camera` memakai endpoint absolut yang divalidasi, lalu menggerakkan cursor dari anchor tengah ke endpoint tersebut; posisi cursor sebelumnya tidak memengaruhi hasil dan aksi berulang tidak mengakumulasi drift.
- Input fisik dilewatkan lewat seam `DeviceInput` (`dn_bot/device.py`): adapter `pydirectinput` di produksi, recorder in-memory di tes, dan `DryRunDevice` untuk mode latihan `--dry-run` (meng-log aksi yang dimaksud tanpa mengeksekusinya) — mengganti library input cukup mengimplementasikan protocol baru, tanpa menyentuh logika aksi.
- Setelah aksi, screenshot baru dikirim sebagai pesan user berikutnya dan menggantikan frame lama sebagai sumber visual yang authoritative.
- Riwayat request dibatasi agar context tidak terus membesar; instruction awal, tool-call/result terbaru yang masih diperlukan, dan screenshot terkini dipertahankan.
- Satu siklus observasi menjalankan paling banyak satu aksi fisik.
- Sesi dibatasi maksimal 10 langkah.
- Panggilan OpenRouter memakai retry terbatas (maksimal 3 percobaan, yaitu 2 retry) dengan backoff untuk error transien (rate limit 429, gangguan server 5xx, koneksi). Retry hanya membungkus permintaan, bukan eksekusi aksi, sehingga aksi tidak pernah diulang. Error konfigurasi (API key, model, request ditolak) tidak diulang dan langsung melaporkan penyebab yang spesifik.
- Setiap request OpenRouter dibatasi timeout bawaan **60 detik** (atur `OPENROUTER_TIMEOUT` di `.env`, bilangan bulat positif dalam detik). Request yang hang diklasifikasi sebagai error jaringan dan ikut dicoba ulang oleh loop retry, sehingga sesi tidak terkunci tanpa responsivitas sampai batas default SDK.
- Log berisi observability ringan **tanpa secret**: session ID unik per sesi, durasi tiap langkah, dimensi region capture, dan latensi tiap request OpenRouter. API key, token, dan konten percakapan tidak pernah di-log. Judul window aktif di-sanitasi (karakter kontrol dan sekuens ANSI di-strip) sebelum masuk ke pesan log, dan detail pesan error OpenRouter dibatasi panjangnya (maks 500 karakter) agar log tidak berisik.

Function yang tersedia:

- `mouse_move`
- `left_click`
- `right_click`
- `press_move_key` untuk `w/a/s/d/q/e`
- `press_action_key` untuk tombol terbatas seperti `f`, `f12`, `space`, `0-9`, atau `shift`
- `move_camera` untuk mengarahkan camera ke endpoint absolut di content game; cursor di-anchor ke titik tengah screenshot pada setiap aksi
- `wait`

Ini memakai function calling OpenAI-compatible melalui OpenRouter, bukan native computer-use API. Tidak semua model gratis mendukung vision dan tools sekaligus. Jika model gagal, cek halaman model OpenRouter dan ganti `OPENROUTER_MODEL`.

## Struktur file

```text
.
├── dn_bot/            # Package utama (python -m dn_bot)
│   ├── __init__.py    # Re-export API publik
│   ├── __main__.py    # Entrypoint CLI (argparse; --instruction / DN_INSTRUCTION / --dry-run)
│   ├── config.py      # Konstanta, eksespsi, parsing env, preflight
│   ├── safety.py      # Emergency stop, cek fokus, sanitasi log, sleep responsif
│   ├── capture.py     # Screenshot, letterbox, pemetaan koordinat
│   ├── messages.py    # Kontrak wire-shape pesan OpenAI-compatible
│   ├── device.py      # Seam input device (protocol + adapter pydirectinput + DryRunDevice)
│   ├── farm.py        # Profil Minotaur, state machine, dan watchdog progres
│   ├── input_control.py # Aksi fisik tervalidasi (via device seam)
│   ├── api.py         # Klien OpenRouter, retry, kontrak tool, SYSTEM_PROMPT
│   └── orchestrator.py # Loop sesi (run_dn_bot), kompaksi konteks
├── tests/             # Suite offline (pytest)
│   ├── conftest.py    # Fixtures + RecordingDevice (recorder input in-memory)
│   ├── test_dn_bot.py
│   └── test_integration.py # Tes integration end-to-end loop (plan 016)
├── .github/workflows/ # CI: compileall + pytest (actions di-pin SHA penuh)
│   └── tests.yml
├── plans/             # Inventaris temuan & rencana implementasi (001–017 + README)
├── requirements.txt   # Dependency runtime Python (pin eksak = lock)
├── requirements-dev.txt # Dependency development + runtime untuk tes offline (pytest di atas -r requirements.txt)
├── pyproject.toml      # Packaging setuptools: metadata, mirror deps requirements.txt, console script `dn-bot`
├── pytest.ini         # Konfigurasi pytest (testpaths, pythonpath)
├── CHANGELOG.md       # Riwayat perubahan (Keep a Changelog)
├── SECURITY.md        # Threat model, asumsi trust boundary, mitigasi, status temuan
├── AGENTS.md          # Konvensi proyek untuk agen coding
├── security_best_practices_report.md # Laporan audit keamanan awal (referensi read-only)
├── .env.example       # Template konfigurasi; tidak berisi secret
├── .gitignore         # Mengecualikan .env, virtualenv, dan cache
└── README.md
```

## Tes lokal

Aktifkan virtual environment terlebih dahulu, lalu gunakan `requirements-dev.txt` agar dependency test tercatat dan tetap terpisah dari dependency runtime:

```bat
python -m pip install -r requirements-dev.txt
python -m compileall -q dn_bot tests
python -m pytest -q tests
```

Konfigurasi pytest ada di `pytest.ini` (`testpaths = tests`, `pythonpath = .`), jadi `python -m pytest` (tanpa argumen) juga menjalankan seluruh suite dari root proyek.

Tes ini offline: tidak membuka Dragon Nest, tidak menggerakkan mouse, dan tidak memanggil OpenRouter. GitHub Actions menjalankan compile check dan perintah pytest yang sama pada setiap push dan pull request.

## Troubleshooting

### API key tidak ditemukan

Pastikan file bernama `.env` berada di folder proyek (satu tingkat di atas paket `dn_bot/`), dan berisi `OPENROUTER_API_KEY` yang valid.

### Model tidak tersedia atau tool call gagal

Atur `OPENROUTER_MODEL` ke model **gratis** yang saat ini mencantumkan kemampuan vision dan tool/function calling di katalog OpenRouter. Model gratis dapat berubah, kehabisan kapasitas, terkena rate limit, atau tidak mendukung kombinasi kemampuan tersebut.

Error transien seperti rate limit (429), gangguan server (5xx), atau masalah koneksi dicoba ulang otomatis (maksimal 3 percobaan, yaitu 2 retry) dengan backoff sebelum sesi berhenti. Error konfigurasi — API key salah (401/403), model tidak ditemukan (404), atau request ditolak (400/422) — langsung menghentikan sesi dengan pesan penyebab yang spesifik; perbaiki `.env` lalu jalankan ulang.

### Input tidak masuk ke game

- Pastikan window game benar-benar fokus dan judulnya cocok dengan `DN_WINDOW_TITLE`.
- Uji hanya pada menu atau lingkungan yang aman dan diizinkan.
- Coba windowed mode dan resolusi yang stabil.
- Perlu diketahui bahwa `pydirectinput` tidak otomatis mengatasi proteksi game, hak akses, atau kompatibilitas client.

### Screenshot hitam atau salah monitor

Pastikan game tampil pada region yang dikonfigurasi. Atur `DN_MONITOR` (indeks MSS mulai dari 1) atau empat variabel `DN_CAPTURE_*` untuk region window game.

### Sesi berhenti sendiri

Itu dapat terjadi karena failsafe, `Ctrl+C`, jendela kehilangan fokus, error OpenRouter, input tidak valid, rate limit, atau batas 10 langkah. Periksa log terminal dan jangan menonaktifkan failsafe.

## Batasan dan risiko

- AI cloud tidak cukup cepat untuk gameplay aksi real-time.
- Computer vision dapat salah mengenali objek atau UI; selalu awasi prosesnya.
- Teks dalam game bisa berisi konten adversarial; agent diperintahkan memperlakukannya sebagai data tidak tepercaya, tetapi kepatuhan model terhadap instruksi tersebut tidak dijamin.
- OpenRouter free models memiliki rate limit dan kapasitas yang dapat berubah.
- API key dan beberapa model dapat menimbulkan biaya; pastikan model yang dipilih benar-benar bertanda `:free`.
- Input otomatis dapat memicu aturan anti-cheat walaupun script tidak mencoba menghindarinya.
- Publisher dapat mengubah client, keybind, UI, atau kebijakan kapan saja.
- Tidak ada jaminan script berjalan pada semua versi/region Dragon Nest.

Threat model, asumsi trust boundary, mitigasi yang ada, dan status temuan keamanan didokumentasikan di [`SECURITY.md`](SECURITY.md).

Proyek ini tidak bertanggung jawab atas banned account, kehilangan progress, biaya API, kerusakan perangkat lunak, atau pelanggaran Terms of Service. Hentikan penggunaan jika publisher melarangnya.
