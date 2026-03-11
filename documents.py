"""Document processing: convert any input to fax-ready TIFF-F (Group 3/4)."""

import os
import subprocess
import shutil
from pathlib import Path
from PIL import Image
from fpdf import FPDF
from config import TIFF_DIR

# Standard fax resolution: 204x196 DPI (fine mode), letter size = 1728x2287 pixels
FAX_WIDTH = 1728
FAX_HEIGHT = 2287
FAX_DPI = (204, 196)

SUPPORTED_TYPES = {".pdf", ".png", ".jpg", ".jpeg", ".tiff", ".tif", ".txt", ".bmp", ".gif"}


def to_tiff(input_path: str, output_name: str = None) -> str:
    """Convert any supported document to fax-ready TIFF-F (Group 4 compression).
    Returns path to the TIFF file."""
    path = Path(input_path)
    ext = path.suffix.lower()
    if ext not in SUPPORTED_TYPES:
        raise ValueError(f"Unsupported file type: {ext}. Supported: {SUPPORTED_TYPES}")

    out_name = output_name or f"{path.stem}_fax.tiff"
    out_path = TIFF_DIR / out_name

    if ext == ".pdf":
        return _pdf_to_tiff(path, out_path)
    elif ext == ".txt":
        return _text_to_tiff(path, out_path)
    else:
        return _image_to_tiff(path, out_path)


def _image_to_tiff(src: Path, dst: Path) -> str:
    """Convert image to fax-ready TIFF using Pillow."""
    img = Image.open(src)
    img = img.convert("L")  # grayscale
    img = _fit_to_fax_page(img)
    img = img.convert("1")  # 1-bit black/white (fax standard)
    img.save(str(dst), format="TIFF", compression="group4",
             dpi=FAX_DPI)
    return str(dst)


def _pdf_to_tiff(src: Path, dst: Path) -> str:
    """Convert PDF to TIFF. Uses Ghostscript if available, falls back to Pillow."""
    gs = shutil.which("gs") or shutil.which("ghostscript")
    if gs:
        subprocess.run([
            gs, "-q", "-dNOPAUSE", "-dBATCH", "-sDEVICE=tiffg4",
            f"-r{FAX_DPI[0]}x{FAX_DPI[1]}",
            f"-sOutputFile={dst}",
            str(src)
        ], check=True, capture_output=True)
        return str(dst)

    # Fallback: try Pillow (limited PDF support)
    try:
        img = Image.open(src)
        img = img.convert("L")
        img = _fit_to_fax_page(img)
        img = img.convert("1")
        img.save(str(dst), format="TIFF", compression="group4", dpi=FAX_DPI)
        return str(dst)
    except Exception:
        raise RuntimeError(
            "PDF conversion requires Ghostscript. Install: sudo apt install ghostscript")


def _text_to_tiff(src: Path, dst: Path) -> str:
    """Convert text file to TIFF via intermediate PDF."""
    text = src.read_text(errors="replace")
    pdf_path = dst.with_suffix(".pdf")
    _text_to_pdf(text, str(pdf_path))
    result = _pdf_to_tiff(pdf_path, dst)
    pdf_path.unlink(missing_ok=True)
    return result


def _text_to_pdf(text: str, output_path: str):
    """Convert plain text to a PDF."""
    pdf = FPDF()
    pdf.set_auto_page_break(auto=True, margin=20)
    pdf.add_page()
    pdf.set_font("Courier", size=10)
    for line in text.split("\n"):
        pdf.cell(0, 5, line[:100], new_x="LMARGIN", new_y="NEXT")
    pdf.output(output_path)


def _fit_to_fax_page(img: Image.Image) -> Image.Image:
    """Resize image to fit fax page dimensions while maintaining aspect ratio."""
    ratio = min(FAX_WIDTH / img.width, FAX_HEIGHT / img.height)
    new_w = int(img.width * ratio)
    new_h = int(img.height * ratio)
    img = img.resize((new_w, new_h), Image.LANCZOS)

    # Center on white fax-size page
    page = Image.new("L", (FAX_WIDTH, FAX_HEIGHT), 255)
    x = (FAX_WIDTH - new_w) // 2
    y = (FAX_HEIGHT - new_h) // 2
    page.paste(img, (x, y))
    return page


def generate_cover_page(to_name: str, to_number: str, from_name: str,
                        from_number: str, message: str = "",
                        pages: int = 0) -> str:
    """Generate a fax cover page as TIFF."""
    pdf = FPDF()
    pdf.add_page()
    pdf.set_font("Helvetica", "B", 24)
    pdf.cell(0, 20, "FAX TRANSMISSION", align="C", new_x="LMARGIN", new_y="NEXT")

    pdf.line(10, pdf.get_y(), 200, pdf.get_y())
    pdf.ln(10)

    pdf.set_font("Helvetica", size=12)
    fields = [
        ("TO:", f"{to_name}  {to_number}"),
        ("FROM:", f"{from_name}  {from_number}"),
        ("DATE:", __import__("datetime").datetime.now().strftime("%Y-%m-%d %H:%M")),
        ("PAGES:", str(pages) if pages else "See attached"),
    ]
    for label, value in fields:
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(30, 8, label)
        pdf.set_font("Helvetica", size=12)
        pdf.cell(0, 8, value, new_x="LMARGIN", new_y="NEXT")

    if message:
        pdf.ln(10)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(5)
        pdf.set_font("Helvetica", "B", 12)
        pdf.cell(0, 8, "MESSAGE:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", size=11)
        pdf.multi_cell(0, 6, message)

    cover_pdf = str(TIFF_DIR / "_cover.pdf")
    cover_tiff = str(TIFF_DIR / "_cover.tiff")
    pdf.output(cover_pdf)
    _pdf_to_tiff(Path(cover_pdf), Path(cover_tiff))
    Path(cover_pdf).unlink(missing_ok=True)
    return cover_tiff
