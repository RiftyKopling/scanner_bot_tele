import os
import logging
import time
import requests
import json
import uuid

from fastapi import FastAPI, Request

try:
    from api.scanner import scan_image
except ImportError:
    from scanner import scan_image

try:
    from api.pdf_utils import png_to_pdf, combine_to_pdf
except ImportError:
    from pdf_utils import png_to_pdf, combine_to_pdf


app = FastAPI()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]
CHAT_ID = os.environ["TELEGRAM_CHAT_ID"]

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

# Batas ukuran file: 4 MB
MAX_FILE_SIZE = 4 * 1024 * 1024

# Cache untuk hasil scan (untuk download PNG/PDF)
# cache_id -> {"png": bytes, "ts": float, "chat_id": int}
scan_cache: dict[str, dict] = {}
CACHE_TTL = 300  # 5 menit

# Session untuk batch scan
# chat_id -> {"mode": "scan"|"scan_batch", "pages": [bytes...], "started_at": float, "message_id": int}
user_sessions: dict[int, dict] = {}
MAX_BATCH_PAGES = 10
SESSION_TTL = 600  # 10 menit

logger = logging.getLogger(__name__)


def _cleanup_expired():
    """Lazy cleanup untuk cache dan session yang expired."""
    now = time.time()
    
    # Cleanup scan_cache
    expired_cache = [
        cid for cid, data in scan_cache.items()
        if now - data["ts"] > CACHE_TTL
    ]
    for cid in expired_cache:
        del scan_cache[cid]
    
    # Cleanup user_sessions
    expired_sessions = [
        uid for uid, sess in user_sessions.items()
        if now - sess["started_at"] > SESSION_TTL
    ]
    for uid in expired_sessions:
        del user_sessions[uid]


def _validate_webhook_secret(request: Request) -> bool:
    """Cek header X-Telegram-Bot-Api-Secret-Token jika secret dikonfigurasi."""
    if not WEBHOOK_SECRET:
        return True
    return request.headers.get("X-Telegram-Bot-Api-Secret-Token") == WEBHOOK_SECRET


def _build_inline_keyboard():
    """Buat inline keyboard untuk menu utama."""
    return {
        "inline_keyboard": [
            [
                {"text": "📷 Scan Dokumen", "callback_data": "cmd_scanner"},
                {"text": "❓ Bantuan", "callback_data": "cmd_help"}
            ],
            [
                {"text": "ℹ️ Status", "callback_data": "cmd_status"}
            ]
        ]
    }


def _build_help_keyboard():
    """Buat inline keyboard untuk halaman bantuan."""
    return {
        "inline_keyboard": [
            [
                {"text": "📷 Scan Dokumen", "callback_data": "cmd_scanner"},
                {"text": "🏠 Menu Utama", "callback_data": "cmd_start"}
            ]
        ]
    }


def _build_status_keyboard():
    """Buat inline keyboard untuk halaman status."""
    return {
        "inline_keyboard": [
            [
                {"text": "📷 Scan Dokumen", "callback_data": "cmd_scanner"},
                {"text": "🏠 Menu Utama", "callback_data": "cmd_start"}
            ]
        ]
    }


@app.get("/api")
def home():
    return {
        "status": "success",
        "message": "Telegram Scanner Bot API is running"
    }


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

    _cleanup_expired()

    chat_id = None

    try:

        update = await request.json()

        # Handle callback query (inline keyboard button press)
        if "callback_query" in update:
            return await handle_callback_query(update["callback_query"])

        if "message" not in update:
            return {"status": "ignored"}

        message = update["message"]
        chat_id = message["chat"]["id"]

        # Handle commands
        if "text" in message:
            text = message.get("text", "")
            if text.startswith("/start"):
                return await send_start_message(chat_id)
            elif text.startswith("/help"):
                return await send_help_message(chat_id)
            elif text.startswith("/status"):
                return await send_status_message(chat_id)
            elif text.startswith("/scanner"):
                user_sessions[chat_id] = {"mode": "scan", "pages": [], "started_at": time.time(), "message_id": 0}
                await send_message(
                    chat_id,
                    "📷 *Mode Scan Dokumen Aktif*\n\n"
                    "Silakan kirimkan foto yang ingin dipindai.\n\n"
                    "💡 *Tips hasil terbaik:*\n"
                    "• Background kontras dengan dokumen\n"
                    "• Dokumen tidak terpotong\n"
                    "• Cahaya merata, hindari bayangan\n"
                    "• Kamera tegak lurus ke dokumen",
                    reply_markup=_build_help_keyboard()
                )
                return {"status": "ok"}

        # Jika bukan foto
        if "photo" not in message:

            await send_message(
                chat_id,
                "📷 *Silakan kirim foto untuk di-scan.*\n\n"
                "Gunakan tombol di bawah atau ketik `/scanner` untuk memulai.",
                reply_markup=_build_inline_keyboard()
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
            await send_message(
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

            await send_message(
                chat_id,
                f"❌ *Foto terlalu besar.*\n\n"
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

            await send_message(
                chat_id,
                "❌ Gagal mengunduh foto."
            )

            return {"status": "error"}

        original_data = image_response.content

        original_size = len(original_data)

        # ==========================
        # 3b. Mode scanner: proses dengan OpenCV
        # ==========================

        if user_sessions.get(chat_id, {}).get("mode") == "scan":

            try:

                scanned_data = scan_image(original_data)

            except Exception:

                logger.exception("Gagal scan gambar")

                await send_message(
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

                await send_message(
                    chat_id,
                    "❌ Foto berhasil di-scan, "
                    "tetapi gagal mengirim hasilnya."
                )

                return {"status": "error"}

            return {
                "status": "success",
                "mode": "scan"
            }

        # Default: jika user tidak set mode, default ke scan
        try:
            scanned_data = scan_image(original_data)
        except Exception:
            logger.exception("Gagal scan gambar")
            await send_message(
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
            await send_message(
                chat_id,
                "❌ Foto berhasil di-scan, "
                "tetapi gagal mengirim hasilnya."
            )
            return {"status": "error"}

        return {
            "status": "success",
            "mode": "scan"
        }

    except Exception:

        # Jangan biarkan exception naik ke Telegram.
        # HTTP 500 membuat Telegram me-retry update yang sama berulang kali.
        logger.exception("Gagal memproses update Telegram")

        try:
            if chat_id is not None:
                await send_message(
                    chat_id,
                    "❌ Terjadi kesalahan di server. Silakan coba lagi."
                )
        except Exception:
            logger.exception("Gagal mengirim pesan error ke user")

        return {
            "status": "error",
            "reason": "internal_error"
        }


async def handle_callback_query(callback_query):
    """Handle inline keyboard button presses."""
    _cleanup_expired()
    
    chat_id = callback_query["message"]["chat"]["id"]
    data = callback_query.get("data", "")
    callback_query_id = callback_query["id"]

    # Answer callback query to remove loading state
    requests.post(
        f"{TELEGRAM_API}/answerCallbackQuery",
        data={"callback_query_id": callback_query_id},
        timeout=HTTP_TIMEOUT
    )

    if data == "cmd_start":
        return await send_start_message(chat_id)
    elif data == "cmd_help":
        return await send_help_message(chat_id)
    elif data == "cmd_status":
        return await send_status_message(chat_id)
    elif data == "cmd_scanner":
        user_sessions[chat_id] = {"mode": "scan", "pages": [], "started_at": time.time(), "message_id": 0}
        await send_message(
            chat_id,
            "📷 *Mode Scan Dokumen Aktif*\n\n"
            "Silakan kirimkan foto yang ingin dipindai.\n\n"
            "💡 *Tips hasil terbaik:*\n"
            "• Background kontras dengan dokumen\n"
            "• Dokumen tidak terpotong\n"
            "• Cahaya merata, hindari bayangan\n"
            "• Kamera tegak lurus ke dokumen",
            reply_markup=_build_help_keyboard()
        )
        return {"status": "ok"}

    return {"status": "ignored"}


async def send_start_message(chat_id):
    """Kirim pesan menu utama dengan inline keyboard."""
    text = (
        "📄 *Bot Scan Dokumen*\n\n"
        "┌─ *PERINTAH* ────────────────────────┐\n"
        "│ `/scanner` ─ Mode scan dokumen      │\n"
        "│ `/help`    ─ Bantuan detail         │\n"
        "│ `/status`  ─ Cek mode & batas file  │\n"
        "└─────────────────────────────────────┘\n\n"
        "📏 Batas: 4 MB per foto\n"
        "📤 Hasil: PNG hitam-putih via chat\n\n"
        "Kirim foto setelah klik `/scanner` atau gunakan tombol di bawah:"
    )
    await send_message(chat_id, text, reply_markup=_build_inline_keyboard())
    return {"status": "ok"}


async def send_help_message(chat_id):
    """Kirim pesan bantuan detail dengan inline keyboard."""
    text = (
        "📖 *CARA PAKAI OPTIMAL*\n\n"
        "1️⃣ Klik `/scanner` atau tombol *Scan Dokumen*\n"
        "2️⃣ Ambil foto dokumen:\n"
        "   ✅ Background kontras (hitam/putih)\n"
        "   ✅ Dokumen tidak terpotong\n"
        "   ✅ Cahaya merata, hindari bayangan\n"
        "   ❌ Jangan miring ekstrem (>30°)\n\n"
        "💡 *TIPS HASIL TERBAIK:*\n"
        "• Kertas putih di atas meja gelap\n"
        "• Kamera tegak lurus ke dokumen\n"
        "• Fokus tajam (tap layar HP)\n\n"
        "⚠️ *BATASAN:*\n"
        "• Maks 4 MB (Telegram kompres otomatis)\n"
        "• Flat scan — belum auto-crop sudut\n"
        "• Hasil PNG → Telegram bisa kompres ulang"
    )
    await send_message(chat_id, text, reply_markup=_build_help_keyboard())
    return {"status": "ok"}


async def send_status_message(chat_id):
    """Kirim info status bot dengan inline keyboard."""
    session = user_sessions.get(chat_id, {})
    mode = session.get("mode", "belum dipilih")
    mode_text = "📷 Scanner aktif" if mode == "scan" else "⏳ Belum dipilih"

    text = (
        f"ℹ️ *STATUS BOT*\n\n"
        f"Mode: {mode_text}\n"
        f"Batas file: 4 MB\n"
        f"Format output: PNG (hitam-putih)\n"
        f"Session: in-memory (reset saat restart)"
    )
    await send_message(chat_id, text, reply_markup=_build_status_keyboard())
    return {"status": "ok"}


async def send_message(chat_id, text, parse_mode="Markdown", reply_markup=None):
    """Kirim pesan ke Telegram dengan dukungan Markdown dan inline keyboard."""
    data = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    if reply_markup:
        data["reply_markup"] = json.dumps(reply_markup)

    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        data=data,
        timeout=HTTP_TIMEOUT
    )
    
@app.get("/api/ping")
def ping():
    data = {
        "chat_id": CHAT_ID,
        "text": "🔔 Test notifikasi berhasil!"
    }

    response = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        data=data,
        timeout=HTTP_TIMEOUT
    )

    return {
        "status_code": response.status_code,
        "telegram_response": response.json()
    }
@app.head("/api/ping")
def ping_head():
    data = {
        "chat_id": CHAT_ID,
        "text": "🔔 Test UptimeRobot berhasil!"
    }

    response = requests.post(
        f"{TELEGRAM_API}/sendMessage",
        data=data,
        timeout=HTTP_TIMEOUT
    )

    return {"status": "ok"}