# Plan 006 — F-06/SBP-006: batasi detail error API di log (implement)

- **Temuan:** Detail error API (pesan SDK) dicantumkan **verbatim** ke log → log berisik, metadata request ikut tersimpan. Low.
- **Status:** ✅ **Fixed** (2026-08-06). Implementasi + tes regresi selesai; rantai exception di-suppress (`raise ... from None`) agar pesan SDK mentah tidak bocor via traceback `log.exception`; suite penuh **62 passed** saat itu (kini **117**).

## Konteks

`_call_openrouter` mengambil `detail = getattr(error, "message", None) or str(error)` dan menyisipkannya mentah ke pesan `RuntimeError`; `run_dn_bot` lalu me-log pesan itu via `log.exception` (menyertakan traceback + `detail`). Pesan SDK bisa sangat panjang (mis. respons 4xx yang menyertakan body request).

## Keadaan saat ini (bukti)

- `dn_bot/api.py:179`:
  ```python
  detail = getattr(error, "message", None) or str(error)
  if kind not in _RETRYABLE_API_KINDS or attempt == API_MAX_ATTEMPTS:
      raise RuntimeError(f"{API_ERROR_MESSAGES[kind]} Detail: {detail}") from error
  ```
- `dn_bot/orchestrator.py:112-114` — `log.exception("OpenRouter API gagal; sesi dihentikan tanpa aksi tambahan: %s", error)`.
- Tidak ada kebocoran secret terkonfirmasi (API key tidak pernah di-log); ini murni masalah panjang/verbosity.

## Langkah

1. Di `dn_bot/api.py`, tambahkan konstanta `API_ERROR_DETAIL_MAX = 500` di `dn_bot/config.py` (bersama konstanta API lain), atau lokal di `api.py` — pilih `config.py` agar konsisten dengan pola konstanta.
2. Batasi `detail` sebelum masuk pesan error:
   ```python
   detail = getattr(error, "message", None) or str(error)
   if len(detail) > API_ERROR_DETAIL_MAX:
       detail = detail[:API_ERROR_DETAIL_MAX] + "... (terpotong)"
   ```
3. Pertahankan klasifikasi actionable (`API_ERROR_MESSAGES[kind]`) — itu yang utama, detail hanya penunjang.
4. Tidak mengubah jalur retry: `kind` tetap dihitung dari `_classify_api_error` (status/type), bukan dari pesan.

## Verifikasi (machine-checkable)

```bash
python -m pytest -q tests/test_dn_bot.py -k "call_openrouter"   # semua tes retry/config tetap pass
python -m pytest -q                                              # 117 passed (kini)
```

## Batas scope

- IN: `dn_bot/config.py` (konstanta), `dn_bot/api.py` (`_call_openrouter`).
- OUT: `orchestrator.py` (`log.exception` dibiarkan — traceback tetap berguna; `detail` yang panjang sudah dipotong di sumber).
- OUT: menyembunyikan klasifikasi — pesan actionable wajib tetap ada.

## Rencana tes

Tambahkan 1-2 tes di `tests/test_dn_bot.py` (pola `_FakeAPIError`):
- error dengan `message` > batas → `RuntimeError` berisi `... (terpotong)` dan panjang pesan ≤ batas + suffix.
- error dengan `message` pendek → tidak dipotong (regresi guard terhadap over-trimming).
Ikuti gaya tes `test_call_openrouter_does_not_retry_configuration_errors` (parametrize + `pytest.raises(RuntimeError, match=...)`).

## Catatan pemeliharaan

Jika suatu saat detail perlu dibedakan (mis. hanya `?` log terminal vs file), pertimbangkan memisahkan pesan user-facing dari detail; untuk sekarang potong di sumber cukup.

## Update dokumen

Selesai implementasi: pindahkan F-06 di SECURITY.md dari 🔴 Terbuka ke ✅ Fixed, update ringkasan eksekutif (1 Low tersisa: F-07), tambahkan item mitigasi, dan tambah baris CHANGELOG.md (Unreleased → Security).
