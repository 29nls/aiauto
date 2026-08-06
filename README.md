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
python -m pytest -q test_app_dn.py
```

Edit `.env` secara lokal:

```dotenv
OPENROUTER_API_KEY=sk-or-v1-isi-api-key-di-sini
# Isi dengan model gratis yang saat ini tersedia di OpenRouter dan mendukung vision + tools.
OPENROUTER_MODEL=isi-model-free-yang-mendukung-vision-dan-tools
DN_WINDOW_TITLE=Dragon Nest
```

Jangan commit `.env`, karena berisi secret API. Jangan menaruh API key di source code.

## Menjalankan

1. Pastikan penggunaan bot/otomasi diizinkan oleh publisher Dragon Nest.
2. Jalankan game dalam **windowed mode**.
3. Pastikan karakter berada di tempat yang aman dan tujuan eksperimen jelas.
4. Aktifkan virtual environment.
5. Jalankan:

```bat
python app_dn.py
```

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
- `openai` Python SDK diarahkan ke `https://openrouter.ai/api/v1`.
- Model hanya dapat memanggil function `dragon_nest_action` dengan action yang di-allowlist.
- Tombol, koordinat, dan durasi divalidasi sebelum input dikirim.
- `move_camera` memakai endpoint absolut yang divalidasi, lalu menggerakkan cursor dari anchor tengah ke endpoint tersebut; posisi cursor sebelumnya tidak memengaruhi hasil dan aksi berulang tidak mengakumulasi drift.
- Setelah aksi, screenshot baru dikirim sebagai pesan user berikutnya dan menggantikan frame lama sebagai sumber visual yang authoritative.
- Riwayat request dibatasi agar context tidak terus membesar; instruction awal, tool-call/result terbaru yang masih diperlukan, dan screenshot terkini dipertahankan.
- Satu siklus observasi menjalankan paling banyak satu aksi fisik.
- Sesi dibatasi maksimal 10 langkah.

Function yang tersedia:

- `mouse_move`
- `left_click`
- `right_click`
- `press_move_key` untuk `w/a/s/d/q/e`
- `press_action_key` untuk tombol terbatas seperti `f`, `space`, `0-9`, atau `shift`
- `move_camera` untuk mengarahkan camera ke endpoint absolut di content game; cursor di-anchor ke titik tengah screenshot pada setiap aksi
- `wait`

Ini memakai function calling OpenAI-compatible melalui OpenRouter, bukan native computer-use API. Tidak semua model gratis mendukung vision dan tools sekaligus. Jika model gagal, cek halaman model OpenRouter dan ganti `OPENROUTER_MODEL`.

## Struktur file

```text
.
├── app_dn.py          # Agent loop, capture, validasi, dan input
├── test_app_dn.py     # Tes parsing tool call
├── requirements.txt   # Dependency runtime Python
├── requirements-dev.txt # Dependency development + runtime untuk tes offline
├── .env.example       # Template konfigurasi; tidak berisi secret
├── .gitignore         # Mengecualikan .env, virtualenv, dan cache
└── README.md
```

## Tes lokal

Aktifkan virtual environment terlebih dahulu, lalu gunakan `requirements-dev.txt` agar dependency test tercatat dan tetap terpisah dari dependency runtime:

```bat
python -m pip install -r requirements-dev.txt
python -m py_compile app_dn.py test_app_dn.py
python -m pytest -q test_app_dn.py
```

Tes ini offline: tidak membuka Dragon Nest, tidak menggerakkan mouse, dan tidak memanggil OpenRouter. GitHub Actions menjalankan compile check dan perintah pytest yang sama pada setiap push dan pull request.

## Troubleshooting

### API key tidak ditemukan

Pastikan file bernama `.env` berada di folder yang sama dengan `app_dn.py`, dan berisi `OPENROUTER_API_KEY` yang valid.

### Model tidak tersedia atau tool call gagal

Atur `OPENROUTER_MODEL` ke model **gratis** yang saat ini mencantumkan kemampuan vision dan tool/function calling di katalog OpenRouter. Model gratis dapat berubah, kehabisan kapasitas, terkena rate limit, atau tidak mendukung kombinasi kemampuan tersebut.

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
- OpenRouter free models memiliki rate limit dan kapasitas yang dapat berubah.
- API key dan beberapa model dapat menimbulkan biaya; pastikan model yang dipilih benar-benar bertanda `:free`.
- Input otomatis dapat memicu aturan anti-cheat walaupun script tidak mencoba menghindarinya.
- Publisher dapat mengubah client, keybind, UI, atau kebijakan kapan saja.
- Tidak ada jaminan script berjalan pada semua versi/region Dragon Nest.

Proyek ini tidak bertanggung jawab atas banned account, kehilangan progress, biaya API, kerusakan perangkat lunak, atau pelanggaran Terms of Service. Hentikan penggunaan jika publisher melarangnya.
