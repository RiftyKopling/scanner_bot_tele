# TODO.md

Diurutkan dari yang paling dekat siap pakai.

## 1. Scanner (paling matang)
- [x] Pipeline dasar jalan (`api/scanner.py`)
- [x] CLI tuning preset: `python -m tests.test_scanner --show`
- [x] Unit test output PNG valid: `pytest tests/test_scan_image.py`
- [ ] Tambah deteksi tepi + contour 4 titik dokumen → perspective transform
      (Canny/Gaussian → findContours → order_points → warpPerspective)
- [ ] Eksperimen CLAHE dan/atau gamma correction sebelum threshold
      (tuning via `tests/test_scanner.py`, jangan langsung ubah produksi)
- [ ] [TODO: putuskan — hasil scan dikirim sebagai photo saja, atau juga opsi sendDocument agar tidak dikompres ulang Telegram?]

## 2. Deploy Vercel
- [ ] Buat `vercel.json` (routing semua path → `api/index.py`)
- [ ] Set env var `TELEGRAM_BOT_TOKEN` di dashboard Vercel
      (+ opsional `TELEGRAM_WEBHOOK_SECRET` untuk validasi webhook)
- [ ] Set webhook sekali setelah deploy (sertakan secret jika dipakai):
      `https://api.telegram.org/bot<TOKEN>/setWebhook?url=<URL>/api/webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>`
- [ ] Tes end-to-end dari Telegram: scanner

Keputusan (bukan task):
- TELEGRAM_BOT_TOKEN ✅ sudah diset di Vercel
- user_mode in-memory diterima flaky di serverless (v1 personal)

## Backlog (v2+)
- [ ] OCR (tesseract) — hanya kalau benar-benar dibutuhkan