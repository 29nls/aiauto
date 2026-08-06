# Plans — Inventaris temuan terverifikasi

Semua **12 temuan terverifikasi** dari sesi ini, masing-masing dengan satu plan yang self-contained (dapat dieksekusi oleh agent tanpa konteks sesi). Setiap plan berisi keadaan aktual (dengan `file:line`), langkah, verifikasi machine-checkable, batas scope, dan rencana tes.

Stempel commit dasar: `91bf7e4` (HEAD saat inventaris ditulis, 2026-08-06). Verifikasi drift: sebelum mengeksekusi plan apa pun, cek bahwa kode masih cocok dengan kutipan di plan; jika tidak, STOP dan laporkan.

## Status table

| # | Temuan | ID asal | Severity | Status | Plan |
|---|--------|---------|----------|--------|------|
| 001 | Dependensi runtime tidak di-pin, tanpa lock | SBP-001 / F-03 | Medium | ✅ Fixed | [001-sbp001-pin-runtime-deps.md](001-sbp001-pin-runtime-deps.md) — ✅ verified (2026-08-06) |
| 002 | CI actions di-pin ke tag bergerak, tanpa least-privilege | SBP-002 / F-04 | Medium | ✅ Fixed | [002-sbp002-pin-ci-actions.md](002-sbp002-pin-ci-actions.md) — ✅ verified (2026-08-06) |
| 003 | Cek fokus window fail-open di non-Windows | SBP-003 / F-02 | Medium | ✅ Fixed (fail-closed penuh) | [003-sbp003-fail-closed-non-windows.md](003-sbp003-fail-closed-non-windows.md) — ✅ verified (2026-08-06) |
| 004 | Parsing env tanpa pesan error yang actionable | SBP-004 | Low | ✅ Fixed | [004-sbp004-env-parse-messages.md](004-sbp004-env-parse-messages.md) — ✅ verified (2026-08-06) |
| 005 | Potensi log injection via judul window | SBP-005 / F-05 | Low | ✅ Fixed | [005-sbp005-log-sanitization.md](005-sbp005-log-sanitization.md) — ✅ verified (2026-08-06) |
| 006 | Detail error API dicantumkan verbatim ke log | SBP-006 / F-06 | Low | ✅ Fixed | [006-f06-limit-api-error-detail.md](006-f06-limit-api-error-detail.md) — ✅ verified (2026-08-06) |
| 007 | Indirect prompt injection via teks screenshot | F-01 (VERIFY-001) | Medium (potensi High saat live) | ✅ Mitigated (verifikasi live belum) | [007-f01-prompt-injection-live-verification.md](007-f01-prompt-injection-live-verification.md) — runbook |
| 008 | Versi actions CI ketinggalan (pin SHA tidak menerima backport) | F-07 | Low | ✅ Fixed | [008-f07-upgrade-ci-actions.md](008-f07-upgrade-ci-actions.md) — ✅ verified (2026-08-06) |
| 009 | Kandidat #1: global capture state → Frame module | — | — | ✅ Done | [009-arch1-frame-module.md](009-arch1-frame-module.md) — ✅ verified (2026-08-06) |
| 010 | Kandidat #2: adapter OpenRouter hasil model polos | — | — | ✅ Done | [010-arch2-openrouter-plain-adapter.md](010-arch2-openrouter-plain-adapter.md) — ✅ verified (2026-08-06) |
| 011 | Kandidat #3: satu module kontrak wire-shape pesan | — | — | ✅ Done | [011-arch3-message-contract-module.md](011-arch3-message-contract-module.md) — ✅ verified (2026-08-06) |
| 012 | Kandidat #4: seam input device nyata | — | — | ✅ Done (via 015) | [012-arch4-input-device-seam.md](012-arch4-input-device-seam.md) — ✅ verified (2026-08-06) |

## Urutan eksekusi yang direkomendasikan

1. **006 (F-06)** dan **008 (F-07)** — item keamanan inventaris 12-temuan kini **semuanya selesai** (fixed 2026-08-06).
2. **011 (kontrak wire-shape)** → **010 (adapter OpenRouter)** → **012/015 (seam input)** — SELESAI 2026-08-06 (010/011: 67 tes; 012/015: 71 tes saat itu; suite kini **88**). **Seluruh kandidat arsitektur (009–012) sudah tuntas & diverifikasi — retired.**
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
| [013-improve1-prompt-injection.md](013-improve1-prompt-injection.md) | #1 Indirect prompt injection via screenshot | P1 | — | ⛔ BLOCKED (butuh env eksternal: game + API key; guard offline terverifikasi 2 delimiter) |
| [014-improve2-fail-open-non-windows.md](014-improve2-fail-open-non-windows.md) | #2 Cek fokus fail-open di non-Windows | P1 | — | ✅ Verified via reconcile (2026-08-06 — fail-closed berdiri; temuan sama dengan plan 003) |
| [015-improve3-device-port.md](015-improve3-device-port.md) | #3 Device port — coupling langsung ke pydirectinput | P2 | — | DONE (2026-08-06, seam `device.py` + `RecordingDevice`; suite kini 88) |
| [016-improve4-integration-tests.md](016-improve4-integration-tests.md) | #4 Tes integration loop end-to-end | P2 | 015 (recorder device membuatnya natural; boleh paralel) | DONE (2026-08-06, 4 tes — item 3 aksi nyata via recorder dieksekusi setelah 015; suite kini 88) |
| [017-improve7-hardening-ci.md](017-improve7-hardening-ci.md) | #7 Hardening workflow CI | P1 | — | DONE (dasar + freshness: checkout v7.0.1, setup-python v7.0.0, 2026-08-06) |

### Dependency order

1. **013**, **014**, **017** — verifikasi/penyelesaian keamanan, independen, biaya kecil. Kerjakan duluan (P1).
2. **015** (device port) → **016** (integration tests): keduanya SELESAI (2026-08-06). 015 menambahkan seam `device.py` + `RecordingDevice`; 016 berdiri sebelum 015, tetap hijau setelahnya, dan item 3-nya (aksi nyata via recorder, assert urutan input fisik `move_camera`/`wait`) dieksekusi setelah 015. Suite kini **88**.
3. **016** adalah jaring pengaman untuk refactor arsitektur lain (010/011/015) — sudah berdiri sebelum refactor besar berikutnya.

### Rekonsiliasi dengan inventaris 001–012

Temuan audit improve ini **tumpang tindih** dengan inventaris 12-temuan (yang mencatat status saat ini). Agar tidak ada duplikasi eksekusi:

- **013 ≈ 007** (F-01 prompt injection) — keduanya verifikasi live; eksekusi 013 sebagai yang mengikuti template skill, tandai 007 REJECTED/superseded.
- **014 ≈ 003** (F-02 fail-open non-Windows) — 014 mengikuti template skill; tandai 003 REJECTED/superseded setelah 014 dieksekusi.
- **015 ≈ 012** (arch #4 input device seam) — temuan yang sama; 015 dieksekusi 2026-08-06 (suite 71), 012 ditandai **Done (via 015)**.
- **017 ≈ 002 + 008** (F-04 pin SHA + F-07 freshness) — 017 menggabungkan keduanya dan sudah dieksekusi (2026-08-06, upgrade v7.0.1/v7.0.0); 002 dan 008 ditandai Fixed (008), status 017 DONE.
- **016 (integration tests)** — temuan baru, tidak ada padanan di inventaris 001–012.
- Plan 001/004/005/006/009/010/011 di inventaris 12-temuan **tidak tersentuh** oleh batch ini.

## Kolom status

Plan verify/implement yang sudah dieksekusi: ubah kolom Status di tabel ini dan tandai checklist plan. Jangan hapus plan yang sudah selesai — pindahkan ke bawah tabel sebagai "Selesai" atau tandai `[x]`.

## Rekonsiliasi 2026-08-06 (reconcile plans/)

Verifikasi plan **Done/Fixed** terhadap kode live. Semua invarian machine-checkable **LOLOS**; suite penuh **83 passed**.

| Plan | Invarian yang diverifikasi | Hasil |
|------|----------------------------|-------|
| 001 | 5 pin `==` di requirements.txt, tanpa `>=`/`~=`/`<`; `pip freeze` cocok persis kelima pin (mss 10.2.0, openai 2.53.0, pillow 12.3.0, pydirectinput 1.0.4, python-dotenv 1.2.2) | ✅ |
| 002 | 2 `uses:` @ SHA 40-hex + `permissions: contents: read`; tanpa `pull_request_target`; actionlint exit 0; yaml-lint successful | ✅ |
| 003 | `os.name != "nt"` ×2 dengan `raise` (safety.py:48, config.py:136); `(EmergencyStop, FocusLost): raise` di orchestrator.py:166 | ✅ |
| 004 | 0 `int(os.getenv)` mentah (semua lewat `_int_env`); pesan per-variabel jelas | ✅ |
| 005 | sanitasi sebelum interpolasi (safety.py:67) + uji C1 manual (8-bit CSI `\x9b`/`\x1b` ter-strip) | ✅ |
| 009 | 0 global capture state (`_capture_region`/`_capture_geometry`), 0 `global`, 4 call site `_physical_point(..., frame)` | ✅ |
| 010 | 0 `response.choices`/`.choices[0]`/`.tool_calls` di orchestrator; `_call_openrouter` → `ModelReply`, parse di luar loop retry | ✅ |
| 011 | 0 dict role mentah di orchestrator/capture (semua lewat `messages.py`) | ✅ |
| 016 | 4 tes integration end-to-end; suite 83 | ✅ |

**Drift yang ditandai (kosmetik, bukan regresi):**

- **Jumlah tes basi**: ekspektasi di plan 001–005/009 ("60 passed") dan 010/011 ("67 passed") → aktual **83** (suite tumbuh: integration 016 + unit `RecordingDevice` + item 3 recorder + polesan parametrize `classify_api_error` +12). Perintah `python -m pytest -q` tetap valid.
- **Plan 002 mengutip SHA v4.2.1/v5.6.0** → live **v7.0.1/v7.0.0** (`3d3c42e5…`/`5fda3b95…`): upgrade **disengaja** (F-07, plan 008/017); invariant pin-SHA + least-privilege tetap berdiri.
- **Plan 010/011 mengutip nomor baris era refactor** (orchestrator.py:124-144/:186-194 dst) → bergeser; invariant fungsional bertahan.

**Retired/superseded (dikonfirmasi):**

- OVR-01/OVR-02: overrides (keputusan desain), bukan plan — tetap tanpa plan.
- **012** superseded oleh **015** (012: Done via 015).
- **002 + 008** diwakili **017** (semua Fixed/DONE).
- **003 = 014** (F-02): 003 diverifikasi; 014 kini Verified via reconcile — fail-closed berdiri.
- **007 = 013** (F-01): **⛔ BLOCKED** — butuh verifikasi live (game + API key + model vision/tools); guard offline terverifikasi, verifikasi live belum; bukan retired.

### Rekonsiliasi kedua (009–017, 2026-08-06)

Status plan 009–017 diperiksa ulang terhadap kode live — **semua invariant LOLOS** (suite **83 passed**):

- **009–012 (kandidat arsitektur)** — selesai & terverifikasi; **semua retired** (tidak ada pekerjaan tersisa): #1 Frame module, #2 adapter polos, #3 kontrak wire-shape, #4 seam input device.
- **013 (F-01 prompt injection)** — guard offline berdiri (`untrusted_screenshot` ×2 di `api.py`, 2 tes guard); verifikasi live **BLOCKED** (butuh env eksternal). Ditandai BLOCKED sesuai instruksi plan.
- **014 (F-02 fail-open)** — diverifikasi via reconcile sebelumnya: `os.name != "nt"` ×2 dengan `raise`.
- **015 (device port)** — DONE: `pydirectinput` hanya di `dn_bot/device.py` (guard grep).
- **016 (integration)** — DONE: 4 tes end-to-end, termasuk item 3 (aksi nyata via `RecordingDevice`).
- **017 (hardening CI)** — DONE: 2 `uses:` @ SHA 40-hex + `permissions: contents: read`; actionlint + yaml-lint bersih.
- **Referensi basi yang diperbarui**: angka tes di plan 013/014/015/016/017 (60/62/71/72) → 83 (suite tumbuh via polesan tes).
