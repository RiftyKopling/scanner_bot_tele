# scanner_bot_tele

Bot Telegram berbasis **FastAPI** untuk pemindaian dokumen (document scanner) sederhana menggunakan **OpenCV**. Bot berjalan sebagai webhook dan di-deploy sebagai serverless function (Vercel).

🔗 Demo/endpoint: [test-bot-tele-iota.vercel.app](https://test-bot-tele-iota.vercel.app)

## Fitur

- **`/scanner`** — Mengubah foto dokumen menjadi versi hitam-putih yang lebih bersih, melalui pipeline OpenCV:
  1. Resize otomatis jika lebar gambar > 1600px
  2. Grayscale
  3. Illumination correction (morphological closing untuk estimasi background)
  4. Noise reduction dengan bilateral filter (menjaga tepi teks tetap tajam)
  5. Adaptive thresholding (`ADAPTIVE_THRESH_GAUSSIAN_C`)
  6. Cleanup akhir dengan median blur
- Validasi ukuran file (maksimal **4 MB** per foto yang dikirim ke bot)
- Mode per-pengguna disimpan sementara (in-memory) untuk membedakan permintaan `/scanner`

## Struktur proyek

```
scanner_bot_tele/
├── api/
│   ├── index.py       # Endpoint FastAPI: webhook, /api/webhook
│   └── scanner.py      # Pipeline OpenCV untuk fitur scan_image()
├── tests/
│   ├── test_scan_image.py   # unit test pytest scanner
│   ├── test_scanner.py      # CLI tuning preset scanner
│   └── send_to_scanner.py   # uji manual satu gambar + matplotlib
├── samples/           # gambar uji (gitignored)
├── requirements.txt
└── requirements-dev.txt
```

## Tech stack

- [FastAPI](https://fastapi.tiangolo.com/) — web framework
- [OpenCV (headless)](https://pypi.org/project/opencv-python-headless/) — image processing untuk fitur scanner
- [Requests](https://docs.python-requests.org/) — komunikasi dengan Telegram Bot API
- Deploy target: **Vercel** (struktur `api/` mengikuti konvensi Vercel Python Serverless Functions)

## Instalasi & menjalankan lokal

### 1. Clone repository

```bash
git clone https://github.com/RiftyKopling/scanner_bot_tele.git
cd scanner_bot_tele
```

### 2. Buat virtual environment & install dependencies

```bash
python -m venv venv
source venv/bin/activate      # Windows: venv\Scripts\activate
pip install -r requirements.txt -r requirements-dev.txt
```

### 3. Siapkan environment variable

Buat bot Telegram lewat [@BotFather](https://t.me/BotFather) untuk mendapatkan token, lalu set environment variable:

```bash
export TELEGRAM_BOT_TOKEN="isi_token_bot_kamu"
```

Di Windows (PowerShell):
```powershell
$env:TELEGRAM_BOT_TOKEN="isi_token_bot_kamu"
```

### 4. Jalankan server lokal

```bash
uvicorn api.index:app --reload
```

Server berjalan di `http://127.0.0.1:8000`.

### 5. Hubungkan webhook Telegram ke server lokal

Karena Telegram butuh URL publik (HTTPS) untuk webhook, gunakan tunnel seperti [ngrok](https://ngrok.com/) saat testing lokal:

```bash
ngrok http 8000
```

Lalu daftarkan webhook ke Telegram:

```bash
curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=<URL_NGROK_ATAU_VERCEL>/api/webhook"
```

## Endpoint API

| Method | Endpoint       | Deskripsi                                                        |
|--------|----------------|--------------------------------------------------------------------|
| GET    | `/api`         | Health check, memastikan API berjalan                             |
| POST   | `/api/webhook` | Endpoint webhook yang menerima update dari Telegram Bot API       |

## Cara pakai bot di Telegram

1. `/start` — Menampilkan menu utama
2. `/scanner` — Mengaktifkan mode scan dokumen, lalu kirim foto
3. `/help` — Menampilkan bantuan penggunaan

Bot akan menolak foto dengan ukuran lebih dari 4 MB dan meminta pengguna mengirim ulang dengan ukuran yang lebih kecil.

## Deploy ke Vercel

Repository ini sudah mengikuti struktur `api/` yang dikenali otomatis oleh Vercel sebagai Python Serverless Function.

1. Import repository ke [Vercel](https://vercel.com/new)
2. Tambahkan environment variable `TELEGRAM_BOT_TOKEN` di pengaturan project Vercel
3. Setelah deploy, daftarkan webhook Telegram ke URL production:
   ```bash
   curl "https://api.telegram.org/bot<TELEGRAM_BOT_TOKEN>/setWebhook?url=https://<domain-vercel-kamu>/api/webhook"
   ```

## Catatan pengembangan

- Mode pengguna (`user_mode`) saat ini disimpan **in-memory** — akan reset setiap kali serverless function di-restart/cold start. Untuk produksi yang lebih stabil, pertimbangkan penyimpanan eksternal (Redis, database, atau key-value store).
- Pipeline scanner saat ini belum melakukan deteksi tepi dokumen otomatis (edge detection + perspective transform) untuk crop & meluruskan kertas — hasil scan mengikuti orientasi foto asli apa adanya.
- Opsi Otsu thresholding sudah dicoba (lihat komentar di `scanner.py`) sebagai alternatif adaptive threshold, namun default yang dipakai saat ini tetap `adaptiveThreshold`.

## Lisensi

Belum ditentukan. Tambahkan file `LICENSE` sesuai kebutuhan (misalnya MIT) jika proyek ini akan dibuka untuk kontribusi publik.