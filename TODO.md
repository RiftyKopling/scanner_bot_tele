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
- [ ] Unit test: input PNG/RGBA/WebP → output JPEG valid, ukuran berkurang

Refactor & fix terkait kode kompres masuk **section 6** di bawah.

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
      (+ opsional `TELEGRAM_WEBHOOK_SECRET` untuk validasi webhook)
- [ ] Set webhook sekali setelah deploy (sertakan secret jika dipakai):
      `https://api.telegram.org/bot<TOKEN>/setWebhook?url=<URL>/api/webhook&secret_token=<TELEGRAM_WEBHOOK_SECRET>`
- [ ] Tes end-to-end dari Telegram: compress, scanner, pdf

## 6. Perbaikan api/index.py (hasil review)

### 🔴 Keandalan Deploy
- [x] Bungkus body webhook dengan try/except induk — cegah HTTP 500
      yang memicu retry Telegram; kirim pesan ❌ + return JSON status
- [x] Validasi webhook secret: set `secret_token` saat `setWebhook`,
      cek header `X-Telegram-Bot-Api-Secret-Token` di awal handler
- [x] Turunkan timeout `requests` 30 s → ~8 s (limit fungsi Vercel 10 s)

### 🟡 Refactor Menengah
- [ ] Pindah logic kompres ke `api/compress.py`:
      `compress_image(data: bytes, quality: int = 40) -> bytes`
      (hapus duplikasi `/api/compress` vs webhook)
- [ ] `ImageOps.exif_transpose` sebelum kompres (foto HP tampil miring)
- [ ] Cek `photo["file_size"]` langsung dari update → tolak >4 MB tanpa
      panggilan `getFile` (hemat 1 API call)
- [ ] Pecah webhook ~290 baris → `handle_command()` / `handle_photo()` dll
- [ ] Tambah logging dasar agar bisa debug dari Vercel logs

### 🟢 Polish Kecil
- [ ] Command matching persis (split spasi), bukan `startswith`
- [ ] RGBA→RGB dengan background putih, bukan `convert()` langsung
- [ ] Pesan fallback non-foto menyesuaikan mode aktif (scan vs compress)

Keputusan (bukan task):
- TELEGRAM_BOT_TOKEN ✅ sudah diset di Vercel
- user_mode in-memory diterima flaky di serverless (v1 personal)

## Backlog (v2+)
- [ ] Level kompresi dinamis: `/compress low|med|high` → q=60/40/20
- [ ] OCR (tesseract) — hanya kalau benar-benar dibutuhkan
