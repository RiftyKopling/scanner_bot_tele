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


def _build_download_keyboard(cache_id: str):
    """Keyboard untuk download hasil scan: PNG atau PDF."""
    return {
        "inline_keyboard": [
            [
                {"text": "📥 Download PNG", "callback_data": f"dl_png:{cache_id}"},
                {"text": "📄 Download PDF", "callback_data": f"dl_pdf:{cache_id}"}
            ],
            [
                {"text": "🏠 Menu Utama", "callback_data": "cmd_start"}
            ]
        ]
    }


def _build_batch_keyboard(page_count: int):
    """Keyboard saat mode batch scan: tambah halaman atau selesai."""
    return {
        "inline_keyboard": [
            [
                {"text": "📷 Tambah Halaman", "callback_data": "batch_add"},
                {"text": f"✅ Selesai ({page_count}/{MAX_BATCH_PAGES})", "callback_data": "batch_finish"}
            ],
            [
                {"text": "🗑️ Batal", "callback_data": "batch_cancel"}
            ]
        ]
    }


def _build_batch_finish_keyboard(cache_id: str):
    """Keyboard setelah batch selesai: download PDF atau batal."""
    return {
        "inline_keyboard": [
            [
                {"text": "📄 Download PDF", "callback_data": f"dl_pdf:{cache_id}"},
                {"text": "🗑️ Batal", "callback_data": "batch_cancel"}
            ],
            [
                {"text": "🏠 Menu Utama", "callback_data": "cmd_start"}
            ]
        ]
    }


def _build_scan_mode_keyboard():
    """Keyboard untuk memilih mode scan: single atau batch."""
    return {
        "inline_keyboard": [
            [
                {"text": "📷 Scan Tunggal", "callback_data": "scan_mode_single"},
                {"text": "📚 Scan Batch (maks 10)", "callback_data": "scan_mode_batch"}
            ],
            [
                {"text": "🏠 Menu Utama", "callback_data": "cmd_start"}
            ]
        ]
    }


def _build_batch_finish_extended_keyboard(cache_id: str, page_count: int):
    """Keyboard setelah batch selesai dengan opsi tambah halaman."""
    return {
        "inline_keyboard": [
            [
                {"text": "📄 Download PDF", "callback_data": f"dl_pdf:{cache_id}"},
                {"text": "➕ Tambah Halaman", "callback_data": f"batch_add_more:{cache_id}"}
            ],
            [
                {"text": "🗑️ Batal", "callback_data": "batch_cancel"}
            ],
            [
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
                await send_message(
                    chat_id,
                    "📷 *Pilih Mode Scan*\n\n"
                    "📷 *Scan Tunggal* — 1 foto → 1 hasil\n"
                    "📚 *Scan Batch* — Beberapa foto → 1 PDF (maks 10 halaman)\n\n"
                    "Silakan pilih mode di bawah:",
                    reply_markup=_build_scan_mode_keyboard()
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

        session = user_sessions.get(chat_id, {})
        mode = session.get("mode", "scan")  # default ke single scan

        try:
            scanned_data = scan_image(original_data)
        except Exception:
            logger.exception("Gagal scan gambar")
            await send_message(
                chat_id,
                "❌ Gagal memproses foto untuk discan."
            )
            return {"status": "error"}

        if mode == "scan_batch":
            # Batch mode: accumulate pages
            pages = session.get("pages", [])
            batch_id = session.get("batch_id")
            pages.append(scanned_data)
            
            if len(pages) >= MAX_BATCH_PAGES:
                # Auto-finish if max reached
                try:
                    pdf_bytes = combine_to_pdf(pages)
                except Exception:
                    logger.exception("Gagal gabung halaman ke PDF")
                    await send_message(chat_id, "❌ Gagal membuat PDF multi-halaman.")
                    return {"status": "error"}
                
                cache_id = batch_id or str(uuid.uuid4())[:8]
                scan_cache[cache_id] = {
                    "png": pages[0],
                    "pages": pages,
                    "pdf": pdf_bytes,
                    "ts": time.time(),
                    "chat_id": chat_id,
                    "is_batch": True
                }
                
                user_sessions[chat_id] = {
                    "mode": "scan_batch_finished",
                    "batch_id": cache_id,
                    "started_at": time.time(),
                    "message_id": 0
                }
                
                await send_document(
                    chat_id,
                    pdf_bytes,
                    filename=f"batch_scan_{len(pages)}pages.pdf",
                    caption=(
                        f"✅ Batch scan selesai (maks {MAX_BATCH_PAGES}) — {len(pages)} halaman digabung ke PDF.\n\n"
                        f"Klik *➕ Tambah Halaman* jika masih ada dokumen yang tertinggal."
                    ),
                    reply_markup=_build_batch_finish_extended_keyboard(cache_id, len(pages))
                )
                return {"status": "success", "mode": "scan_batch", "pages": len(pages)}
            
            # Update session (preserve batch_id)
            user_sessions[chat_id] = {
                "mode": "scan_batch",
                "pages": pages,
                "batch_id": batch_id,
                "started_at": time.time(),
                "message_id": 0
            }
            
            page_count = len(pages)
            # Send preview photo with batch keyboard
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
                    "caption": f"✅ Halaman {page_count}/{MAX_BATCH_PAGES} diterima"
                },
                timeout=HTTP_TIMEOUT
            )
            
            if not response.ok:
                await send_message(chat_id, "❌ Gagal kirim preview.")
                return {"status": "error"}
            
            # Send/update batch keyboard
            await send_message(
                chat_id,
                f"📷 *Batch Scan Aktif* — {page_count}/{MAX_BATCH_PAGES} halaman\n\n"
                f"Kirim foto berikutnya, atau klik *Selesai* untuk gabung ke PDF.",
                reply_markup=_build_batch_keyboard(page_count)
            )
            
            return {"status": "success", "mode": "scan_batch", "pages": page_count}

        # Single scan mode (default): cache result and send with download buttons
        cache_id = str(uuid.uuid4())[:8]
        scan_cache[cache_id] = {
            "png": scanned_data,
            "ts": time.time(),
            "chat_id": chat_id
        }
        
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

        # Send download buttons
        await send_message(
            chat_id,
            "📥 *Download hasil scan:*",
            reply_markup=_build_download_keyboard(cache_id)
        )
        
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
        await send_message(
            chat_id,
            "📷 *Pilih Mode Scan*\n\n"
            "📷 *Scan Tunggal* — 1 foto → 1 hasil\n"
            "📚 *Scan Batch* — Beberapa foto → 1 PDF (maks 10 halaman)\n\n"
            "Silakan pilih mode di bawah:",
            reply_markup=_build_scan_mode_keyboard()
        )
        return {"status": "ok"}
    elif data == "scan_mode_single":
        user_sessions[chat_id] = {"mode": "scan", "pages": [], "started_at": time.time(), "message_id": 0}
        await send_message(
            chat_id,
            "📷 *Mode Scan Tunggal Aktif*\n\n"
            "Kirim satu foto untuk discan.\n\n"
            "💡 *Tips hasil terbaik:*\n"
            "• Background kontras dengan dokumen\n"
            "• Dokumen tidak terpotong\n"
            "• Cahaya merata, hindari bayangan\n"
            "• Kamera tegak lurus ke dokumen",
            reply_markup=_build_help_keyboard()
        )
        return {"status": "ok"}
    elif data == "scan_mode_batch":
        user_sessions[chat_id] = {"mode": "scan_batch", "pages": [], "started_at": time.time(), "message_id": 0}
        await send_message(
            chat_id,
            "📚 *Mode Scan Batch Aktif* — (maks 10 halaman)\n\n"
            "Kirim foto halaman dokumen satu per satu.\n"
            "Setelah semua foto terkirim, klik *✅ Selesai* untuk gabung ke PDF.\n\n"
            "💡 *TIPS UNTUK MODE BATCH:*\n"
            "• Pastikan pencahayaan dan sudut konsisten\n"
            "• Urutkan foto sesuai urutan halaman dokumen\n"
            "• Klik *➕ Tambah Halaman* setelah selesai jika masih ada dokumen",
            reply_markup=_build_batch_keyboard(0)
        )
        return {"status": "ok"}
    elif data.startswith("dl_png:"):
        return await handle_download_png(chat_id, data)
    elif data.startswith("dl_pdf:"):
        return await handle_download_pdf(chat_id, data)
    elif data == "batch_add":
        return await handle_batch_add(chat_id)
    elif data == "batch_finish":
        return await handle_batch_finish(chat_id)
    elif data == "batch_cancel":
        return await handle_batch_cancel(chat_id)
    elif data.startswith("batch_add_more:"):
        return await handle_batch_add_more(chat_id, data)

    return {"status": "ignored"}


async def handle_download_png(chat_id: int, data: str):
    """Handle download PNG callback."""
    cache_id = data.split(":", 1)[1]
    cached = scan_cache.get(cache_id)
    
    if not cached or cached["chat_id"] != chat_id:
        await send_message(chat_id, "❌ File tidak ditemukan atau sudah expired.")
        return {"status": "error"}
    
    await send_document(
        chat_id,
        cached["png"],
        filename="scanned.png",
        caption="📥 Hasil scan (PNG original quality)"
    )
    return {"status": "ok"}


async def handle_download_pdf(chat_id: int, data: str):
    """Handle download PDF callback - convert PNG to PDF or use cached batch PDF."""
    cache_id = data.split(":", 1)[1]
    cached = scan_cache.get(cache_id)
    
    if not cached or cached.get("chat_id") != chat_id:
        await send_message(chat_id, "❌ File tidak ditemukan atau sudah expired.")
        return {"status": "error"}
    
    # Use cached PDF if available (batch mode)
    pdf_bytes = cached.get("pdf")
    is_batch = cached.get("is_batch", False)
    
    if not pdf_bytes:
        try:
            pdf_bytes = png_to_pdf(cached["png"])
        except Exception:
            logger.exception("Gagal konversi PNG ke PDF")
            await send_message(chat_id, "❌ Gagal membuat PDF.")
            return {"status": "error"}
    
    filename = f"batch_scan_{len(cached.get('pages', [1]))}pages.pdf" if is_batch else "scanned.pdf"
    caption = "📄 Hasil scan (PDF)" if not is_batch else "📄 Hasil scan (PDF)"
    
    await send_document(
        chat_id,
        pdf_bytes,
        filename=filename,
        caption="📄 Hasil scan (PDF)"
    )
    return {"status": "ok"}


async def handle_batch_add(chat_id: int):
    """Handle batch add page - switch to batch mode."""
    session = user_sessions.get(chat_id, {})
    if session.get("mode") != "scan":
        await send_message(chat_id, "❌ Session tidak valid.")
        return {"status": "error"}
    
    if len(session.get("pages", [])) >= MAX_BATCH_PAGES:
        await send_message(chat_id, f"❌ Maksimal {MAX_BATCH_PAGES} halaman per batch.")
        return {"status": "error"}
    
    user_sessions[chat_id] = {
        "mode": "scan_batch",
        "pages": session.get("pages", []),
        "started_at": time.time(),
        "message_id": 0
    }
    
    page_count = len(user_sessions[chat_id]["pages"])
    await send_message(
        chat_id,
        f"📷 *Mode Batch Scan Aktif*\n\n"
        f"Halaman terkumpul: {page_count}/{MAX_BATCH_PAGES}\n\n"
        f"Kirim foto halaman selanjutnya.",
        reply_markup=_build_batch_keyboard(page_count)
    )
    return {"status": "ok"}


async def handle_batch_finish(chat_id: int):
    """Handle batch finish - combine all pages to PDF."""
    session = user_sessions.get(chat_id, {})
    if session.get("mode") != "scan_batch":
        await send_message(chat_id, "❌ Tidak ada batch scan aktif.")
        return {"status": "error"}
    
    pages = session.get("pages", [])
    if not pages:
        await send_message(chat_id, "❌ Belum ada halaman yang di-scan.")
        return {"status": "error"}
    
    try:
        pdf_bytes = combine_to_pdf(pages)
    except Exception:
        logger.exception("Gagal gabung halaman ke PDF")
        await send_message(chat_id, "❌ Gagal membuat PDF multi-halaman.")
        return {"status": "error"}
    
    # Cache PDF with all pages for potential resume
    existing_batch_id = session.get("batch_id")
    cache_id = existing_batch_id or str(uuid.uuid4())[:8]
    scan_cache[cache_id] = {
        "png": pages[0],
        "pages": pages,
        "pdf": pdf_bytes,
        "ts": time.time(),
        "chat_id": chat_id,
        "is_batch": True
    }
    
    # Update session to track finished batch (for resume via add_more)
    user_sessions[chat_id] = {
        "mode": "scan_batch_finished",
        "batch_id": cache_id,
        "started_at": time.time(),
        "message_id": 0
    }
    
    await send_document(
        chat_id,
        pdf_bytes,
        filename=f"batch_scan_{len(pages)}pages.pdf",
        caption=(
            f"✅ Batch selesai — {len(pages)} halaman digabung ke PDF.\n\n"
            f"Klik *➕ Tambah Halaman* jika masih ada dokumen yang tertinggal."
        ),
        reply_markup=_build_batch_finish_extended_keyboard(cache_id, len(pages))
    )
    return {"status": "ok"}


async def handle_batch_cancel(chat_id: int):
    """Handle batch cancel - clear session and cache."""
    session = user_sessions.get(chat_id, {})
    batch_id = session.get("batch_id")
    if batch_id and batch_id in scan_cache:
        del scan_cache[batch_id]
    if chat_id in user_sessions:
        del user_sessions[chat_id]
    await send_message(
        chat_id,
        "🗑️ Batch scan dibatalkan.",
        reply_markup=_build_inline_keyboard()
    )
    return {"status": "ok"}


async def handle_batch_add_more(chat_id: int, data: str):
    """Handle add more pages to a finished batch."""
    cache_id = data.split(":", 1)[1]
    cached = scan_cache.get(cache_id)
    
    if not cached or cached.get("chat_id") != chat_id or not cached.get("is_batch"):
        await send_message(chat_id, "❌ Batch tidak ditemukan atau sudah expired.")
        return {"status": "error"}
    
    existing_pages = cached.get("pages", [])
    if len(existing_pages) >= MAX_BATCH_PAGES:
        await send_message(chat_id, f"❌ Sudah mencapai batas {MAX_BATCH_PAGES} halaman. Buat batch baru.")
        return {"status": "error"}
    
    # Restore session with existing pages
    user_sessions[chat_id] = {
        "mode": "scan_batch",
        "pages": existing_pages,
        "batch_id": cache_id,
        "started_at": time.time(),
        "message_id": 0
    }
    
    await send_message(
        chat_id,
        f"📷 *Batch Dilanjutkan* — {len(existing_pages)}/{MAX_BATCH_PAGES} halaman\n\n"
        f"Anda punya {len(existing_pages)} halaman dari batch sebelumnya.\n"
        f"Kirim foto berikutnya, atau klik *Selesai* untuk gabung ke PDF.",
        reply_markup=_build_batch_keyboard(len(existing_pages))
    )
    return {"status": "ok"}


async def send_document(chat_id: int, file_bytes: bytes, filename: str, caption: str = "", reply_markup=None):
    """Kirim document ke Telegram."""
    files = {
        "document": (filename, file_bytes, "application/octet-stream")
    }
    payload: dict = {"chat_id": chat_id}
    if caption:
        payload["caption"] = caption  # type: ignore
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)  # type: ignore
    
    requests.post(
        f"{TELEGRAM_API}/sendDocument",
        files=files,
        data=payload,
        timeout=HTTP_TIMEOUT
    )


async def send_start_message(chat_id):
    """Kirim pesan menu utama dengan inline keyboard."""
    text = (
        "📄 *Bot Scan Dokumen*\n\n"
        "┌─ *PERINTAH* ──────────────────────┐\n"
        "│ `/scanner` ─ Mode scan dokumen    │\n"
        "│ `/help`    ─ Bantuan detail       │\n"
        "│ `/status'  ─ Cek mode & batas file│\n"
        "└───────────────────────────────────┘\n\n"
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
        "Pilih mode di menu utama:\n"
        "📷 *Scan Tunggal* — 1 foto → 1 hasil\n"
        "📚 *Scan Batch* — Beberapa foto → 1 PDF (maks 10 halaman)\n\n"
        "1️⃣ Klik tombol di bawah atau ketik `/scanner`\n"
        "2️⃣ Ambil foto dokumen:\n"
        "   ✅ Background kontras (hitam/putih)\n"
        "   ✅ Dokumen tidak terpotong\n"
        "   ✅ Cahaya merata, hindari bayangan\n"
        "   ❌ Jangan miring ekstrem (>30°)\n\n"
        "💡 *TIPS BATCH SCAN:*\n"
        "• Pastikan semua halaman konsisten (pencahayaan & sudut)\n"
        "• Urutkan foto sesuai urutan dokumen asli\n"
        "• Setelah klik Selesai, gunakan ➕ Tambah Halaman jika lupa\n"
        "• Scan berurutan supaya PDF sesuai halaman asli\n\n"
        "⚠️ *BATASAN:*\n"
        "• Maks 4 MB per foto (Telegram kompres otomatis)\n"
        "• Flat scan — belum auto-crop sudut\n"
        "• Hasil PNG → Telegram bisa kompres ulang"
    )
    await send_message(chat_id, text, reply_markup=_build_help_keyboard())
    return {"status": "ok"}


async def send_status_message(chat_id):
    """Kirim info status bot dengan inline keyboard."""
    session = user_sessions.get(chat_id, {})
    mode = session.get("mode", "belum dipilih")
    
    if mode == "scan":
        mode_text = "📷 Scan Tunggal aktif"
    elif mode == "scan_batch":
        pages = session.get("pages", [])
        mode_text = f"📚 Scan Batch aktif — {len(pages)}/{MAX_BATCH_PAGES} halaman"
    elif mode == "scan_batch_finished":
        batch_id = session.get("batch_id", "")
        cached = scan_cache.get(batch_id, {})
        pages = cached.get("pages", [])
        mode_text = f"✅ Batch selesai — {len(pages)} halaman"
    else:
        mode_text = "⏳ Belum dipilih"

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
    payload: dict = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": parse_mode
    }
    if reply_markup:
        payload["reply_markup"] = json.dumps(reply_markup)  # type: ignore

    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        data=payload,
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