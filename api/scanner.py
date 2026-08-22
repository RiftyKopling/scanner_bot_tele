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
        
    # ubah jadi grayscale
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)

    # 1. Illumination correction
    kernel = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (55, 55))
    background = cv2.morphologyEx(gray, cv2.MORPH_CLOSE, kernel)
    diff = cv2.subtract(background, gray)
    normalized = 255 - diff
    
    # 2. Noise reduction tapi pertahankan tepi
    smoothed = cv2.bilateralFilter(normalized, 9, 75, 75)
    
    # 3.  Adaptive threshold -> hasil hitam-putih bersih
    scanned = cv2.adaptiveThreshold(
        smoothed,
        255,
        cv2.ADAPTIVE_THRESH_GAUSSIAN_C,
        cv2.THRESH_BINARY,
        51,
        7,
    )
    
    # test otsu thresholding
    # ret, scanned = cv2.threshold(
    #     smoothed, 0, 255,
    #     cv2.THRESH_BINARY + cv2.THRESH_OTSU
    # )
    
    # 4. Cleanup akhir
    final = cv2.medianBlur(scanned, 3)

    # 5. Encode menjadi PNG bytes
    ok, enc = cv2.imencode(".png", final)
    if not ok:
        raise RuntimeError("Gagal meng-encode gambar hasil scan")

    return enc.tobytes()
