import re
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from pydantic import BaseModel
from datetime import datetime
from database import get_db
from models import VehicleLog, Student
from jose import jwt

router = APIRouter()
SECRET_KEY = "campusgate2024secret"
ALGORITHM = "HS256"

def normalize_plate(plate: str) -> str:
    return plate.upper().replace(" ", "").replace("-", "")

def clean_id(raw: str) -> str:
    """Uppercase and strip everything but A-Z/0-9 from a scanned/typed roll
    number, so CB.SC.U4CIV24101 and CBSCU4CIV24101 both match the same record."""
    return re.sub(r"[^A-Za-z0-9]", "", (raw or "")).upper()

def is_valid_id(cid: str) -> bool:
    """Accept any roll number / campus ID — alphanumeric, with at least one
    letter and one digit, e.g. CBSCU4CIV24101 or CYS24122."""
    return (
        bool(re.fullmatch(r"[A-Z0-9]{5,25}", cid))
        and any(c.isalpha() for c in cid)
        and any(c.isdigit() for c in cid)
    )

def is_valid_plate(norm: str) -> bool:
    """Strict plate format AA 00 AA 0000 (each group may be shorter):
    1-2 letters, 1-2 digits, 1-2 letters, 1-4 digits. e.g. TN 38 H 1234."""
    return bool(re.fullmatch(r"[A-Z]{1,2}\d{1,2}[A-Z]{1,2}\d{1,4}", norm or ""))

class EntryRequest(BaseModel):
    student_id: str
    vehicle_number: str
    guard_token: str

class ExitRequest(BaseModel):
    vehicle_number: str
    guard_token: str

class ScanRequest(BaseModel):
    barcode_id: str
    vehicle_number: str
    guard_token: str
    occupants: int | None = None
    companion: str | None = None   # "Parent" or the relative's name

def get_guard_id(token: str) -> str:
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("id")
    except:
        raise HTTPException(status_code=401, detail="Invalid token")

def get_guard_id_lenient(token: str) -> str:
    """Like get_guard_id but never blocks the gate on a token problem."""
    try:
        payload = jwt.decode(token, SECRET_KEY, algorithms=[ALGORITHM])
        return payload.get("id") or "guard"
    except:
        return "guard"

@router.post("/scan")
def scan_toggle(req: ScanRequest, db: Session = Depends(get_db)):
    """Scan a student ID barcode together with a captured plate.

    Automatically decides entry vs exit:
      - if that vehicle is already INSIDE -> record EXIT
      - otherwise                         -> record ENTRY
    """
    guard_id = get_guard_id_lenient(req.guard_token)

    cid = clean_id(req.barcode_id)
    # Resolve the student from the dataset by normalised roll number. If the roll
    # is not in the dataset, accept any well-formed ID and log it as-is.
    student = db.query(Student).filter(Student.barcode_id == cid).first()

    if student:
        sid, sname, sroll = student.id, student.name, student.roll_number
        sphone, splace, shostel = student.phone, student.place, student.hostel
    else:
        if not is_valid_id(cid):
            raise HTTPException(status_code=400, detail="Enter a valid roll number (e.g. CB.SC.U4CIV24101)")
        # Unseen roll: leave name blank, show the typed ID in the Roll No column.
        sid, sname, sroll = cid, "", cid
        sphone, splace, shostel = None, None, None

    # People in the vehicle is entered at the gate (not from the dataset).
    soccupants = req.occupants

    norm = normalize_plate(req.vehicle_number)
    if not norm:
        raise HTTPException(status_code=400, detail="No vehicle number captured")
    if not is_valid_plate(norm):
        raise HTTPException(status_code=400, detail="Vehicle number must look like AA 00 AA 0000 (e.g. TN 38 H 1234)")

    active = db.query(VehicleLog).filter(
        VehicleLog.vehicle_number_normalized == norm,
        VehicleLog.status == "INSIDE"
    ).first()

    # Entry gate only records entries. If the vehicle is already inside, it must
    # be cleared at the Exit gate first — this keeps the two guards in sync.
    if active:
        raise HTTPException(
            status_code=400,
            detail="This vehicle is already inside — it must be recorded at the Exit gate before re-entering."
        )

    log = VehicleLog(
        student_id=sid,
        student_name=sname,
        roll_number=sroll,
        phone=sphone,
        place=splace,
        hostel=shostel,
        occupants=soccupants,
        companion=(req.companion or "").strip()[:60] or None,
        person_type="student",
        vehicle_number=req.vehicle_number.upper(),
        vehicle_number_normalized=norm,
        entry_time=datetime.utcnow(),
        status="INSIDE",
        guard_id=guard_id,
        # Hostel students need the warden to confirm arrival before their car may exit.
        warden_status="PENDING" if shostel else None,
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    action = "ENTRY"

    return {
        "action": action,
        "student_name": log.student_name,
        "roll_number": log.roll_number,
        "phone": log.phone,
        "place": log.place,
        "hostel": log.hostel,
        "occupants": log.occupants,
        "companion": log.companion,
        "vehicle_number": log.vehicle_number,
        "entry_time": log.entry_time,
        "exit_time": log.exit_time,
        "status": log.status,
    }


@router.post("/entry")
def vehicle_entry(req: EntryRequest, db: Session = Depends(get_db)):
    guard_id = get_guard_id(req.guard_token)
    student = db.query(Student).filter(Student.id == req.student_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")

    norm = normalize_plate(req.vehicle_number)

    existing = db.query(VehicleLog).filter(
        VehicleLog.vehicle_number_normalized == norm,
        VehicleLog.status == "INSIDE"
    ).first()
    if existing:
        raise HTTPException(status_code=400, detail="Vehicle already inside")

    log = VehicleLog(
        student_id=student.id,
        student_name=student.name,
        roll_number=student.roll_number,
        vehicle_number=req.vehicle_number.upper(),
        vehicle_number_normalized=norm,
        entry_time=datetime.utcnow(),
        status="INSIDE",
        guard_id=guard_id
    )
    db.add(log)
    db.commit()
    db.refresh(log)
    return {"message": "Entry recorded", "log_id": log.id, "entry_time": log.entry_time}

@router.post("/exit")
def vehicle_exit(req: ExitRequest, db: Session = Depends(get_db)):
    """Exit gate: match a plate to its open entry and close it.

    This is what the second guard uses — plate only, no ID card. It finds the
    INSIDE record created by the entry guard and marks it EXITED, connecting
    both halves of the trip in one shared log.
    """
    get_guard_id_lenient(req.guard_token)
    norm = normalize_plate(req.vehicle_number)
    if not norm:
        raise HTTPException(status_code=400, detail="No vehicle number entered")
    if not is_valid_plate(norm):
        raise HTTPException(status_code=400, detail="Vehicle number must look like AA 00 AA 0000 (e.g. TN 38 H 1234)")

    log = db.query(VehicleLog).filter(
        VehicleLog.vehicle_number_normalized == norm,
        VehicleLog.status == "INSIDE"
    ).first()
    if not log:
        raise HTTPException(status_code=404, detail="This vehicle is not inside — no matching entry found.")

    # Exit lock: a hostel student's car cannot leave until the warden confirms arrival.
    if log.warden_status == "PENDING":
        raise HTTPException(
            status_code=403,
            detail=f"⛔ Pending — waiting for {log.hostel} hostel warden to confirm {log.student_name or 'the student'} reached the hostel."
        )

    log.exit_time = datetime.utcnow()
    log.status = "EXITED"
    db.commit()
    db.refresh(log)
    return {
        "action": "EXIT",
        "student_name": log.student_name,
        "roll_number": log.roll_number,
        "phone": log.phone,
        "place": log.place,
        "hostel": log.hostel,
        "occupants": log.occupants,
        "companion": log.companion,
        "vehicle_number": log.vehicle_number,
        "entry_time": log.entry_time,
        "exit_time": log.exit_time,
        "status": log.status,
    }