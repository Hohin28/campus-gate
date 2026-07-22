from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session
from database import get_db
from models import Student, VehicleLog

router = APIRouter()

@router.get("/student/{barcode_id}")
def lookup_student(barcode_id: str, db: Session = Depends(get_db)):
    student = db.query(Student).filter(Student.barcode_id == barcode_id).first()
    if not student:
        raise HTTPException(status_code=404, detail="Student not found")
    active_log = db.query(VehicleLog).filter(
        VehicleLog.student_id == student.id,
        VehicleLog.status == "INSIDE"
    ).first()
    return {
        "id": student.id,
        "name": student.name,
        "roll_number": student.roll_number,
        "department": student.department,
        "year": student.year,
        "phone": student.phone,
        "parent_phone": student.parent_phone,
        "barcode_id": student.barcode_id,
        "currently_inside": active_log is not None,
        "active_vehicle": active_log.vehicle_number if active_log else None
    }