# Plan 008 — F-07: upgrade versi actions CI (implement)

- **Temuan:** Pin SHA/patch lama tidak menerima backport keamanan otomatis; `checkout` v4.2.1 dan `setup-python` v5.6.0 ketinggalan. Low (tidak mendesak — trigger tanpa `pull_request_target` tidak terpapar kelas pwn-request).
- **Status:** ✅ **Fixed** (2026-08-06). Upgrade selesai: `checkout` v7.0.1 (`3d3c42e5aac5ba805825da76410c181273ba90b1`), `setup-python` v7.0.0 (`5fda3b95a4ea91299a34e894583c3862153e4b97`); actionlint + yaml-lint exit 0, 62 tes lokal lolos. Verifikasi final: run CI GitHub.

## Konteks

Enforcement keamanan pwn-request checkout (github.blog, 2026-06-18) masuk v4.4.0+ (jalur v4) / v5.1.0+ / v6.1.0+ / v7.0.1; pin `eef6144…` (v4.2.1) tidak menerimanya. Jalur v4 kini membawa backport BREAKING (`allow-unsafe-pr-checkout` default) — target yang lebih bersih adalah major terbaru: `checkout` v7.0.1, `setup-python` v7.0.0 (rilis 20 Jul 2026).

## Keadaan saat ini (bukti)

- `.github/workflows/tests.yml:15` — `uses: actions/checkout@eef61447b9ff4aafe5dcd4e0bbf5d482be7e7871 # v4.2.1`
- `.github/workflows/tests.yml:17` — `uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0`
- Trigger `on: push` + `pull_request` (tanpa `pull_request_target`) → kelas pwn-request tidak eksploitabel untuk repo ini; upgrade adalah hygiene, bukan patch aktif.

## Langkah

1. Resolve SHA penuh dari remote untuk versi target (jangan pernah pin tag bergerak):
   ```bash
   git ls-remote https://github.com/actions/checkout.git refs/tags/v7.0.1
   git ls-remote https://github.com/actions/setup-python.git refs/tags/v7.0.0
   ```
   Catat kedua SHA 40-hex.
2. Update `.github/workflows/tests.yml` (pertahankan komentar versi):
   ```yaml
   uses: actions/checkout@<SHA-v7.0.1> # v7.0.1
   uses: actions/setup-python@<SHA-v7.0.0> # v7.0.0
   ```
3. Jangan mengubah `python-version: "3.12"` atau langkah lain.

## Verifikasi (machine-checkable)

```bash
go run github.com/rhysd/actionlint/cmd/actionlint@latest .github/workflows/tests.yml   # exit 0 ✓ (terverifikasi)
npx -y yaml-lint .github/workflows/tests.yml                                            # lint successful ✓ (terverifikasi)
git ls-remote https://github.com/actions/checkout.git refs/tags/v7.0.1 | grep <SHA-pin> # cocok ✓
.venv/Scripts/python -m pytest -q                                                       # 62 passed ✓
```
Run CI di GitHub adalah verifikasi final (major bump tak terverifikasi lokal).

## Batas scope

- IN: `.github/workflows/tests.yml` (2 baris `uses:`).
- OUT: perubahan Python version, trigger, steps lain.
- OUT: downgrade ke jalur v4 — direkomendasikan lompat ke v7 karena jalur v4 membawa backport BREAKING.

## Rencana tes

Suite 62 tes tidak berubah; verifikasi di CI. Jika major bump v7 mengubah perilaku setup-python (mis. cache default), amati run CI pertama.

## Catatan pemeliharaan

Jika actions ditambahkan di masa depan, pin SHA penuh + komentar versi (konvensi F-04). Track freshness secara berkala — F-07 ditutup setelah upgrade, ID temuan berikutnya F-08+.

## Update dokumen

Selesai: pindahkan F-07 di SECURITY.md ke ✅ Fixed (dengan SHA baru), update ringkasan eksekutif (0 Low terbuka), tambah item mitigasi, dan baris CHANGELOG.md.
