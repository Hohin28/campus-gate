"""License plate recognition from a webcam frame using EasyOCR.

Tuned for speed and accuracy on Indian plates (format AA 00 AA 0000):
- the frontend sends a tight crop of the plate-guide region (small image = fast)
- recognition is restricted to A-Z / 0-9 (allowlist) with the fast greedy decoder
- multi-fragment reads ("TN 38" + "H 1234") are merged left-to-right
- ambiguous characters are auto-corrected using the known plate structure
  (O<->0, I<->1, S<->5, B<->8 ... depending on whether that position must be
  a letter or a digit)
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from functools import lru_cache
import base64
import re
import numpy as np

router = APIRouter()

# EasyOCR is heavy to initialise, so load it once and cache it. main.py warms
# this up in a background thread at server startup so the first scan is fast.
_reader = None

ALLOWLIST = "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789"

# Lookalike maps used when the plate structure says a position must be a
# digit (L2D) or a letter (D2L).
L2D = {"O": "0", "Q": "0", "D": "0", "I": "1", "L": "1", "Z": "2",
       "S": "5", "B": "8", "G": "6", "T": "7", "A": "4", "J": "1"}
D2L = {"0": "O", "1": "I", "2": "Z", "5": "S", "8": "B", "6": "G",
       "7": "T", "4": "A"}

# Indian plate structure: 1-2 letters, 1-2 digits, 1-2 letters, 1-4 digits.
SEGMENTS = (("L", 1, 2), ("D", 1, 2), ("L", 1, 2), ("D", 1, 4))


def get_reader():
    global _reader
    if _reader is None:
        import easyocr
        # verbose=False avoids EasyOCR's progress bar, whose block glyphs
        # crash on the Windows cp1252 console (UnicodeEncodeError).
        _reader = easyocr.Reader(["en"], gpu=False, verbose=False)
    return _reader


def warm_up():
    """Load the model and run one tiny read so the first real scan is fast."""
    reader = get_reader()
    reader.readtext(np.zeros((48, 160, 3), dtype=np.uint8),
                    allowlist=ALLOWLIST, decoder="greedy")


class PlateImage(BaseModel):
    # single frame (legacy) or a burst of frames — the phone sends 3 so one
    # blurry / mid-focus frame doesn't ruin the read
    image: str | None = None
    images: list[str] | None = None
    # fast=True -> skip the enhancement passes. Used by the live auto-detect
    # loop, which sends a frame every ~0.5s and votes across ticks instead.
    fast: bool = False


def clean_plate(text: str) -> str:
    """Keep only A-Z and 0-9, uppercased."""
    return re.sub(r"[^A-Z0-9]", "", text.upper())


def coerce_plate(s: str):
    """Try to interpret `s` as an AA 00 AA 0000 plate, correcting lookalike
    characters by position. Returns the corrected plate or None.

    e.g. 'TN3BHI234' -> 'TN3BH1234' (I->1 in a digit slot)
    """
    s = s.upper()
    n = len(s)
    if not (4 <= n <= 10):
        return None
    if not any(ch.isdigit() for ch in s):
        return None   # a real plate read always contains some digits
    INF = 99

    @lru_cache(maxsize=None)
    def go(i, seg, cnt):
        # best (cost, tail-string) completing from char i, inside segment seg
        # having already consumed cnt chars of that segment
        if seg == len(SEGMENTS):
            return (0, "") if i == n else (INF, None)
        kind, lo, hi = SEGMENTS[seg]
        best = (INF, None)
        if cnt >= lo:                       # option: close this segment
            c, rest = go(i, seg + 1, 0)
            if rest is not None and c < best[0]:
                best = (c, rest)
        if i < n and cnt < hi:              # option: consume s[i] into segment
            ch = s[i]
            if kind == "L":
                fixed = ch if ch.isalpha() else D2L.get(ch)
            else:
                fixed = ch if ch.isdigit() else L2D.get(ch)
            if fixed:
                cost = 0 if fixed == ch else 1
                c, rest = go(i + 1, seg, cnt + 1)
                if rest is not None and c + cost < best[0]:
                    best = (c + cost, fixed + rest)
        return best

    cost, result = go(0, 0, 0)
    # more than 2 corrected characters means we're inventing, not fixing
    return result if result is not None and cost <= 2 else None


def prepare_image(img):
    """Resize for speed (big frames) or readability (tiny crops)."""
    import cv2
    h, w = img.shape[:2]
    if w > 1280:
        scale = 1280.0 / w
        img = cv2.resize(img, (1280, int(h * scale)), interpolation=cv2.INTER_AREA)
    elif w < 480:
        img = cv2.resize(img, (w * 2, h * 2), interpolation=cv2.INTER_CUBIC)
    return img


def enhance_clahe(img):
    """Contrast boost — recovers washed-out / shadowed plates."""
    import cv2
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    clahe = cv2.createCLAHE(clipLimit=3.0, tileGridSize=(8, 8))
    return clahe.apply(gray)


def enhance_sharpen(img):
    """Unsharp mask — recovers mild motion blur / soft focus."""
    import cv2
    gray = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
    blur = cv2.GaussianBlur(gray, (0, 0), 2.0)
    return cv2.addWeighted(gray, 1.8, blur, -0.8, 0)


def read_candidates(reader, img):
    """One OCR pass: fragments merged in reading order -> plate candidates.

    Returns a list of (score, plate, conf, valid) tuples.
    """
    img_h = img.shape[0]
    small = img.shape[1] < 700
    results = reader.readtext(
        img,
        allowlist=ALLOWLIST,   # only plate characters -> faster + fewer misreads
        decoder="greedy",      # fastest decoder
        paragraph=False,
        canvas_size=1280,
        mag_ratio=1.5 if small else 1.0,   # magnify small crops for detection
    )

    # Fragments in reading order: top line first, then left-to-right
    # (handles two-line plates as well as split reads like "TN 38" + "H 1234").
    frags = []
    for box, text, conf in results:
        cleaned = clean_plate(text)
        if not cleaned or conf < 0.15:
            continue
        xs = [p[0] for p in box]
        ys = [p[1] for p in box]
        y_center = sum(ys) / len(ys)
        row = 0 if y_center < img_h / 2 else 1
        frags.append((row, min(xs), cleaned, float(conf)))
    frags.sort(key=lambda f: (f[0], f[1]))

    # Every contiguous run of fragments is a candidate plate string; prefer
    # runs that coerce cleanly into the AA 00 AA 0000 structure.
    out = []
    for i in range(len(frags)):
        text = ""
        confs = []
        for j in range(i, len(frags)):
            text += frags[j][2]
            confs.append(frags[j][3])
            if len(text) > 10:
                break
            if len(text) < 4:
                continue
            conf = sum(confs) / len(confs)
            fixed = coerce_plate(text)
            if fixed:
                out.append((10.0 + conf + 0.2 * len(fixed), fixed, conf, True))
            else:
                out.append((conf, text, conf, False))
    return out


def decode_data_url(data_url):
    import cv2
    data = data_url.split(",")[-1]
    arr = np.frombuffer(base64.b64decode(data), np.uint8)
    return cv2.imdecode(arr, cv2.IMREAD_COLOR)


@router.post("/recognize-plate")
def recognize_plate(req: PlateImage):
    # Decode up to 3 frames (burst from the phone, or one legacy frame).
    raw = req.images if req.images else ([req.image] if req.image else [])
    frames = []
    for d in raw[:3]:
        try:
            img = decode_data_url(d)
            if img is not None:
                frames.append(prepare_image(img))
        except Exception:
            continue
    if not frames:
        raise HTTPException(status_code=400, detail="Invalid image data")

    reader = get_reader()

    # Pass order: every frame plain first (a sharp frame beats an enhanced
    # blurry one), then contrast/sharpen variants of the first frame.
    # fast mode (live auto-detect) skips the enhancement passes for latency.
    passes = [f for f in frames]
    if not req.fast:
        passes.append(enhance_clahe(frames[0]))
        passes.append(enhance_sharpen(frames[0]))

    tally = {}          # plate -> {count, best conf, valid, score}
    best_raw = None     # fallback when nothing coerces to a valid plate

    def record(cands):
        nonlocal best_raw
        for score, plate_txt, conf, valid in cands:
            if valid:
                t = tally.setdefault(plate_txt, {"count": 0, "conf": 0.0, "score": 0.0})
                t["count"] += 1
                t["conf"] = max(t["conf"], conf)
                t["score"] = max(t["score"], score)
            elif best_raw is None or score > best_raw[0]:
                best_raw = (score, plate_txt, conf)

    winner = None
    for i, img in enumerate(passes):
        record(read_candidates(reader, img))
        # Early exit: a valid plate seen twice, or seen once very confidently.
        for p, t in tally.items():
            if t["count"] >= 2 or t["conf"] >= 0.55:
                winner = p
                break
        if winner:
            break

    if not winner and tally:   # best valid plate across all passes
        winner = max(tally, key=lambda p: (tally[p]["count"], tally[p]["conf"]))

    candidates = sorted(
        [{"text": p, "confidence": round(t["conf"], 3), "valid": True,
          "votes": t["count"], "score": round(t["score"], 3)} for p, t in tally.items()],
        key=lambda c: (c["votes"], c["confidence"]), reverse=True)[:5]

    if winner:
        return {"plate": winner, "candidates": candidates, "detected": True}
    if best_raw:
        return {"plate": best_raw[1], "candidates": candidates,
                "detected": best_raw[2] > 0.4}
    return {"plate": "", "candidates": [], "detected": False}
