# Setup Jitbit Macro Recorder — Dragon Nest Minotaur Farm

Panduan singkat setup **Jitbit Macro Recorder** untuk farming Minotaur Nest.
**Offline, tanpa API key, tanpa rate limit.**

---

## 1. Install Jitbit

1. Download dari: https://www.jitbit.com/macro-recorder/
2. Install (versi gratis cukup)
3. Buka aplikasi

---

## 2. Setup Game

1. Buka Dragon Nest
2. **Settings (O) → Screen → Screen Mode: Borderless Window**
3. Resolusi: **1024×768**
4. Pastikan window title = `Insane Dragon Nest DX11`

---

## 3. Import Macro

1. Di Jitbit, klik **File → Open**
2. Pilih file `.mcr` dari folder ini:

| File | Fungsi |
|---|---|
| `minotaur-01-enter.mcr` | Town → portal → Enter → loading dungeon |
| `minotaur-02-combat-saint.mcr` | Rotasi skill Saint (loop sampai distop manual) |
| `minotaur-03-loot-exit.mcr` | Loot peti → keluar dungeon → kembali town |
| `minotaur-full-farm.mcr` | **Full loop** — gabungan ketiganya, repeat forever |

---

## 4. Cara Pakai (3 Macro Terpisah — Paling Aman)

### Step 1: Masuk dungeon
1. Posisikan karakter di town dekat portal Minotaur
2. Klik kanan `minotaur-01-enter.mcr` → **Play**
3. Tunggu ~15 detik sampai masuk dungeon

### Step 2: Combat
1. Klik kanan `minotaur-02-combat-saint.mcr` → **Play**
2. Macro akan spam skill + gerak otomatis
3. **Awasi boss HP** — begitu boss mati, tekan **Ctrl+Shift+F10** untuk stop

### Step 3: Loot & Keluar
1. Klik kanan `minotaur-03-loot-exit.mcr` → **Play**
2. Karakter akan jalan ke peti → loot → keluar dungeon → loading town
3. Ulangi dari Step 1

---

## 5. Cara Pakai (1 Macro Full Auto)

> ⚠️ Macro ini pakai timing combat FIXED (~2 menit). Kalau gear kamu lebih cepat/lambat, combat bisa kepotong atau kebuang waktunya.

1. Posisikan karakter di town dekat portal Minotaur
2. Klik kanan `minotaur-full-farm.mcr` → **Play**
3. Macro akan: masuk → combat 2 menit → loot → keluar → town → LOOP
4. Untuk berhenti: **Ctrl+Shift+F10**

**Untuk menyesuaikan durasi combat:**
- Buka macro di Jitbit editor
- Cari comment `<!-- FASE 2: COMBAT -->`
- **Kurangi blok** (hapus 5-10 blok) kalau combat terlalu lama setelah boss mati
- **Duplikasi blok** (copy-paste 5-10 blok lagi) kalau combat kurang lama

---

## 6. Menyesuaikan Skill Slot

Skill slot di macro ini menggunakan **D1-D5** (keyboard 1-5). Sesuaikan dengan skillbar kamu:

| Slot | Default | Skill Kamu (ganti di sini) |
|---|---|---|
| `D1` | Skill damage utama | `_______` |
| `D2` | Skill damage kedua | `_______` |
| `D3` | Grand Cross / AoE | `_______` |
| `D4` | Heal / Support | `_______` |
| `D5` | Buff / Aura | `_______` |

Untuk mengganti di Jitbit:
1. Klik kanan macro → **Edit**
2. Cari `<Key>D1</Key>` → ganti `D1` dengan tombol skill kamu
3. Atau: **rekam ulang** combat section dengan skill kamu

---

## 7. Emergency Stop

| Cara | Kapan |
|---|---|
| **Ctrl+Shift+F10** | Stop macro kapan saja |
| **Alt+Tab** keluar game | Kalau macro stuck dan hotkey tidak respon |
| Gerakkan mouse ke pojok | Tidak berfungsi di Jitbit — pakai hotkey |

---

## 8. Tips

- **Tes 1 loop dulu** sebelum farming lama
- **Jangan alt-tab** saat macro jalan
- **Restart macro setiap 30 menit** untuk mencegah drift
- Kalau klik meleset: cek resolusi game = 1024×768 dan window mode = Borderless
- Kalau loading lebih lama dari jeda: tambah `Delay` di editor (klik kanan → Insert Delay)

---

## 9. Koordinat Kunci (1024×768)

| Elemen | Koordinat | File Macro |
|---|---|---|
| Portal nest | `[512, 380]` | `01-enter` |
| Tombol Enter (dialog) | `[729, 493]` | `01-enter` |
| Tombol keluar (exit) | `[512, 700]` | `03-loot-exit` |

Kalau koordinat tidak tepat, jalankan `python find_macro_coords.py` untuk mencari ulang.

---

## 10. Troubleshooting

| Masalah | Solusi |
|---|---|
| Macro tidak main di game | Pastikan game **Borderless Window**, bukan Fullscreen |
| Klik meleset | Cek resolusi game = 1024×768. Kalau beda, cari koordinat baru |
| Combat kepotong | Tambah blok combat di macro editor |
| Boss sudah mati tapi macro masih combat | Tekan **Ctrl+Shift+F10**, lanjut manual ke loot |
| Skill tidak keluar | Cek skill slot sesuai dengan keyboard 1-5 di game |
| Macro drift setelah lama | Restart macro tiap 30 menit |
