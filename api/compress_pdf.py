import io
import pymupdf  # PyMuPDF
from PIL import Image

# Batas ukuran file: 4 MB (sama dengan compress.py)
MAX_FILE_SIZE = 4 * 1024 * 1024

COMPRESSION_LEVELS = {
    "low":    {"max_dimension": 2000, "quality": 75},
    "medium": {"max_dimension": 1600, "quality": 60},
    "high":   {"max_dimension": 1200, "quality": 45},
    "not":    {"max_dimension": 1000, "quality": 100}
}


def compress_pdf(pdf_bytes: bytes, quality: int = 40) -> bytes:
    """Kompres PDF dengan mengompres gambar di dalamnya ke JPEG.
    
    Args:
        pdf_bytes: Bytes file PDF input
        quality: Kualitas JPEG 1-100 (default 40)
        
    Returns:
        Bytes PDF terkompres
        
    Raises:
        ValueError: Jika input bukan PDF valid, melebihi 4 MB, atau gagal diproses
    """
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
            
            try:
                base_image = doc.extract_image(xref)
                image_bytes = base_image["image"]
            except Exception:
                continue
            
            try:
                pil_img = Image.open(io.BytesIO(image_bytes))
            except Exception:
                continue
            
            # Tangani transparansi
            if pil_img.mode in ("RGBA", "LA"):
                background = Image.new("RGB", pil_img.size, (255, 255, 255))
                background.paste(pil_img, mask=pil_img.split()[-1])
                pil_img = background
            elif pil_img.mode != "RGB":
                pil_img = pil_img.convert("RGB")
                
            # cek besar dimensi untuk menentukan tingkat kualitas gambar
            
            # Kompres ke JPEG
            img_byte_arr = io.BytesIO()
            pil_img.save(img_byte_arr, format="JPEG", quality=quality, optimize=True)
            compressed_bytes = img_byte_arr.getvalue()
            
            # Hanya timpa jika lebih kecil
            if len(compressed_bytes) < len(image_bytes):
                doc.update_stream(xref, compressed_bytes)
                doc.xref_set_key(xref, "Filter", "/DCTDecode")
                doc.xref_set_key(xref, "ColorSpace", "/DeviceRGB")
    
    # Simpan ke bytes
    output_bytes = doc.tobytes(garbage=4, deflate=True)
    doc.close()
    
    return output_bytes