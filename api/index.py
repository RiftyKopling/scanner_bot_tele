import os
import requests
from io import BytesIO

from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import StreamingResponse
from PIL import Image


app = FastAPI()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"

# Batas ukuran file: 4 MB
MAX_FILE_SIZE = 4 * 1024 * 1024


@app.get("/api")
def home():
    return {
        "status": "success",
        "message": "Telegram Image Compressor API is running"
    }


@app.post("/api/compress")
async def compress(file: UploadFile = File(...)):

    image = Image.open(file.file)

    if image.mode != "RGB":
        image = image.convert("RGB")

    output = BytesIO()

    image.save(
        output,
        format="JPEG",
        quality=40,
        optimize=True
    )

    output.seek(0)

    return StreamingResponse(
        output,
        media_type="image/jpeg"
    )


@app.post("/api/webhook")
async def webhook(request: Request):

    update = await request.json()

    if "message" not in update:
        return {"status": "ignored"}

    message = update["message"]
    chat_id = message["chat"]["id"]

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
        timeout=30
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
        timeout=30
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
    # 4. Buka gambar
    # ==========================

    try:

        image = Image.open(
            BytesIO(original_data)
        )

    except Exception:

        send_message(
            chat_id,
            "❌ File yang dikirim bukan gambar yang valid."
        )

        return {"status": "error"}

    # ==========================
    # 5. Konversi RGB
    # ==========================

    if image.mode != "RGB":
        image = image.convert("RGB")

    # ==========================
    # 6. Kompres
    # ==========================

    output = BytesIO()

    image.save(
        output,
        format="JPEG",
        quality=40,
        optimize=True
    )

    output.seek(0)

    compressed_data = output.getvalue()

    compressed_size = len(compressed_data)

    # ==========================
    # 7. Hitung penghematan
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
    # 8. Kirim hasil
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
        timeout=30
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


def send_message(chat_id, text):

    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text
        },
        timeout=30
    )