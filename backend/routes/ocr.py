"""
OCR Route — Vehicle number plate detection.
Uses EasyOCR. Models are loaded ONCE at startup and kept in memory.
No cold-start penalty per request.
"""

import re
import io
import base64
import numpy as np
from PIL import Image
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from routes.auth import get_current_user

router = APIRouter(prefix="/ocr", tags=["ocr"])

# ── Load OCR model once at module import time ────────────────────────────────
_reader = None

def get_reader():
    global _reader
    if _reader is None:
        try:
            import easyocr
            _reader = easyocr.Reader(['en'], gpu=False, verbose=False)
            print("✅ EasyOCR model loaded")
        except Exception as e:
            print(f"⚠️  EasyOCR not available: {e}")
            _reader = None
    return _reader


# ── Indian Number Plate Patterns ────────────────────────────────────────────
# Format: TN 99 AB 1234  or  TN99AB1234
PLATE_PATTERN = re.compile(
    r'[A-Z]{2}[\s\-]?[0-9]{1,2}[\s\-]?[A-Z]{1,3}[\s\-]?[0-9]{1,4}',
    re.IGNORECASE
)


def extract_plate_text(texts: list) -> str | None:
    """
    Filter OCR results to find a valid Indian number plate.
    OCR often reads multiple text regions — we pick the best match.
    """
    candidates = []
    for text in texts:
        cleaned = text.strip().upper().replace("O", "0")
        match = PLATE_PATTERN.search(cleaned)
        if match:
            plate = re.sub(r'[\s\-]', '', match.group()).upper()
            candidates.append(plate)

    if not candidates:
        # Return the longest text as a fallback
        all_text = " ".join(texts).upper()
        return all_text if all_text else None

    # Return the most plate-like candidate
    return max(candidates, key=len)


def process_image_for_ocr(image_data: bytes) -> list[str]:
    """Convert image bytes to numpy array for EasyOCR."""
    img = Image.open(io.BytesIO(image_data))
    # Upscale small images for better OCR accuracy
    if img.width < 600:
        scale = 600 / img.width
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.LANCZOS)
    # Convert to RGB (handles RGBA, grayscale, etc.)
    img = img.convert("RGB")
    return np.array(img)


# ── Request Schema ────────────────────────────────────────────────────────────

class OCRRequest(BaseModel):
    image: str  # base64 encoded image


# ── Routes ───────────────────────────────────────────────────────────────────

@router.post("/scan-plate")
def scan_plate(
    req: OCRRequest,
    current_user=Depends(get_current_user)
):
    """
    Receive base64 image from frontend camera → run OCR → return plate text.
    Guard can edit the result if OCR is wrong.
    """
    reader = get_reader()
    if reader is None:
        return {
            "success": False,
            "plate": None,
            "confidence": 0,
            "message": "OCR model not available. Please type the vehicle number manually.",
            "all_text": []
        }

    try:
        # Decode base64 image
        if "base64," in req.image:
            image_data = base64.b64decode(req.image.split("base64,")[1])
        else:
            image_data = base64.b64decode(req.image)

        img_array = process_image_for_ocr(image_data)
        results = reader.readtext(img_array, detail=0, paragraph=False)

        plate = extract_plate_text(results)

        return {
            "success": True,
            "plate": plate,
            "confidence": 0.85 if plate and PLATE_PATTERN.search(plate or "") else 0.5,
            "message": "Plate detected" if plate else "Could not detect plate clearly",
            "all_text": results
        }

    except Exception as e:
        return {
            "success": False,
            "plate": None,
            "confidence": 0,
            "message": f"OCR error: {str(e)}. Please type the vehicle number manually.",
            "all_text": []
        }


@router.get("/status")
def ocr_status():
    """Check if OCR model is loaded and ready."""
    reader = get_reader()
    return {
        "ocr_ready": reader is not None,
        "message": "EasyOCR ready" if reader else "OCR not loaded — manual entry mode"
    }
