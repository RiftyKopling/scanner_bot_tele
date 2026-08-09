import os
import requests
from io import BytesIO

from fastapi import FastAPI, UploadFile, File, Request
from fastapi.responses import StreamingResponse, JSONResponse
from PIL import Image


app = FastAPI()

BOT_TOKEN = os.environ["TELEGRAM_BOT_TOKEN"]

TELEGRAM_API = f"https://api.telegram.org/bot{BOT_TOKEN}"
TELEGRAM_FILE_API = f"https://api.telegram.org/file/bot{BOT_TOKEN}"


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

    # Pastikan ada message
    if "message" not in update:
        return {"status": "ignored"}

    message = update["message"]

    chat_id = message["chat"]["id"]

    # Pastikan user mengirim foto
    if "photo" not in message:

        send_message(
            chat_id,
            "📷 Silakan kirim gambar untuk dikompres."
        )

        return {"status": "ok"}

    # Ambil foto dengan resolusi terbesar
    photo = message["photo"][-1]

    file_id = photo["file_id"]

    # Ambil informasi file dari Telegram
    file_info = requests.get(
        f"{TELEGRAM_API}/getFile",
        params={
            "file_id": file_id
        }
    ).json()

    file_path = file_info["result"]["file_path"]

    # Download gambar
    image_response = requests.get(
        f"{TELEGRAM_FILE_API}/{file_path}"
    )

    image_data = BytesIO(image_response.content)

    # Buka gambar
    image = Image.open(image_data)

    if image.mode != "RGB":
        image = image.convert("RGB")

    # Kompres
    output = BytesIO()

    image.save(
        output,
        format="JPEG",
        quality=40,
        optimize=True
    )

    output.seek(0)

    # Kirim kembali ke Telegram
    requests.post(
        f"{TELEGRAM_API}/sendDocument",
        files={
            "document": (
                "compressed.jpg",
                output,
                "image/jpeg"
            )
        },
        data={
            "chat_id": chat_id,
            "caption": "✅ Gambar berhasil dikompres!"
        }
    )

    return {
        "status": "success"
    }


def send_message(chat_id, text):

    requests.post(
        f"{TELEGRAM_API}/sendMessage",
        data={
            "chat_id": chat_id,
            "text": text
        }
    )