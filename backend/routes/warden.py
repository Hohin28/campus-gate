"""Warden approval API.

A warden logs in, sees the students who entered the gate and belong to *their*
hostel (PENDING), and taps approve when the student reaches. Approving unlocks
that vehicle's exit at the gate.
"""
from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from jose import jwt
from database import get_db
from models import VehicleLog

router = APIRouter()
SECRET_KEY = "campusgate2024secret"
ALGORITHM = "HS256"


def warden_from_token(token: str) -> dict:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired session")
    if payload.get("role") != "warden":
        raise HTTPException(status_code=403, detail="Warden access only")
    if not payload.get("hostel"):
        raise HTTPException(status_code=403, detail="This warden has no hostel assigned")
    return payload


def serialize(l: VehicleLog) -> dict:
    return {
        "id": l.id,
        "student_name": l.student_name,
        "roll_number": l.roll_number,
        "phone": l.phone,
        "place": l.place,
        "occupants": l.occupants,
        "companion": l.companion,
        "vehicle_number": l.vehicle_number,
        "entry_time": l.entry_time,
        "warden_status": l.warden_status,
        "warden_approved_at": l.warden_approved_at,
        "vehicle_status": l.status,
    }


@router.get("/warden/list")
def warden_list(
    token: str = Query(...),
    status: str = Query("PENDING"),   # PENDING or APPROVED
    db: Session = Depends(get_db),
):
    w = warden_from_token(token)
    hostel = w["hostel"]
    rows = (
        db.query(VehicleLog)
        .filter(VehicleLog.hostel == hostel, VehicleLog.warden_status == status)
        .order_by(VehicleLog.entry_time.desc())   # newest on top
        .limit(100)
        .all()
    )
    return {"hostel": hostel, "warden": w.get("sub"), "items": [serialize(l) for l in rows]}


class ApproveRequest(BaseModel):
    log_id: str
    token: str


@router.post("/warden/approve")
def warden_approve(req: ApproveRequest, db: Session = Depends(get_db)):
    w = warden_from_token(req.token)
    log = db.query(VehicleLog).filter(VehicleLog.id == req.log_id).first()
    if not log:
        raise HTTPException(status_code=404, detail="Record not found")
    if log.hostel != w["hostel"]:
        raise HTTPException(status_code=403, detail="That student is not in your hostel")
    if log.warden_status != "PENDING":
        raise HTTPException(status_code=400, detail="Already handled")
    log.warden_status = "APPROVED"
    log.warden_approved_at = datetime.utcnow()
    log.warden_approved_by = w.get("sub")
    db.commit()
    return {"ok": True, "student_name": log.student_name}
