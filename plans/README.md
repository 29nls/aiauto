# Plans — Inventaris temuan terverifikasi

Semua **12 temuan terverifikasi** dari sesi ini, masing-masing dengan satu plan yang self-contained (dapat dieksekusi oleh agent tanpa konteks sesi). Setiap plan berisi keadaan aktual (dengan `file:line`), langkah, verifikasi machine-checkable, batas scope, dan rencana tes.

Stempel commit dasar: `91bf7e4` (HEAD saat inventaris ditulis, 2026-08-06). Verifikasi drift: sebelum mengeksekusi plan apa pun, cek bahwa kode masih cocok dengan kutipan di plan; jika tidak, STOP dan laporkan.

## Status table

| # | Temuan | ID asal | Severity | Status | Plan |
|---|--------|---------|----------|--------|------|
| 001 | Dependensi runtime tidak di-pin, tanpa lock | SBP-001 / F-03 | Medium | ✅ Fixed (worktree) | [001-sbp001-pin-runtime-deps.md](001-sbp001-pin-runtime-deps.md) — verify |
| 002 | CI actions di-pin ke tag bergerak, tanpa least-privilege | SBP-002 / F-04 | Medium | ✅ Fixed (worktree) | [002-sbp002-pin-ci-actions.md](002-sbp002-pin-ci-actions.md) — verify |
| 003 | Cek fokus window fail-open di non-Windows | SBP-003 / F-02 | Medium | ✅ Fixed (fail-closed penuh) | [003-sbp003-fail-closed-non-windows.md](003-sbp003-fail-closed-non-windows.md) — verify |
| 004 | Parsing env tanpa pesan error yang actionable | SBP-004 | Low | ✅ Fixed | [004-sbp004-env-parse-messages.md](004-sbp004-env-parse-messages.md) — verify |
| 005 | Potensi log injection via judul window | SBP-005 / F-05 | Low | ✅ Fixed | [005-sbp005-log-sanitization.md](005-sbp005-log-sanitization.md) — verify |
| 006 | Detail error API dicantumkan verbatim ke log | SBP-006 / F-06 | Low | ✅ Fixed | [006-f06-limit-api-error-detail.md](006-f06-limit-api-error-detail.md) — verify |
| 007 | Indirect prompt injection via teks screenshot | F-01 (VERIFY-001) | Medium (potensi High saat live) | ✅ Mitigated (verifikasi live belum) | [007-f01-prompt-injection-live-verification.md](007-f01-prompt-injection-live-verification.md) — runbook |
| 008 | Versi actions CI ketinggalan (pin SHA tidak menerima backport) | F-07 | Low | 🔴 Open | [008-f07-upgrade-ci-actions.md](008-f07-upgrade-ci-actions.md) — **implement** |
| 009 | Kandidat #1: global capture state → Frame module | — | — | ✅ Done | [009-arch1-frame-module.md](009-arch1-frame-module.md) — verify |
| 010 | Kandidat #2: adapter OpenRouter hasil model polos | — | — | ⬜ Pending | [010-arch2-openrouter-plain-adapter.md](010-arch2-openrouter-plain-adapter.md) — **implement** |
| 011 | Kandidat #3: satu module kontrak wire-shape pesan | — | — | ⬜ Pending | [011-arch3-message-contract-module.md](011-arch3-message-contract-module.md) — **implement** |
| 012 | Kandidat #4: seam input device nyata | — | — | ⬜ Pending | [012-arch4-input-device-seam.md](012-arch4-input-device-seam.md) — **implement** |

## Urutan eksekusi yang direkomendasikan

1. **008 (F-07)** — satu-satunya item keamanan terbuka tersisa; biaya kecil, nilai langsung. (006/F-06 selesai 2026-08-06.)
2. **011 (kontrak wire-shape)** → **010 (adapter OpenRouter)** → **012 (seam input)** — kandidat arsitektur. 011 dan 010 berbagi boundary api.py; kerjakan 011 dulu agar adapter mengembalikan tipe kontrak, lalu 012 (orthogonal, menyentuh input_control.py + tes).
3. **001–005 dan 009 (verify)** — verifikasi cepat bahwa mitigasi/fix masih berdiri + tes menjaganya; dapat di-batch dan dijalankan ulang sebelum commit besar.
4. **007 (F-01 live)** — **butuh lingkungan eksternal** (game Dragon Nest + API key OpenRouter + model vision/tools); BLOCKED sampai user menyediakannya.

## Catatan inventaris

- **Deduplikasi:** SBP-006 = F-06 (dihitung sekali, plan 006). Mapping SBP → F: SBP-001→F-03, SBP-002→F-04, SBP-003→F-02, SBP-004 (fixed via `_int_env`, tidak punya ID F), SBP-005→F-05, SBP-006→F-06. F-01 dan F-07 adalah temuan tambahan di SECURITY.md yang tidak punya pasangan SBP.
- **Overrides (bukan temuan):** OVR-01 (retry `time.sleep` polos — keputusan desain, komentar ditambahkan di kode) dan OVR-02 (fail-open non-Windows) sudah superseded oleh F-02. Tidak dibuatkan plan.
- **Fresh-venv & commit** tercatat sebagai follow-up operasional di AGENTS.md, bukan temuan — tidak dibuatkan plan.

## Batch 2 — Top-5 temuan audit improve (plan 013–017)

Dari audit improve yang dianalisis pada commit `89b6c5a` (era `app_dn.py`; sebelum restrukturisasi dan sebelum sebagian besar hardening masuk). Daftar temuan audit: #1 prompt injection, #2 fail-open non-Windows, #3 Device port, #4 tes integration, #7 hardening CI (top-5 yang dipilih; #5/#6 tidak diplan-kan). Seluruh plan stamped `89b6c5a`; path mengikuti kode **saat ini** (`dn_bot/`) karena restrukturisasi terjadi setelah stamp — drift check di tiap plan sudah menyesuaikan.

### Status table (013–017)

| Plan | Temuan audit | Prioritas | Depends on | Status |
|------|--------------|-----------|------------|--------|
| [013-improve1-prompt-injection.md](013-improve1-prompt-injection.md) | #1 Indirect prompt injection via screenshot | P1 | — | TODO (mitigasi ada; verifikasi live pending) |
| [014-improve2-fail-open-non-windows.md](014-improve2-fail-open-non-windows.md) | #2 Cek fokus fail-open di non-Windows | P1 | — | TODO (sudah fail-closed; verifikasi) |
| [015-improve3-device-port.md](015-improve3-device-port.md) | #3 Device port — coupling langsung ke pydirectinput | P2 | — | TODO (implement) |
| [016-improve4-integration-tests.md](016-improve4-integration-tests.md) | #4 Tes integration loop end-to-end | P2 | 015 (recorder device membuatnya natural; boleh paralel) | TODO (implement) |
| [017-improve7-hardening-ci.md](017-improve7-hardening-ci.md) | #7 Hardening workflow CI | P1 | — | TODO (dasar fixed; upgrade freshness tersisa) |

### Dependency order

1. **013**, **014**, **017** — verifikasi/penyelesaian keamanan, independen, biaya kecil. Kerjakan duluan (P1).
2. **015** (device port) → **016** (integration tests): recorder device dari 015 membuat tes integration lebih natural (assert urutan input nyata); 016 boleh mulai paralel memakai patch yang ada.
3. **016** adalah jaring pengaman untuk refactor arsitektur lain (010/011/015) — idealnya sebelum refactor besar berikutnya.

### Rekonsiliasi dengan inventaris 001–012

Temuan audit improve ini **tumpang tindih** dengan inventaris 12-temuan (yang mencatat status saat ini). Agar tidak ada duplikasi eksekusi:

- **013 ≈ 007** (F-01 prompt injection) — keduanya verifikasi live; eksekusi 013 sebagai yang mengikuti template skill, tandai 007 REJECTED/superseded.
- **014 ≈ 003** (F-02 fail-open non-Windows) — 014 mengikuti template skill; tandai 003 REJECTED/superseded setelah 014 dieksekusi.
- **015 ≈ 012** (arch #4 input device seam) — temuan yang sama; eksekusi 015, tandai 012 REJECTED/superseded.
- **017 ≈ 002 + 008** (F-04 pin SHA + F-07 freshness) — 017 menggabungkan keduanya; eksekusi 017, tandai 002 dan 008 REJECTED/superseded.
- **016 (integration tests)** — temuan baru, tidak ada padanan di inventaris 001–012.
- Plan 001/004/005/006/009/010/011 di inventaris 12-temuan **tidak tersentuh** oleh batch ini.

## Kolom status

Plan verify/implement yang sudah dieksekusi: ubah kolom Status di tabel ini dan tandai checklist plan. Jangan hapus plan yang sudah selesai — pindahkan ke bawah tabel sebagai "Selesai" atau tandai `[x]`.
