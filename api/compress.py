from io import BytesIO
from PIL import Image, UnidentifiedImageError

# Batas ukuran file: 4 MB
MAX_FILE_SIZE = 4 * 1024 * 1024


def compress_image(image_bytes: bytes, quality: int = 40) -> bytes:
    """Kompres gambar ke JPEG dengan kualitas tetap (default 40%).
    
    Args:
        image_bytes: Bytes gambar input
        quality: Kualitas JPEG 1-100 (default 40)
        
    Returns:
        Bytes gambar JPEG terkompres
        
    Raises:
        ValueError: Jika input tidak valid atau melebihi batas ukuran
    """
    if len(image_bytes) > MAX_FILE_SIZE:
        raise ValueError(
            f"Ukuran file melebihi batas 4 MB ({len(image_bytes) / (1024 * 1024):.2f} MB)"
        )
    
    try:
        image = Image.open(BytesIO(image_bytes))
    except UnidentifiedImageError:
        raise ValueError("File bukan gambar yang valid atau format tidak didukung")
    
    if image.mode != "RGB":
        image = image.convert("RGB")
    
    output = BytesIO()
    image.save(output, format="JPEG", quality=quality, optimize=True)
    
    return output.getvalue()