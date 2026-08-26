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

## 2. Kompres Gambar
- [x] Logic kompres jalan di `api/index.py`
- [ ] Refactor ke `api/compress.py`: `compress_image(data: bytes, quality: int = 40) -> bytes`
      (signature parameterized sejak awal supaya level dinamis v2 tanpa refactor)
- [ ] Handle orientasi EXIF (`PIL.ImageOps.exif_transpose`) sebelum kompres
- [ ] Unit test: input PNG/RGBA/WebP → output JPEG valid, ukuran berkurang

## 3. Kompres PDF (fitur baru)
- [ ] Install `PyMuPDF` ke `requirements.txt`
- [ ] Buat `api/pdf.py`: `compress_pdf(data: bytes) -> bytes`
      - Re-render / re-embed gambar halaman sebagai JPEG q=40
      - Hapus metadata (`doc.set_metadata({})`)
      - Save dengan `garbage=4, deflate=True`
- [ ] Guard: PDF terenkripsi/password → tolak dengan pesan jelas
- [ ] Guard: jika hasil ≥ ukuran asli → kirim file asli balik + catatan "sudah optimal"
- [ ] Taruh sample PDF di `samples/` + unit test (valid PDF, ukuran berkurang)

## 4. Integrasi Bot
- [x] Pola mode per user: `user_mode[chat_id]` di `api/index.py`
- [ ] Command `/pdf` → set `user_mode[chat_id] = "pdf"`
- [ ] Handler `message.document` (PDF **tidak** datang sebagai `photo`) — cek `mime_type == "application/pdf"`
- [ ] Update teks `/start` dan `/help` dengan fitur PDF
- [ ] Daftarkan command di BotFather: `/start`, `/compress`, `/scanner`, `/pdf`, `/help`

## 5. Deploy Vercel
- [ ] Buat `vercel.json` (routing semua path → `api/index.py`)
- [ ] Set env var `TELEGRAM_BOT_TOKEN` di dashboard Vercel
- [ ] Set webhook sekali setelah deploy:
      `https://api.telegram.org/bot<TOKEN>/setWebhook?url=<URL>/api/webhook`
- [ ] Tes end-to-end dari Telegram: compress, scanner, pdf

## Backlog (v2+)
- [ ] Level kompresi dinamis: `/compress low|med|high` → q=60/40/20
- [ ] OCR (tesseract) — hanya kalau benar-benar dibutuhkan
