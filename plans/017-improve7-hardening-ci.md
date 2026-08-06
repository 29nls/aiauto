# Plan 017: Hardening workflow CI (pin SHA + least-privilege + freshness)

> **Executor instructions**: Follow this plan step by step. Run every
> verification command and confirm the expected result before moving to the
> next step. If anything in the "STOP conditions" section occurs, stop and
> report — do not improvise. When done, update the status row for this plan
> in `plans/README.md` — unless a reviewer dispatched you and told you they
> maintain the index.
>
> **Drift check (run first)**: Repo ini direstrukturisasi dari `app_dn.py`
> menjadi package `dn_bot/` SETELAH stamp plan ini (audit improve pada commit
> `89b6c5a` menemukan `actions/checkout@v4`/`actions/setup-python@v5` tanpa
> `permissions:`). Bandingkan kutipan "Current state" dengan
> `.github/workflows/tests.yml` live; jika tidak cocok → STOP.

## Status

- **Priority**: P1
- **Effort**: S
- **Risk**: LOW
- **Depends on**: none
- **Category**: security
- **Planned at**: commit `89b6c5a`, 2026-08-06 (audit improve; workflow saat itu `actions/checkout@v4` + `@v5`, tanpa `permissions:`)
- **Issue**: omit
- **Executed**: 2026-08-06 — freshness upgrade selesai: `checkout` v4.2.1 → v7.0.1 (`3d3c42e5aac5ba805825da76410c181273ba90b1`), `setup-python` v5.6.0 → v7.0.0 (`5fda3b95a4ea91299a34e894583c3862153e4b97`); actionlint + yaml-lint exit 0; 62 tes lokal lolos saat itu (kini **117**); run CI GitHub final. Dilanjutkan oleh survey T5 (2026-08-06): matrix Python 3.10/3.12/3.14, `timeout-minutes: 10`, `pip check`, pip cache — pin SHA + least-privilege tetap.

## Why this matters

Tag mayor (`@v4`, `@v5`) adalah referensi yang bisa berubah (re-tag/minor baru)
— action yang dikompromikan bisa menginjeksi langkah berbahaya ke CI; token
workflow berjalan dengan permission default. Pin ke SHA penuh + `permissions:
contents: read` menutup kedua celah. Hardening dasar sudah ada dan ter-commit
(sesi SBP-002/F-04); tersisa **freshness**: pin SHA/patch lama tidak menerima
backport keamanan otomatis (enforcement pwn-request checkout 2026-06-18 masuk
v4.4.0+).

## Current state

- `.github/workflows/tests.yml`:
  - baris 15: `uses: actions/checkout@eef61447b9ff4aafe5dcd4e0bbf5d482be7e7871 # v4.2.1`
  - baris 17: `uses: actions/setup-python@a26af69be951a213d495a4c3e4e4022e16d87065 # v5.6.0`
  - `permissions: contents: read` di root (sebelum `jobs:`)
  - trigger `on: push` + `pull_request` (tanpa `pull_request_target` → kelas pwn-request tidak eksploitabel untuk repo ini)
- Terbaru di remote (diverifikasi 2026-08-06): `checkout` v7.0.1 (jalur v4 terbaru v4.4.0), `setup-python` v7.0.0.
- Validator: PyYAML tidak ada di venv — gunakan actionlint (`go run`) + `yaml-lint` (`npx`), keduanya terverifikasi exit 0.
- Konvensi: actions baru harus di-pin SHA penuh + komentar versi (SECURITY.md F-04).

## Commands you will need

| Purpose   | Command                  | Expected on success |
|-----------|--------------------------|---------------------|
| Resolve SHA | `git ls-remote https://github.com/actions/checkout.git refs/tags/v7.0.1` | SHA 40-hex |
| Resolve SHA | `git ls-remote https://github.com/actions/setup-python.git refs/tags/v7.0.0` | SHA 40-hex |
| YAML lint  | `go run github.com/rhysd/actionlint/cmd/actionlint@latest .github/workflows/tests.yml` | exit 0, no findings |
| YAML lint  | `npx -y yaml-lint .github/workflows/tests.yml` | "YAML Lint successful" |
| Tests      | `.venv/Scripts/python -m pytest -q` | 117 passed (kini) |

## Scope

**In scope**:
- `.github/workflows/tests.yml` (2 baris `uses:` — upgrade versi; `permissions` sudah ada)
- `SECURITY.md`, `CHANGELOG.md` (update status F-07/F-04 setelah selesai)

**Out of scope**:
- Perubahan `python-version`, trigger, steps lain.
- Menurunkan ke jalur v4 — target bersih adalah major terbaru (v7), karena jalur v4 membawa backport BREAKING.

## Git workflow

- Branch: `advisor/017-hardening-ci`
- Message style: conventional commits
- Do NOT push/open PR kecuali diinstruksikan.

## Steps

### Step 1: Verifikasi hardening dasar sudah berdiri

- `grep -n "permissions:" .github/workflows/tests.yml` → ada di root.
- `grep -oE "@[0-9a-f]{40}" .github/workflows/tests.yml` → 2 baris @ 40-hex.
- `git ls-remote` untuk v4.2.1/v5.6.0 → SHA persis sama dengan pin (bukti tidak drift).

**Verify**: semua grep sesuai.

### Step 2: Upgrade versi actions (freshness)

- `git ls-remote ... refs/tags/v7.0.1` dan `... refs/tags/v7.0.0` → catat SHA 40-hex.
- Update 2 baris `uses:` ke SHA baru dengan komentar versi (`# v7.0.1`, `# v7.0.0`).
- Jangan sentuh bagian lain.

**Verify**: actionlint exit 0; `yaml-lint` successful; `grep -oE "@[0-9a-f]{40}"` → 2 baris baru.

### Step 3: Update dokumen

- `SECURITY.md`: pindahkan F-07 dari 🔴 Terbuka ke ✅ Fixed (tulis SHA baru), update ringkasan eksekutif (0 Low terbuka), tambah item mitigasi.
- `CHANGELOG.md`: tambah baris di Unreleased.

**Verify**: grep F-07 di SECURITY.md → status Fixed.

## Test plan

- Suite 60 tes tidak berubah; run lokal + run CI GitHub adalah verifikasi final (major bump tak terverifikasi lokal).

## Done criteria

Machine-checkable. ALL must hold:

- [ ] `git ls-remote ... v7.0.1` / `v7.0.0` SHA persis cocok dengan pin baru
- [ ] actionlint exit 0 + `yaml-lint` successful
- [x] `.venv/Scripts/python -m pytest -q` → 117 passed (kini)
- [ ] F-07 di SECURITY.md berstatus ✅ Fixed
- [ ] `plans/README.md` status row 017 diupdate
- [ ] Tidak ada file di luar in-scope yang berubah

## STOP conditions

- Remote tag v7.0.1/v7.0.0 tidak ada atau SHA tidak 40-hex → stop, laporkan.
- Kode live `.github/workflows/tests.yml` tidak cocok dengan kutipan.
- Verifikasi gagal dua kali setelah upaya wajar.

## Maintenance notes

- Semua action baru wajib pin SHA penuh + komentar versi (konvensi F-04).
- Pin SHA immutable menutup tag-mutation tapi tidak menerima backport otomatis — track freshness berkala (setelah F-07 ditutup, temuan berikutnya F-08+).
- Rekonsiliasi: plan 002 (`sbp002-pin-ci-actions.md`) dan 008 (`f07-upgrade-ci-actions.md`) di inventaris 12-temuan mencakup temuan yang sama — eksekusi plan ini sebagai satu-satunya, tandai 008 REJECTED/superseded di README.
