from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session
from datetime import datetime, date
from database import get_db
from models import VehicleLog

router = APIRouter()

@router.get("/logs")
def get_logs(
    db: Session = Depends(get_db),
    status: str = Query(None),
    search: str = Query(None),
    limit: int = 50
):
    query = db.query(VehicleLog)
    if status:
        query = query.filter(VehicleLog.status == status)
    if search:
        s = f"%{search.upper()}%"
        query = query.filter(
            VehicleLog.vehicle_number_normalized.like(s) |
            VehicleLog.student_name.like(s) |
            VehicleLog.roll_number.like(s)
        )
    logs = query.order_by(VehicleLog.entry_time.desc()).limit(limit).all()
    return [
        {
            "id": l.id,
            "student_name": l.student_name,
            "roll_number": l.roll_number,
            "phone": l.phone,
            "place": l.place,
            "hostel": l.hostel,
            "occupants": l.occupants,
            "companion": l.companion,
            "person_type": l.person_type,
            "vehicle_number": l.vehicle_number,
            "entry_time": l.entry_time,
            "exit_time": l.exit_time,
            "status": l.status
        } for l in logs
    ]

@router.get("/stats")
def get_stats(db: Session = Depends(get_db)):
    today = date.today()
    total_today = db.query(VehicleLog).filter(
        VehicleLog.entry_time >= datetime.combine(today, datetime.min.time())
    ).count()
    inside_now = db.query(VehicleLog).filter(VehicleLog.status == "INSIDE").count()
    exited_today = db.query(VehicleLog).filter(
        VehicleLog.status == "EXITED",
        VehicleLog.exit_time >= datetime.combine(today, datetime.min.time())
    ).count()
    return {
        "total_today": total_today,
        "inside_now": inside_now,
        "exited_today": exited_today
    }