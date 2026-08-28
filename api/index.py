import os
import logging
import requests
from io import BytesIO

from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import StreamingResponse

try:
    from api.scanner import scan_image
except ImportError:
    from scanner import scan_image

try:
    from api.compress import compress_image, MAX_FILE_SIZE
except ImportError:
    from compress import compress_image, MAX_FILE_SIZE


app = FastAPI()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

# Timeout tiap call ke Telegram API.
# Fungsi serverless (Vercel Hobby) dibunuh di 10 detik,
# jadi tiap request harus selesai jauh sebelum itu.
HTTP_TIMEOUT = 8

# Secret untuk validasi webhook (opsional).
# Set env var ini di Vercel DAN kirim sebagai `secret_token`
# saat memanggil setWebhook. Jika tidak diset, validasi dilewati.
WEBHOOK_SECRET = os.environ.get("TELEGRAM_WEBHOOK_SECRET")

# Menyimpan mode tiap pengguna: "compress" atau "scan"
user_mode = {}

logger = logging.getLogger(__name__)


def _validate_webhook_secret(request: Request) -> bool:
    """Cek header X-Telegram-Bot-Api-Secret-Token jika secret dikonfigurasi."""
    if not WEBHOOK_SECRET:
        return True
    return request.headers.get("X-Telegram-Bot-Api-Secret-Token") == WEBHOOK_SECRET


@app.get("/api")
def home():
    return {
        "status": "success",
        "message": "Telegram Image Compressor API is running"
    }


@app.post("/api/compress")
async def compress(file: UploadFile = File(...)):

    data = await file.read()
    try:
        compressed = compress_image(data)
    except ValueError as e:
        return {"status": "error", "reason": str(e)}

    return StreamingResponse(
        BytesIO(compressed),
        media_type="image/jpeg"
    )


@app.post("/api/webhook")
async def webhook(request: Request):

    # ==========================
    # 0. Validasi secret webhook
    # ==========================

    if not _validate_webhook_secret(request):
        logger.warning("Webhook ditolak: secret token tidak valid")
        return {
            "status": "rejected",
            "reason": "invalid_secret"
        }

    chat_id = None

    try:

        update = await request.json()

        if "message" not in update:
            return {"status": "ignored"}

        message = update["message"]
        chat_id = message["chat"]["id"]

        # Handle commands
        if "text" in message:
            text = message.get("text", "")
            if text.startswith("/start"):
                send_message(
                    chat_id,
                    "Halo! Selamat datang di Bot Kompres Gambar.\n\n"
                    "Gunakan menu berikut:\n"
                    "/compress - Kompres foto\n"
                    "/scanner - Scan foto jadi hitam-putih\n"
                    "/help - Bantuan"
                )
                return {"status": "ok"}
            elif text.startswith("/help"):
                send_message(
                    chat_id,
                    "Bot ini dapat mengompres dan memindai gambar Anda.\n\n"
                    "Cara pakai:\n"
                    "1. Klik /compress atau /scanner\n"
                    "2. Kirim foto (maks 4 MB)\n"
                    "3. Bot akan mengirimkan hasilnya."
                )
                return {"status": "ok"}
            elif text.startswith("/compress"):
                user_mode[chat_id] = "compress"
                send_message(
                    chat_id,
                    "Silakan kirimkan foto yang ingin Anda kompres."
                )
                return {"status": "ok"}
            elif text.startswith("/scanner"):
                user_mode[chat_id] = "scan"
                send_message(
                    chat_id,
                    "Silakan kirimkan foto yang ingin dipindai.\n\n"
                    "Tolong kirim foto dokumen dengan warna background yang berbeda dari warna dokumen, dan pastikan dokumen tidak terpotong.\n"
                )
                return {"status": "ok"}
        # Jika bukan foto
        if "photo" not in message:

            send_message(
                chat_id,
                "📷 Silakan kirim gambar untuk dikompres."
            )

            return {"status": "ok"}

        # Ambil foto dengan resolusi terbesar
        photo = message["photo"][-1]

        file_id = photo["file_id"]

        # ==========================
        # 1. Ambil informasi file
        # ==========================

        file_info_response = requests.get(
            f"{TELEGRAM_API}/getFile",
            params={
                "file_id": file_id
            },
            timeout=HTTP_TIMEOUT
        )

        file_info = file_info_response.json()

        if not file_info.get("ok"):
            send_message(
                chat_id,
                "❌ Gagal mendapatkan informasi foto."
            )

            return {"status": "error"}

        file_data = file_info["result"]

        file_path = file_data["file_path"]

        # Telegram memberikan ukuran file
        file_size = file_data.get("file_size", 0)

        # ==========================
        # 2. Cek ukuran file
        # ==========================

        if file_size > MAX_FILE_SIZE:

            size_mb = file_size / (1024 * 1024)

            send_message(
                chat_id,
                f"❌ Foto terlalu besar.\n\n"
                f"📦 Ukuran foto: {size_mb:.2f} MB\n"
                f"📏 Batas maksimal: 4 MB\n\n"
                f"Silakan kirim foto dengan ukuran maksimal 4 MB."
            )

            return {
                "status": "rejected",
                "reason": "file_too_large"
            }

        # ==========================
        # 3. Download foto
        # ==========================

        image_response = requests.get(
            f"{TELEGRAM_FILE_API}/{file_path}",
            timeout=HTTP_TIMEOUT
        )

        if image_response.status_code != 200:

            send_message(
                chat_id,
                "❌ Gagal mengunduh foto."
            )

            return {"status": "error"}

        original_data = image_response.content

        original_size = len(original_data)

        # ==========================
        # 3b. Mode scanner: proses dengan OpenCV
        # ==========================

        if user_mode.get(chat_id) == "scan":

            try:

                scanned_data = scan_image(original_data)

            except Exception:

                logger.exception("Gagal scan gambar")

                send_message(
                    chat_id,
                    "❌ Gagal memproses foto untuk discan."
                )

                return {"status": "error"}

            response = requests.post(
                f"{TELEGRAM_API}/sendPhoto",
                files={
                    "photo": (
                        "scanned.jpg",
                        scanned_data,
                        "image/jpeg"
                    )
                },
                data={
                    "chat_id": chat_id,
                    "caption": "✅ Foto berhasil di-scan!"
                },
                timeout=HTTP_TIMEOUT
            )

            if not response.ok:

                send_message(
                    chat_id,
                    "❌ Foto berhasil di-scan, "
                    "tetapi gagal mengirim hasilnya."
                )

                return {"status": "error"}

            return {
                "status": "success",
                "mode": "scan"
            }

        # ==========================
        # 4. Kompres via modul
        # ==========================

        try:
            compressed_data = compress_image(original_data)
        except ValueError as e:
            send_message(
                chat_id,
                f"❌ {e}"
            )
            return {"status": "error"}
        except Exception:
            logger.exception("Gagal mengompres gambar")
            send_message(
                chat_id,
                "❌ Gagal mengompres foto."
            )
            return {"status": "error"}

        compressed_size = len(compressed_data)

        # ==========================
        # 5. Hitung penghematan
        # ==========================

        saved_bytes = original_size - compressed_size

        if original_size > 0:
            saved_percent = (
                saved_bytes / original_size
            ) * 100
        else:
            saved_percent = 0

        original_mb = original_size / (1024 * 1024)
        compressed_mb = compressed_size / (1024 * 1024)

        # ==========================
        # 6. Kirim hasil
        # ==========================

        caption = (
            "✅ Gambar berhasil dikompres!\n\n"
            f"📦 Sebelum : {original_mb:.2f} MB\n"
            f"🗜️ Sesudah : {compressed_mb:.2f} MB\n"
            f"💾 Hemat   : {saved_percent:.1f}%"
        )

        response = requests.post(
            f"{TELEGRAM_API}/sendPhoto",
            files={
                "photo": (
                    "compressed.jpg",
                    compressed_data,
                    "image/jpeg"
                )
            },
            data={
                "chat_id": chat_id,
                "caption": caption
            },
            timeout=HTTP_TIMEOUT
        )

        if not response.ok:

            send_message(
                chat_id,
                "❌ Gambar berhasil dikompres, "
                "tetapi gagal mengirim hasilnya."
            )

            return {"status": "error"}

        return {
            "status": "success",
            "original_size": original_size,
            "compressed_size": compressed_size,
            "saved_percent": saved_percent
        }

    except Exception:

        # Jangan biarkan exception naik ke Telegram.
        # HTTP 500 membuat Telegram me-retry update yang sama berulang kali.
        logger.exception("Gagal memproses update Telegram")

        try:
            if chat_id is not None:
                send_message(
                    chat_id,
                    "❌ Terjadi kesalahan di server. Silakan coba lagi."
                )
        except Exception:
            logger.exception("Gagal mengirim pesan error ke user")

        return {
            "status": "error",
            "reason": "internal_error"
        }


def send_message(chat_id, text):

    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text
        },
        timeout=HTTP_TIMEOUT
    )
