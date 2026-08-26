# CLAUDE.md

Konteks proyek untuk AI agent. Baca ini dulu sebelum coding — detail lengkap di `PROJECT.md`, task list di `TODO.md`.

## Apa Ini
Bot Telegram **personal** (Bahasa Indonesia) dengan 3 fitur: kompres gambar, kompres PDF, scan dokumen ala CamScanner. Deploy target: **Vercel** (serverless, plan Hobby).

## Stack
Python · FastAPI (webhook) · Pillow (kompres gambar, JPEG q=40 fixed) · PyMuPDF/fitz (kompres PDF, belum dibuat) · opencv-python-headless + numpy (scanner) · requests (Telegram Bot API) · pytest.

## Struktur & File Penting
```
api/index.py      # SATU-SATUNYA entrypoint: FastAPI app + webhook Telegram
api/scanner.py    # scan_image(bytes)->bytes — SUDAH JALAN, stabil
tests/test_scanner.py   # CLI tuning preset scanner (bukan pytest biasa)
tests/test_scan_image.py # unit test pytest scanner
samples/          # gambar uji (gitignored)
TUNING_SCANNER.txt # panduan tuning scanner
```

## Pola Handler Bot (`api/index.py`)
- Semua masuk lewat `POST /api/webhook` → parse `update["message"]`.
- Command text: `text.startswith("/cmd")` → set `user_mode[chat_id]` (`"compress"` / `"scan"`) → minta user kirim file.
- Foto: `message["photo"][-1]` (index terakhir = resolusi terbesar).
- PDF nanti datang sebagai `message.document` + `mime_type == "application/pdf"` (**bukan** `photo`) — handler untuk ini belum ada.
- Webhook divalidasi header `X-Telegram-Bot-Api-Secret-Token` (env `TELEGRAM_WEBHOOK_SECRET`, opsional — dilewati jika kosong); seluruh body webhook dibungkus try/except induk.
- Balasan via helper `send_message(chat_id, text)` dan POST langsung ke `{TELEGRAM_API}/sendPhoto|sendDocument`.

## Aturan Keras
1. **Maks file 4 MB** — cek `file_size` dari respons `getFile` SEBELUM download.
2. Semua proses **in-memory** (Vercel tanpa persistent disk). Bytes masuk → proses → kirim balik.
3. Kontrak fungsi modul fitur: `bytes -> bytes`, raise `ValueError` jika input invalid:
   - `compress_image(data, quality=40)` [TODO: dipisah dari index.py]
   - `compress_pdf(data)`
   - `scan_image(data)` ✅ sudah ada
4. Exception di handler ditangkap → kirim pesan ❌ ke user → return JSON status. Jangan biarkan error naik ke webhook (Telegram retry ulang).
5. Jangan ubah parameter pipeline scanner tanpa tuning dulu via `python -m tests.test_scanner --show`.
6. Timeout semua call HTTP ke Telegram = `HTTP_TIMEOUT` (8 s) — jangan dinaikkan melebihi limit fungsi 10 s.

## Menjalankan Lokal (Windows PowerShell)
```powershell
pip install -r requirements.txt -r requirements-dev.txt
$env:TELEGRAM_BOT_TOKEN = "123:abc"
uvicorn api.index:app --reload --port 8000
pytest tests/test_scan_image.py -v        # unit test scanner
python -m tests.test_scanner --show       # tuning scanner + grid perbandingan
python tests/send_to_scanner.py           # uji 1 gambar visual (matplotlib)
```
Webhook lokal: pakai ngrok → set webhook ke `<ngrok-url>/api/webhook`.

## Limitasi Hosting (Vercel Hobby)
- Timeout fungsi **10 s**, bundle ≤ 250 MB, cold start cv2+numpy ~2–5 s (wajar).
- Tanpa disk persisten; env var `TELEGRAM_BOT_TOKEN` wajib diset di dashboard (`TELEGRAM_WEBHOOK_SECRET` opsional untuk validasi webhook).
- Telegram API sendiri: download 20 MB / upload 50 MB — bukan bottleneck; bottleneck kita adalah timeout 10 s.
- Belum ada `vercel.json` [TODO] — routing default runtime Python Vercel sudah cocok dengan layout `api/index.py`.

## Status Fitur
| Fitur | Status |
|---|---|
| Kompres gambar | ✅ jalan (logic inline di index.py, refactor terjadwal) |
| Scan dokumen | ✅ jalan (flat scan; perspective transform = TODO) |
| Kompres PDF | ❌ belum dibuat (rencana PyMuPDF, lihat TODO.md) |

## Keputusan Desain (jangan diubah tanpa konfirmasi user)
- Kualitas JPEG **fixed 40%** untuk v1; level dinamis hanya backlog v2.
- PyMuPDF dipilih karena satu wheel pip, tanpa binary eksternal (Ghostscript tidak realistis di serverless).
- Hasil gambar dikirim via `sendPhoto`; PDF via `sendDocument`.
- Pesan bot berbahasa Indonesia.
- `user_mode` in-memory sengaja dipertahankan walau flaky di multi-instance serverless (keputusan v1).
