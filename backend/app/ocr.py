"""Local OCR for scanned statement pages, using the Tesseract engine (installed in the Docker image).

Statement images never leave the server: no cloud OCR or AI service sees them.

Pipeline per page: render the PDF page to a greyscale image (pypdfium2) -> straighten small scan tilts
-> Tesseract word boxes (TSV) -> words in PDF points, in the same shape pdfplumber produces, so the
statement parser treats scanned and digital pages alike.

Safety: rendering is capped in pixels (a PDF can declare an enormous page), each Tesseract call has a
timeout, and a semaphore limits how many pages are OCR'd at once per process (OCR is CPU-heavy).
"""
from __future__ import annotations

import csv
import io
import logging
import os
import shutil
import subprocess
import threading
from functools import lru_cache

from app.config import get_settings

log = logging.getLogger("smecopilot.ocr")

DPI = 300
MAX_PIXELS_LONG_SIDE = 4200        # about A4 at 360 dpi; bigger declared pages are scaled down
# Tesseract's confidence is poorly calibrated for figures in tables: on a test scan it read "12,450.50"
# correctly at confidence 10. Words are kept regardless; the statement parser's strict number patterns and
# the running-balance check decide what is trusted. Only -1 (not a word) is dropped.
MIN_WORD_CONFIDENCE = 0
PAGE_TIMEOUT_S = 90

_slots = threading.BoundedSemaphore(max(1, get_settings().ocr_concurrency))


class OcrError(RuntimeError):
    pass


@lru_cache
def available() -> bool:
    """True when OCR is enabled and the Tesseract binary runs."""
    st = get_settings()
    if not st.ocr_enabled:
        return False
    cmd = shutil.which(st.tesseract_cmd) or (st.tesseract_cmd if os.path.isfile(st.tesseract_cmd) else None)
    if not cmd:
        log.info("Tesseract not found (%s): scanned PDF statements cannot be read", st.tesseract_cmd)
        return False
    try:
        subprocess.run([cmd, "--version"], capture_output=True, timeout=10, check=True)
    except (OSError, subprocess.SubprocessError):
        log.warning("Tesseract at %s does not run: scanned PDF statements cannot be read", cmd)
        return False
    return True


def ocr_pdf_pages(content: bytes, password: str, page_numbers: list[int]) -> dict[int, list[dict]]:
    """OCR the given 1-based pages. -> {page number: [word dicts with x0, x1, top, bottom, text, conf]}."""
    import pypdfium2 as pdfium

    try:
        pdf = pdfium.PdfDocument(content, password=password or None)
    except pdfium.PdfiumError as e:
        raise OcrError("Could not open the PDF for OCR.") from e
    out: dict[int, list[dict]] = {}
    try:
        for number in page_numbers:
            page = pdf[number - 1]
            width_pt, height_pt = page.get_size()
            scale = min(DPI / 72, MAX_PIXELS_LONG_SIDE / max(width_pt, height_pt, 1))
            image = page.render(scale=scale, grayscale=True).to_pil().convert("L")
            page.close()
            image, _ = deskew(clean(image))
            if not _slots.acquire(timeout=120):
                raise OcrError("The server is busy reading other statements. Try again in a minute.")
            try:
                words = tesseract_words(image)
            finally:
                _slots.release()
            out[number] = [{**w, "x0": w["x0"] / scale, "x1": w["x1"] / scale,
                            "top": w["top"] / scale, "bottom": w["bottom"] / scale} for w in words]
    finally:
        pdf.close()
    return out


def tesseract_words(image) -> list[dict]:
    """Word boxes in image pixels."""
    st = get_settings()
    buf = io.BytesIO()
    image.save(buf, format="PNG")
    # psm 6: one uniform block of text - keeps table rows together better than automatic layout.
    cmd = [st.tesseract_cmd, "stdin", "stdout", "-l", st.ocr_languages, "--psm", "6",
           "-c", "preserve_interword_spaces=1", "tsv"]
    env = {**os.environ, "OMP_THREAD_LIMIT": "1"}   # concurrency is limited by the semaphore instead
    try:
        proc = subprocess.run(cmd, input=buf.getvalue(), capture_output=True, timeout=PAGE_TIMEOUT_S, env=env)
    except subprocess.TimeoutExpired:
        raise OcrError("Reading a scanned page took too long. Try a clearer or smaller scan.") from None
    if proc.returncode != 0:
        log.error("Tesseract failed: %s", proc.stderr.decode(errors="replace")[:500])
        raise OcrError("OCR failed on this file.")
    words = []
    for row in csv.DictReader(io.StringIO(proc.stdout.decode("utf-8", errors="replace")), delimiter="\t",
                              quoting=csv.QUOTE_NONE):
        text = (row.get("text") or "").strip()
        try:
            conf = float(row.get("conf") or -1)
        except ValueError:
            continue
        if row.get("level") != "5" or not text or conf < MIN_WORD_CONFIDENCE:
            continue
        left, top, w, h = (int(row[k]) for k in ("left", "top", "width", "height"))
        words.append({"text": text, "x0": left, "x1": left + w, "top": top, "bottom": top + h, "conf": conf})
    return words


def clean(image):
    """Remove scanner speckle (3x3 median) and binarise with Otsu's threshold.

    Measured on a degraded test scan: without the median filter Tesseract recovered 4 of 16 dates and
    amounts; with it, 16 of 16. Otsu keeps that and makes OCR faster.
    """
    import numpy as np
    from PIL import ImageFilter

    image = image.filter(ImageFilter.MedianFilter(3))
    pixels = np.asarray(image, dtype=np.uint8)
    hist = np.bincount(pixels.ravel(), minlength=256).astype(np.float64)
    levels = np.arange(256)
    w_back = np.cumsum(hist)
    w_fore = w_back[-1] - w_back
    m_back = np.cumsum(hist * levels)
    with np.errstate(divide="ignore", invalid="ignore"):
        between = (m_back[-1] * w_back - m_back * w_back[-1]) ** 2 / (w_back * w_fore)
    threshold = int(np.nanargmax(np.where(np.isfinite(between), between, np.nan)))
    return invert_dark_bands(image.point(lambda p: 255 if p > threshold else 0))


def invert_dark_bands(image, min_height: int = 12):
    """Table headers are often white text on a dark bar, which binarises to a solid block Tesseract skips.

    Rows that are mostly black and at least `min_height` px tall (taller than ruling lines) are flipped
    to dark-on-light over the width of the bar.
    """
    import numpy as np
    from PIL import Image

    px = np.asarray(image, dtype=np.uint8).copy()
    dark_rows = (px < 128).mean(axis=1) > 0.5
    y = 0
    while y < len(dark_rows):
        if not dark_rows[y]:
            y += 1
            continue
        end = y
        while end < len(dark_rows) and dark_rows[end]:
            end += 1
        if end - y >= min_height:
            band = px[y:end]
            cols = np.where((band < 128).mean(axis=0) > 0.6)[0]
            if cols.size:
                x0, x1 = cols.min(), cols.max() + 1
                px[y:end, x0:x1] = 255 - px[y:end, x0:x1]
                # The bar's blurred edges leave dark stripes just above and below; clear them so they
                # don't merge with the neighbouring text row.
                # A stripe is one long dark run; a text row just below the bar never is, so it is left alone.
                for r in list(range(max(0, y - 4), y)) + list(range(end, min(len(px), end + 4))):
                    if _longest_run(px[r, x0:x1] < 128) > 0.25 * (x1 - x0):
                        px[r, x0:x1] = 255
        y = end
    return Image.fromarray(px)


def _longest_run(mask) -> int:
    """Length of the longest run of True values in a 1-D boolean array."""
    import numpy as np

    padded = np.concatenate(([0], mask.astype(np.int8), [0]))
    edges = np.flatnonzero(np.diff(padded))
    return int((edges[1::2] - edges[::2]).max()) if edges.size else 0


def deskew(image, max_angle: float = 4.0, step: float = 0.25):
    """Straighten a slightly rotated scan. -> (image, angle used).

    Projection profile: text rows are sharpest (row sums vary most) when lines are horizontal.
    Searched on a downscaled copy, then the full image is rotated once.
    """
    import numpy as np
    from PIL import Image

    small = image.copy()
    small.thumbnail((1000, 1000))
    ink = np.asarray(small, dtype=np.uint8) < 160           # dark pixels
    if ink.mean() < 0.002:                                    # blank page
        return image, 0.0
    ink_img = Image.fromarray((ink * 255).astype(np.uint8))

    def sharpness(angle: float) -> float:
        rotated = np.asarray(ink_img.rotate(angle, resample=Image.Resampling.NEAREST, fillcolor=0), dtype=np.float32)
        return float(np.var(rotated.sum(axis=1)))

    angles = [i * step for i in range(int(-max_angle / step), int(max_angle / step) + 1)]
    best = max(angles, key=sharpness)
    if abs(best) < step:
        return image, 0.0
    return image.rotate(best, resample=Image.Resampling.BICUBIC, expand=True, fillcolor=255), best
