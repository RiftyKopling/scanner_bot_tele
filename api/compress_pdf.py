import io
import warnings
import pymupdf  # PyMuPDF
from PIL import Image

# Batas ukuran file: 4 MB (sama dengan compress.py)
MAX_FILE_SIZE = 4 * 1024 * 1024

# Skip thresholds
SKIP_MIN_DIMENSION = 400      # px — di bawah ini biasanya bukan halaman dokumen full
SKIP_MIN_FILE_SIZE = 50 * 1024  # 50 KB — sudah cukup kecil untuk hasil scan
SKIP_IF_ALREADY_JPEG_QUALITY = True  # cek ekstensi 

# Tingkat kompresi aktif (pakai compression_level, bukan quality tetap)
COMPRESSION_LEVELS = {
    "low":    {"max_dimension": 2000, "quality": 75},
    "medium": {"max_dimension": 1600, "quality": 60},  # match scanner max_width
    "high":   {"max_dimension": 1200, "quality": 45},
}


def compress_pdf(
    pdf_bytes: bytes,
    compression_level: str = "medium",  # "low" | "medium" | "high"
    quality: int | None = None          # deprecated alias untuk backward compat
) -> bytes:
    """Kompres PDF dengan mengompres gambar di dalamnya ke JPEG secara adaptif.
    
    Args:
        pdf_bytes: Bytes file PDF input
        compression_level: Tingkat kompresi ("low" | "medium" | "high")
        quality: DEPRECATED — gunakan compression_level. Jika diberikan, 
                 akan dipetakan ke compression_level terdekat.
        
    Returns:
        Bytes PDF terkompres
        
    Raises:
        ValueError: Jika input bukan PDF valid, melebihi 4 MB, atau gagal diproses
    """
    # Backward compatibility: quality int -> compression_level
    if quality is not None:
        if quality >= 70:
            compression_level = "low"
        elif quality >= 50:
            compression_level = "medium"
        else:
            compression_level = "high"
        warnings.warn(
            "'quality' parameter deprecated, use 'compression_level' instead",
            DeprecationWarning,
            stacklevel=2
        )
    
    if compression_level not in COMPRESSION_LEVELS:
        raise ValueError(f"compression_level tidak valid: {compression_level}. Pilih: low, medium, high")
    
    level = COMPRESSION_LEVELS[compression_level]
    max_dimension = level["max_dimension"]
    jpeg_quality = level["quality"]
    
    if len(pdf_bytes) > MAX_FILE_SIZE:
        raise ValueError(
            f"Ukuran file melebihi batas 4 MB ({len(pdf_bytes) / (1024 * 1024):.2f} MB)"
        )
    
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:
        raise ValueError(f"File bukan PDF yang valid: {e}")
    
    if doc.page_count == 0:
        doc.close()
        raise ValueError("PDF tidak memiliki halaman")
    
    processed_xrefs = set()
    
    for page_num in range(doc.page_count):
        page = doc[page_num]
        images = page.get_images()
        
        for img in images:
            xref = img[0]
            
            if xref in processed_xrefs:
                continue
            processed_xrefs.add(xref)
            
            # ── PRE-FILTER: cek apakah sudah JPEG ─────────────────
            if SKIP_IF_ALREADY_JPEG_QUALITY:
                filter_val = doc.xref_get_key(xref, "Filter")
                if filter_val and "/DCTDecode" in filter_val:
                    continue
            
            # Ekstrak untuk cek ukuran file
            try:
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
            except Exception:
                continue
            
            # Skip jika file sudah kecil
            if len(image_bytes) < SKIP_MIN_FILE_SIZE:
                continue
            
            # Decode untuk cek dimensi
            try:
                pil_img = Image.open(io.BytesIO(image_bytes))
            except Exception:
                continue
            
            # Skip jika dimensi kecil
            if max(pil_img.size) < SKIP_MIN_DIMENSION:
                continue
            
            # ── MODE HANDLING ────────────────────────────────────
            if pil_img.mode in ("RGBA", "LA", "PA"):
                # Transparansi → RGB dengan background putih
                background = Image.new("RGB", pil_img.size, (255, 255, 255))
                alpha = pil_img.split()[-1]
                background.paste(pil_img, mask=alpha)
                pil_img = background
                target_mode = "RGB"
            elif pil_img.mode == "CMYK":
                pil_img = pil_img.convert("RGB")
                target_mode = "RGB"
            elif pil_img.mode == "P":
                # Palette → cek apakah grayscale
                palette = pil_img.getpalette()
                if palette:
                    is_gray = all(
                        palette[i] == palette[i + 1] == palette[i + 2]
                        for i in range(0, len(palette), 3)
                    )
                    pil_img = pil_img.convert("L" if is_gray else "RGB")
                    target_mode = "L" if is_gray else "RGB"
                else:
                    pil_img = pil_img.convert("RGB")
                    target_mode = "RGB"
            elif pil_img.mode == "L":
                target_mode = "L"  # Pertahankan grayscale
            else:
                pil_img = pil_img.convert("RGB")
                target_mode = "RGB"
            
            # ── DOWNSAMPLING ─────────────────────────────────────
            if max(pil_img.size) > max_dimension:
                pil_img.thumbnail((max_dimension, max_dimension), Image.LANCZOS)
            
            # ── JPEG ENCODE ──────────────────────────────────────
            img_byte_arr = io.BytesIO()
            pil_img.save(img_byte_arr, format="JPEG", quality=jpeg_quality, optimize=True)
            compressed_bytes = img_byte_arr.getvalue()
            
            # ── REPLACE IF SMALLER ───────────────────────────────
            if len(compressed_bytes) < len(image_bytes):
                doc.update_stream(xref, compressed_bytes)
                doc.xref_set_key(xref, "Filter", "/DCTDecode")
                colorspace = "/DeviceGray" if target_mode == "L" else "/DeviceRGB"
                doc.xref_set_key(xref, "ColorSpace", colorspace)
    
    # Simpan ke bytes dengan garbage collection penuh
    output_bytes = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    
    return output_bytes