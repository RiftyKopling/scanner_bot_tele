from io import BytesIO
from fpdf import FPDF
from PIL import Image


def _png_bytes_to_pil(png_bytes: bytes) -> Image.Image:
    """Convert PNG bytes to PIL Image."""
    return Image.open(BytesIO(png_bytes))


def png_to_pdf(png_bytes: bytes) -> bytes:
    """Convert single PNG to 1-page PDF.
    
    Args:
        png_bytes: PNG image bytes
        
    Returns:
        PDF bytes
    """
    img = _png_bytes_to_pil(png_bytes)
    width, height = img.size
    
    pdf = FPDF(unit="pt", format=(width, height))
    pdf.add_page()
    
    img_buffer = BytesIO()
    img.save(img_buffer, format="PNG")
    img_buffer.seek(0)
    
    pdf.image(img_buffer, x=0, y=0, w=width, h=height)
    
    output = BytesIO()
    pdf.output(output)
    return output.getvalue()


def combine_to_pdf(png_list: list[bytes]) -> bytes:
    """Combine multiple PNGs into a multi-page PDF.
    
    Args:
        png_list: List of PNG image bytes
        
    Returns:
        Multi-page PDF bytes
    """
    if not png_list:
        raise ValueError("Empty PNG list")
    
    first_img = _png_bytes_to_pil(png_list[0])
    width, height = first_img.size
    
    pdf = FPDF(unit="pt", format=(width, height))
    
    for png_bytes in png_list:
        img = _png_bytes_to_pil(png_bytes)
        w, h = img.size
        
        if w != width or h != height:
            img = img.resize((width, height), Image.Resampling.LANCZOS)
        
        pdf.add_page()
        
        img_buffer = BytesIO()
        img.save(img_buffer, format="PNG")
        img_buffer.seek(0)
        
        pdf.image(img_buffer, x=0, y=0, w=width, h=height)
    
    output = BytesIO()
    pdf.output(output)
    return output.getvalue()