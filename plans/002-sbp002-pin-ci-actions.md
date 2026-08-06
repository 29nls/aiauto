# Plan 002 — SBP-002/F-04: pin actions CI ke SHA penuh + least-privilege (verify)

- **Temuan:** `actions/checkout@v4`, `actions/setup-python@v5` (tag bergerak), tanpa blok `permissions:` → supply-chain (tag mutation) + token berjalan dengan permission default. Medium.
- **Status:** ✅ Fixed di worktree (belum di-commit). Plan ini = verifikasi.

## Konteks

Workflow satu-satunya (`.github/workflows/tests.yml`) memakai SHA penuh untuk kedua actions dengan komentar versi, dan `permissions: contents: read` di root. SHA sudah diverifikasi ulang dari remote (2026-08-06).

## Keadaan saat ini (bukti)

- `uses:` baris 15 dan 17:
  - `actions/checkout@eef61447b9ff4aafe5dcd4e0bbf5d482be7e7871 # v4.2.1`
  - `actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0`
- `permissions: contents: read` di root (sebelum `jobs:`).
- Trigger hanya `push` / `pull_request` (tanpa `pull_request_target`).

## Langkah verifikasi

1. Resolve ulang SHA dari remote dan bandingkan dengan pin:
   ```bash
   git ls-remote https://github.com/actions/checkout.git refs/tags/v4.2.1
   git ls-remote https://github.com/actions/setup-python.git refs/tags/v5.6.0
   ```
2. Validasi sintaks + schema Actions dengan dua validator independen (PyYAML tidak ada di venv):
   ```bash
   go run github.com/rhysd/actionlint/cmd/actionlint@latest .github/workflows/tests.yml   # exit 0, no findings
   npx -y yaml-lint .github/workflows/tests.yml                                           # "YAML Lint successful"
   ```
3. Pastikan panjang SHA = 40 hex: `grep -oE "@[0-9a-f]{40}" .github/workflows/tests.yml`.

## Verifikasi (machine-checkable)

Output `git ls-remote` sama persis dengan SHA yang di-pin; actionlint exit 0 tanpa temuan; `grep -oE "@[0-9a-f]{40}"` menghasilkan 2 baris @ 40-hex.

## Batas scope

- IN: `.github/workflows/tests.yml` (pin + permissions).
- OUT: **upgrade versi actions** — itu F-07 (plan 008), item freshness terpisah.

## Rencana tes

Suite 60 tes berjalan di CI sebagai verifikasi nyata; run lokal `python -m pytest -q` untuk regresi cepat.

## Catatan pemeliharaan

Pin SHA menutup tag-mutation, tetapi **tidak** otomatis menerima backport keamanan — track freshness di F-07 (plan 008).
