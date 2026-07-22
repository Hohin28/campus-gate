import uuid
from datetime import datetime
from sqlalchemy import Column, String, DateTime, Enum, Index, Boolean, Integer
from database import Base

def gen_uuid():
    return str(uuid.uuid4())

class SystemUser(Base):
    __tablename__ = "system_users"
    id = Column(String, primary_key=True, default=gen_uuid)
    username = Column(String, unique=True, nullable=False)
    password_hash = Column(String, nullable=False)
    role = Column(String, default="guard")      # guard | warden
    hostel = Column(String, nullable=True)       # set for wardens — the hostel they manage

class Student(Base):
    __tablename__ = "students"
    id = Column(String, primary_key=True, default=gen_uuid)
    barcode_id = Column(String, unique=True, nullable=False, index=True)
    name = Column(String, nullable=False)
    roll_number = Column(String, unique=True, nullable=False)
    department = Column(String)
    year = Column(String)
    place = Column(String)
    hostel = Column(String)
    phone = Column(String)
    parent_phone = Column(String)

class VehicleLog(Base):
    __tablename__ = "vehicle_logs"
    id = Column(String, primary_key=True, default=gen_uuid)
    student_id = Column(String, nullable=False)
    student_name = Column(String, nullable=False)
    roll_number = Column(String, nullable=False)
    phone = Column(String)
    place = Column(String)
    hostel = Column(String)
    occupants = Column(Integer)
    companion = Column(String)                   # "Parent" or the relative's name
    person_type = Column(String, default="student")
    vehicle_number = Column(String, nullable=False)
    vehicle_number_normalized = Column(String, nullable=False)
    entry_time = Column(DateTime, default=datetime.utcnow)
    exit_time = Column(DateTime, nullable=True)
    status = Column(String, default="INSIDE")
    guard_id = Column(String, nullable=False)
    # Warden approval (only set when the student belongs to a hostel):
    #   PENDING -> waiting for warden; APPROVED -> warden confirmed arrival; None -> not required
    warden_status = Column(String, nullable=True)
    warden_approved_at = Column(DateTime, nullable=True)
    warden_approved_by = Column(String, nullable=True)

    __table_args__ = (
        Index("ix_vehicle_logs_entry_time", "entry_time"),
        Index("ix_vehicle_logs_status", "status"),
        Index("ix_vehicle_logs_hostel_warden", "hostel", "warden_status"),
    )

class FaceArrival(Base):
    """A face-scan event at the gate. In production Amrita's face-recognition
    system POSTs these to /api/face-scan; the gate's 'Live Entry' tab lists the
    recent ones so the guard can tap the student instead of typing the roll."""
    __tablename__ = "face_arrivals"
    id = Column(String, primary_key=True, default=gen_uuid)
    barcode_id = Column(String, nullable=False, index=True)   # normalised roll
    scanned_at = Column(DateTime, default=datetime.utcnow, index=True)