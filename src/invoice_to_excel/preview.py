"""Page images for the review screen, so a person can compare the invoice with what was read."""

from __future__ import annotations

import io
from pathlib import Path

from PIL import Image, ImageChops, ImageOps

MAX_PAGES = 3


def preview_images(file_name: str, data: bytes, width: int = 1100) -> list[Image.Image]:
    """First pages of a PDF, or the photo itself (rotated upright). Empty list if unreadable."""
    try:
        if Path(file_name).suffix.lower() == ".pdf":
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(data)
            pages = []
            for i in range(min(len(pdf), MAX_PAGES)):
                page = pdf[i]
                scale = width / page.get_width()
                pages.append(_trim_bottom(page.render(scale=scale).to_pil().convert("RGB")))
            return pages
        img = ImageOps.exif_transpose(Image.open(io.BytesIO(data))).convert("RGB")
        if img.width > width:
            img = img.resize((width, round(img.height * width / img.width)))
        return [img]
    except Exception:  # noqa: BLE001 - a missing preview must never break the review page
        return []


def _trim_bottom(img: Image.Image, margin: int = 30) -> Image.Image:
    """Drop the empty white area below the last printed line of a PDF page."""
    diff = ImageChops.difference(img, Image.new("RGB", img.size, "white")).convert("L")
    box = diff.point(lambda v: 255 if v > 24 else 0).getbbox()
    if not box:
        return img
    return img.crop((0, 0, img.width, min(img.height, box[3] + margin)))
