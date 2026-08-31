import cv2  # library pengolahan gambar OpenCV
import numpy as np  # library numerik untuk operasi array

# konstanta tinggi maksimal gambar setelah di-resize
tinggi_maks = 800  # batas maksimum tinggi dalam pixel


def urutkan_titik(pts):
    """Urutkan 4 titik jadi: top-left, top-right, bottom-right, bottom-left."""
    rect = np.zeros((4, 2), dtype="float32")
    s = pts.sum(axis=1)
    rect[0] = pts[np.argmin(s)]
    rect[2] = pts[np.argmax(s)]
    diff = np.diff(pts, axis=1)
    rect[1] = pts[np.argmin(diff)]
    rect[3] = pts[np.argmax(diff)]
    return rect


def four_point_transform(image, pts):
    """Melakukan transformasi perspektif untuk meratakan gambar."""
    rect = urutkan_titik(pts)
    (tl, tr, br, bl) = rect

    widthA = np.sqrt(((br[0] - bl[0]) ** 2) + ((br[1] - bl[1]) ** 2))
    widthB = np.sqrt(((tr[0] - tl[0]) ** 2) + ((tr[1] - tl[1]) ** 2))
    maxWidth = max(int(widthA), int(widthB))

    heightA = np.sqrt(((tr[0] - br[0]) ** 2) + ((tr[1] - br[1]) ** 2))
    heightB = np.sqrt(((tl[0] - bl[0]) ** 2) + ((tl[1] - bl[1]) ** 2))
    maxHeight = max(int(heightA), int(heightB))

    dst = np.array([
        [0, 0],
        [maxWidth - 1, 0],
        [maxWidth - 1, maxHeight - 1],
        [0, maxHeight - 1]], dtype="float32")

    M = cv2.getPerspectiveTransform(rect, dst)
    warped = cv2.warpPerspective(image, M, (maxWidth, maxHeight))
    return warped


def get_odd_size(lebar, pembagi):
    """Hitung ukuran kernel ganjil untuk operasi morfologi."""
    ukuran = max(3, lebar // pembagi)
    return ukuran + 1 if ukuran % 2 == 0 else ukuran


def scan_image(image_bytes: bytes) -> bytes:
    """Ubah foto Telegram menjadi bersih (mirip CamScanner):
    1. Decode ke OpenCV
    2. HSV masking + morfologi untuk isolasi dokumen
    3. Canny edge detection + dilasi
    4. Cari kontur terbesar -> minAreaRect -> 4 sudut
    5. Perspective transform (warping)
    6. Enhancement (CLAHE, contrast, bilateral filter, detail enhance)
    7. Encode kembali ke PNG dan kembalikan bytes.
    """
    # 1. Decode bytes gambar ke array OpenCV
    nparr = np.frombuffer(image_bytes, np.uint8)
    img = cv2.imdecode(nparr, cv2.IMREAD_COLOR)

    if img is None:
        raise ValueError("Gambar tidak valid atau gagal di-decode")

    img_asli = img.copy()

    # Resize jika terlalu besar
    h_asli, w_asli = img.shape[:2]
    rasio = 1.0
    if h_asli > tinggi_maks:
        rasio = img.shape[0] / float(tinggi_maks)
        img = cv2.resize(img, (int(img.shape[1] / rasio), tinggi_maks))

    # 2. Pre-processing: HSV masking untuk isolasi dokumen (putih/terang)
    hsv = cv2.cvtColor(img, cv2.COLOR_BGR2HSV)
    # Blur adaptif berdasarkan lebar gambar
    blur_ksize = max(3, img.shape[1] // 100)
    if blur_ksize % 2 == 0:
        blur_ksize += 1
    hsv = cv2.blur(hsv, (blur_ksize, blur_ksize))

    # Mask area putih/terang (dokumen biasanya putih)
    # H: 0-180, S: 0-60 (low saturation = putih/abu), V: 150-255 (terang)
    thresh_inrange = 255 - cv2.inRange(hsv, (0, 0, 150), (180, 60, 255))

    # 3. Operasi morfologi: OPEN (hilang noise kecil) + CLOSE (sambung tepi putus)
    w = img.shape[1]
    k_open = cv2.getStructuringElement(cv2.MORPH_RECT, (get_odd_size(w, 150), get_odd_size(w, 150)))
    k_close = cv2.getStructuringElement(cv2.MORPH_RECT, (get_odd_size(w, 80), get_odd_size(w, 80)))

    thresh = cv2.morphologyEx(thresh_inrange, cv2.MORPH_OPEN, k_open, iterations=1)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, k_close, iterations=1)

    # 4. Deteksi tepi Canny + dilasi tipis
    edges = cv2.Canny(thresh, 50, 100, apertureSize=7)
    dilate_ksize = max(3, img.shape[1] // 50)
    if dilate_ksize % 2 == 0:
        dilate_ksize += 1
    k_dilate = cv2.getStructuringElement(cv2.MORPH_RECT, (dilate_ksize, dilate_ksize))
    edges_dilated = cv2.morphologyEx(edges, cv2.MORPH_DILATE, k_dilate, iterations=1)

    # 5. Cari kontur batas dokumen
    contours, _ = cv2.findContours(edges_dilated, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_NONE)

    titik_sudut = None
    if len(contours) > 0:
        # Ambil kontur terbesar (asumsi ini adalah dokumennya)
        main_contour = max(contours, key=len)
        # minAreaRect memberikan rotated rectangle yang tight fit ke kontur
        bbox = cv2.minAreaRect(main_contour)
        box = cv2.boxPoints(bbox)
        box = np.int32(box)  # ubah ke integer
        titik_sudut = box.reshape(4, 2)

    # Fallback: pakai seluruh frame
    if titik_sudut is None:
        h, w = img.shape[:2]
        titik_sudut = np.array([[0, 0], [w, 0], [w, h], [0, h]], dtype="float32")

    # 6. Perspective transform (warping) - gunakan gambar asli untuk kualitas terbaik
    titik_sudut_asli = titik_sudut.astype("float32") * rasio
    warped = four_point_transform(img_asli, titik_sudut_asli)

    # 7. Enhancement pipeline (mirip CamScanner)
    # CLAHE untuk brightness/contrast lokal
    clahe = cv2.createCLAHE(clipLimit=1.5, tileGridSize=(16, 16))
    warped_hsv = cv2.cvtColor(warped, cv2.COLOR_BGR2HSV)
    warped_hsv[:, :, 2] = clahe.apply(warped_hsv[:, :, 2])
    enhanced = cv2.cvtColor(warped_hsv, cv2.COLOR_HSV2BGR)

    # Contrast & brightness adjustment
    enhanced = np.uint8(np.clip(1.7 * np.float32(enhanced) - 100, 0, 255))
    enhanced = np.ascontiguousarray(enhanced)

    # Bilateral filter untuk smoothing sambil jaga tepi
    enhanced = cv2.bilateralFilter(enhanced, 9, 75, 75)

    # Detail enhance untuk sharpness
    enhanced = cv2.detailEnhance(enhanced, sigma_s=3, sigma_r=0.15)

    # 8. Convert ke grayscale dan adaptive threshold untuk hasil hitam-putih bersih
    gray = cv2.cvtColor(enhanced, cv2.COLOR_BGR2GRAY)
    final = cv2.adaptiveThreshold(
        gray, 255, cv2.ADAPTIVE_THRESH_GAUSSIAN_C, cv2.THRESH_BINARY, 25, 7
    )

    # 9. Encode menjadi PNG bytes
    ok, enc = cv2.imencode(".png", final)
    if not ok:
        raise RuntimeError("Gagal meng-encode gambar hasil scan")

    return enc.tobytes()
