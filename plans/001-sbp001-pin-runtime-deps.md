# Plan 001 — SBP-001/F-03: pin dependensi runtime eksak (verify)

- **Temuan:** Dependensi runtime tidak di-pin (`openai>=1.40.0`, dll), tanpa lock file → supply-chain / build tidak reproducible. Medium.
- **Status:** ✅ Fixed — **Verified (reconcile 2026-08-06)**: 5 pin `==`, tanpa `>=`/`~=`/`<`; `pip freeze` cocok persis kelima pin.

## Konteks

`requirements.txt` memakai **pin eksak** (`==`) sebagai lock sederhana untuk 5 dependensi runtime; `requirements-dev.txt` menambah `pytest==8.3.5` di atas `-r requirements.txt`. Strategi lock/constraints didokumentasikan di README ("Dependensi & lock").

## Keadaan saat ini (bukti)

- `requirements.txt`:
  ```text
  openai==2.53.0
  pydirectinput==1.0.4
  mss==10.2.0
  pillow==12.3.0
  python-dotenv==1.2.2
  ```
- `requirements-dev.txt`: `-r requirements.txt` + `pytest==8.3.5`.
- README section "Dependensi & lock": aturan pemeliharaan + alasan sengaja tanpa lockfile + kapan beralih ke `constraints.txt`.

## Langkah verifikasi

1. `grep -c "==" requirements.txt` → 5; pastikan tidak ada `>=`/`~=` tersisa: `grep -nE ">=|~=" requirements.txt` → kosong.
2. `pip freeze` di venv aktif → kelima versi persis cocok dengan pin.
3. Jalankan `python -m pytest -q` → seluruh suite lolos (target 117; ekspektasi "60"/"72" di plan ini basi — suite tumbuh via 016 + unit recorder + survey T1–T7).
4. Baca README "Dependensi & lock" — tetap akurat terhadap file aktual.

## Verifikasi (machine-checkable)

```bash
grep -cE "^[a-zA-Z_-]+==[0-9]" requirements.txt   # expect 5
grep -nE ">=|~=|<" requirements.txt               # expect no output
.venv/Scripts/python -m pytest -q                 # expect 117 passed (kini; reconcile 2026-08-06)
```

## Batas scope

- IN: `requirements.txt`, `requirements-dev.txt`, README section "Dependensi & lock".
- OUT: membuat `constraints.txt` (itu opsional lanjutan — lihat AGENTS.md, bukan bagian dari fix ini).

## Rencana tes

Tidak ada tes baru (ini file dependensi, bukan kode). Regresi dijamin suite 117 tes yang berjalan di versi ter-pin.

## Catatan pemeliharaan

Jika dependensi bertambah > 5 atau CI memakai ekosistem berbeda, pertimbangkan `constraints.txt` dari `pip freeze` (langkah lanjutan terdokumentasi di README). Verifikasi fresh-venv (pip install dari scratch) adalah uji nyata pin — rencana user di AGENTS.md.
