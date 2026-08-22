import cv2
import numpy as np


def scan_image(image_bytes: bytes) -> bytes:
    """Ubah foto Telegram menjadi bersih:
    1. Decode ke OpenCV
    2. Grayscale (cvtColor)
    3. Reduksi noise (GaussianBlur)
    4. Adaptive threshold -> hitam-putih
    5. Encode kembali ke JPEG dan kembalikan bytes.
    """
    # 1. Decode bytes gambar ke array OpenCV
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError("Gambar tidak valid atau gagal di-decode")

    # 2. Konversi ke grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 3. Reduksi noise dengan Gaussian blur
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)

    # 4. Adaptive threshold -> hasil hitam-putih bersih
    scanned = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        2,
    )

    # 5. Encode kembali ke JPEG bytes
    ok, enc = cv2.imencode(".jpg", scanned)
    if not ok:
        raise RuntimeError("Gagal meng-encode gambar hasil scan")

    return enc.tobytes()
