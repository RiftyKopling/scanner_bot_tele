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
    
    # jika resolusi gambar terlalu besar turunkan 
    h, w = img.shape[:2]
    if w > 1600:
        scale = 1600 / w
        img = cv2.resize(img, (int(w*scale), int(h*scale)))

    # 2. Konversi ke grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    
    # Normalisasi pencahayaan dulu
    bg = cv2.GaussianBlur(gray, (55, 55), 0)
    normalized = cv2.divide(gray, bg, scale=255)
    
    # 3. Reduksi noise dengan Gaussian blur
    blurred = cv2.GaussianBlur(normalized, (5, 5), 0)

    # 4. Adaptive threshold -> hasil hitam-putih bersih
    scanned = cv2.adaptiveThreshold(
        blurred,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        11,
        5,
    )
    
    # Cleanup noise kecil
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2, 2))
    scanned = cv2.morphologyEx(scanned, cv2.MORPH_OPEN, kernel)

    # 5. Encode menjadi PNG bytes
    ok, enc = cv2.imencode(".png", scanned)
    if not ok:
        raise RuntimeError("Gagal meng-encode gambar hasil scan")

    return enc.tobytes()
