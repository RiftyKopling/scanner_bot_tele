from fastapi import FastAPI, UploadFile, File
from fastapi.responses import StreamingResponse
from PIL import Image
from io import BytesIO

app = FastAPI()


@app.get("/")
def home():
    return {
        "status": "success",
        "message": "Image Compressor API is running"
    }


@app.post("/compress")
async def compress(file: UploadFile = File(...)):

    image = Image.open(file.file)

    # Ubah ke RGB agar bisa disimpan sebagai JPEG
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