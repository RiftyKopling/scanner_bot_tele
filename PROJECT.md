# PROJECT.md — Bot Scan Dokumen (Telegram)

## Tujuan
Bot Telegram personal untuk merapikan dokumen langsung dari chat.
Pengguna: saya sendiri. Masalah yang diselesaikan:
- Foto dokumen berantakan (pencahayaan tidak merata, latar kotor) → scan ala CamScanner.

## Fitur

### 1. Scan Dokumen
| | |
|---|---|
| Input | Foto dokumen dari chat Telegram (maks 4 MB) |
| Output | PNG hitam-putih bersih via `sendPhoto` |

Pipeline saat ini (`api/scanner.py`, flat scan):
decode → resize max lebar 1600 px → grayscale → koreksi iluminasi (morph close ellipse) → bilateral filter → adaptive threshold Gaussian → median blur → encode PNG.

Status: **jalan**. Belum ada: deteksi tepi + perspective transform (auto-deteksi & luruskan sudut dokumen), CLAHE, gamma correction → lihat TODO.md.

## Scope v1 — TIDAK Dikerjakan
- Deteksi tepi + perspective transform otomatis (masih flat scan) → pindah ke v2/TODO.
- OCR / ekstraksi teks.
- Batch multi-halaman / multi-file.
- Database, riwayat proses, storage persisten.
- Autentikasi / multi-user management.

## Tech Stack & Alasan
| Komponen | Pilihan | Alasan |
|---|---|---|
| Runtime | Python | Sudah dipakai kode existing |
| Webhook | FastAPI | Async-native; konvensi `api/index.py` = runtime Python Vercel tanpa konfigurasi tambahan |
| Image processing | opencv-python-headless | Tanpa dependency GUI, aman untuk serverless |
| HTTP client | requests | Sinkron sederhana, cukup untuk bot personal |
| Test | pytest (+ pytest-asyncio) | Standar |

## Konvensi Kode
Struktur:
```
api/
  index.py        # entrypoint Vercel: webhook Telegram + handler command
  scanner.py      # scan_image(data: bytes) -> bytes                    (sudah ada)
tests/
  test_scan_image.py   # unit test pytest scanner
  test_scanner.py      # CLI tuning preset scanner (python -m tests.test_scanner --show)
  send_to_scanner.py   # uji manual satu gambar + matplotlib
samples/          # gambar uji (gitignored)
```

Aturan:
- Penamaan `snake_case`; fungsi modul fitur = kata kerja (`scan_image`).
- Kontrak fungsi modul fitur: **bytes masuk → bytes keluar**, raise `ValueError` jika input invalid.
- Error handling: try/except lokal di handler → kirim pesan gagal ke user → return `{"status": "error", "reason": ...}`. Jangan biarkan exception naik sampai webhook (Telegram akan retry).
- File besar: cek `file_size` dari `getFile` **sebelum download**; tolak > 4 MB dengan pesan jelas.
- Pesan bot: Bahasa Indonesia, prefix status emoji (✅/❌).

## Limitasi Hosting (Vercel, plan Hobby)
- Timeout fungsi **10 detik**, bundle ≤ 250 MB, RAM ~1 GB, cold start cv2+numpy ~2–5 s.
- Tanpa persistent disk → semua proses in-memory, hasil langsung dikirim balik.
- Batas Telegram Bot API: download file 20 MB, upload 50 MB — kita self-limit **4 MB** agar aman di timeout 10 s.