"""Live Entry — face-scan arrivals.

POST /api/face-scan   <- called by the college's face-recognition system (or
                         the demo simulator page) each time a student's face
                         is recognised at the gate.
GET  /api/arrivals    <- the gate app's "Live Entry" tab: students who face-
                         scanned in the last few minutes, newest first, so the
                         guard taps the student instead of typing the roll.
"""
import re
from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import get_db
from models import Student, FaceArrival

router = APIRouter()


def clean_id(raw: str) -> str:
    return re.sub(r"[^A-Za-z0-9]", "", (raw or "")).upper()


class FaceScanRequest(BaseModel):
    roll: str


@router.post("/face-scan")
def face_scan(req: FaceScanRequest, db: Session = Depends(get_db)):
    cid = clean_id(req.roll)
    student = db.query(Student).filter(Student.barcode_id == cid).first()
    if not student:
        raise HTTPException(status_code=404, detail="Face system: student not found for this roll")
    db.add(FaceArrival(barcode_id=cid))
    db.commit()
    return {"ok": True, "name": student.name, "roll_number": student.roll_number}


@router.get("/arrivals")
def arrivals(minutes: int = Query(10, ge=1, le=60), db: Session = Depends(get_db)):
    since = datetime.utcnow() - timedelta(minutes=minutes)
    rows = (
        db.query(FaceArrival)
        .filter(FaceArrival.scanned_at >= since)
        .order_by(FaceArrival.scanned_at.desc())
        .limit(50)
        .all()
    )
    items, seen = [], set()
    for r in rows:                        # newest first; keep one per student
        if r.barcode_id in seen:
            continue
        seen.add(r.barcode_id)
        s = db.query(Student).filter(Student.barcode_id == r.barcode_id).first()
        if not s:
            continue
        items.append({
            "barcode_id": s.barcode_id,
            "name": s.name,
            "roll_number": s.roll_number,
            "hostel": s.hostel,
            "place": s.place,
            "scanned_at": r.scanned_at,
        })
        if len(items) >= 15:
            break
    return {"items": items}
