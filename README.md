# 🎓 Campus Gate — Smart Vehicle Entry/Exit Management System

## What problem does this solve?

At our university, when a student arrives with parents in a private vehicle:

1. Student scans face at the main gate ✅ (existing system)
2. Student walks to security bench
3. Student **manually writes** vehicle number, student details, parent info on paper
4. Parents wait at the barrier — one by one — causing **massive traffic jams**
5. At exit, parents submit the paper. Guard checks it manually.

This app eliminates steps 2–5 entirely. Guard scans the student's ID barcode → details appear instantly → guard enters/scans vehicle number → done. **Total time: under 10 seconds.**

---

## Architecture

```
Guard's Phone/Tablet (Mobile Browser)
          ↓ HTTP
FastAPI Server (runs on laptop at security bench)
          ↓
SQLite Database (file on disk — no installation needed)
```

- **No app installation** — opens in any mobile browser
- **Same login, multiple devices** — guard1 at entry, guard2 at exit, same database
- **Scales to PostgreSQL** — one line change when ready

---

## Quick Setup

### Step 1: Install Python dependencies

```bash
cd backend
pip install -r requirements.txt
```

> ⚠️ EasyOCR will download a ~100MB model on first run. This is a one-time download.

### Step 2: Create dummy data (50 students, 10 faculty)

```bash
cd backend
python seed_data.py
```

You'll see sample barcodes printed — note these for testing.

### Step 3: Start the server

```bash
cd backend
uvicorn main:app --host 0.0.0.0 --port 8000 --reload
```

### Step 4: Open the app

- **On the same laptop:** http://localhost:8000
- **On guard's phone** (must be on same WiFi): http://YOUR_LAPTOP_IP:8000
  - Find your IP: `ipconfig` (Windows) or `ifconfig` (Linux/Mac)
  - Example: http://192.168.1.5:8000

---

## Login Credentials

| Username | Password  | Role  |
|----------|-----------|-------|
| admin    | admin123  | Admin |
| guard1   | guard123  | Guard |
| guard2   | guard123  | Guard |

---

## How to Use

### Student Vehicle Entry
1. Student arrives with parents at gate
2. Guard opens app → taps **Student**
3. Guard taps **Scan ID** → scans barcode on student ID card
4. Student details appear instantly
5. Guard taps **Scan Vehicle** or types plate number
6. Guard taps **Record Entry** → done ✅
7. Barrier opens. Parents drive in.

### Exit
1. Guard taps **Exit** on dashboard
2. Types/scans vehicle number
3. App shows who the vehicle belongs to (preview)
4. Guard taps **Confirm Exit** → record updated ✅

### Logs
- Tap **View All Logs** from dashboard
- Search by name, vehicle number, roll number
- Filter: Inside / Exited
- 🟡 Yellow = currently inside | ✅ Green = exited

---

## Testing Barcodes

After running `seed_data.py`, you'll see output like:
```
Sample student barcodes (for testing):
Name: Aarav Kumar          Roll: 24CS001  Barcode: CGU24CS001
Name: Priya Sharma         Roll: 23AI005  Barcode: CGU23AI005
```

To test scanning:
1. Print or display the barcode value on screen
2. Use any online barcode generator (e.g. https://barcode.tec-it.com) to generate CODE-128 barcodes
3. Or just type the barcode value in the manual entry box

---

## Folder Structure

```
campus-gate/
├── backend/
│   ├── main.py           ← FastAPI app (start here)
│   ├── database.py       ← DB config (SQLite → PostgreSQL: 1 line change)
│   ├── models.py         ← All database tables
│   ├── seed_data.py      ← Generate 50 students + 10 faculty
│   ├── requirements.txt
│   └── routes/
│       ├── auth.py       ← Login / JWT
│       ├── lookup.py     ← Barcode scan → person details
│       ├── vehicle.py    ← Entry / Exit recording
│       ← ocr.py          ← Number plate OCR
│       └── logs.py       ← Dashboard / search
└── frontend/
    ├── index.html        ← Single page app
    ├── style.css         ← Mobile-first styling
    └── app.js            ← All frontend logic
```

---

## Database Schema (Key Tables)

### students
| Field           | Type    | Notes                          |
|----------------|---------|--------------------------------|
| id             | UUID    | Primary key                    |
| roll_number    | String  | Indexed for fast lookup        |
| barcode_value  | String  | Matches physical ID card       |
| full_name      | String  |                                |
| department     | Enum    | CS, AI, ECE, etc.              |
| hostel_name    | String  |                                |
| room_number    | String  |                                |
| phone          | String  |                                |

### vehicle_logs
| Field                    | Type     | Notes                          |
|--------------------------|----------|--------------------------------|
| id                       | UUID     | Primary key                    |
| person_type              | Enum     | STUDENT / FACULTY / VISITOR    |
| student_id               | FK       | Links to students table        |
| vehicle_number           | String   | Original typed/scanned         |
| vehicle_number_normalized| String   | Indexed, no spaces/dashes      |
| entry_time               | DateTime |                                |
| exit_time                | DateTime | Null until exit                |
| status                   | Enum     | INSIDE / EXITED / OVERSTAY    |

---

## Switching to PostgreSQL (Production)

1. Install PostgreSQL and create a database:
```sql
CREATE DATABASE campusgate;
CREATE USER campusgate WITH PASSWORD 'secret';
GRANT ALL ON DATABASE campusgate TO campusgate;
```

2. In `backend/database.py`, change **one line**:
```python
# FROM:
DATABASE_URL = "sqlite:///./campus_gate.db"

# TO:
DATABASE_URL = "postgresql://campusgate:secret@localhost/campusgate"
```

3. Install psycopg2:
```bash
pip install psycopg2-binary
```

4. Re-run `python seed_data.py` — all tables are created automatically.

---

## Scalability Notes (15,000+ Students)

| Concern | Solution |
|---------|----------|
| 15,000 student lookups | All barcode/roll queries are indexed — sub-5ms even at 100k records |
| Peak traffic (morning rush) | PostgreSQL connection pooling + FastAPI async |
| Multiple gates | Multiple devices, same backend, same DB |
| Daily logs volume | Partition `vehicle_logs` by date in PostgreSQL |
| ERP integration | Replace `seed_data.py` with a sync job from university ERP |
| Overstay detection | Cron job at midnight: mark all INSIDE as OVERSTAY, alert admin |
| Audit trail | All entries have guard_id — know who recorded what |
| Offline fallback | Add SQLite local cache on tablet for network failures |

---

## API Reference (for paper/extension)

| Method | Endpoint | Description |
|--------|----------|-------------|
| POST | /auth/login | Login, returns JWT |
| GET | /lookup/barcode/{value} | Scan barcode → person details |
| GET | /lookup/student/roll/{roll} | Lookup by roll number |
| POST | /vehicle/entry/student | Record student vehicle entry |
| POST | /vehicle/entry/faculty | Record faculty vehicle entry |
| POST | /vehicle/entry/visitor | Record visitor entry |
| POST | /vehicle/exit | Record vehicle exit |
| GET | /vehicle/check/{vehicle} | Check if vehicle is inside |
| GET | /logs/ | Get all logs (with search/filter) |
| GET | /logs/stats | Today's counts |
| GET | /logs/inside | All vehicles currently inside |
| POST | /ocr/scan-plate | Send image, get plate text |

Full interactive docs: http://localhost:8000/docs

---

## Future Additions (for paper extension)

- [ ] **SMS/WhatsApp notification** to student when parent's vehicle exits
- [ ] **End-of-day report** — email to admin: list of vehicles that didn't exit
- [ ] **Overstay alert** — flag vehicles inside after 10 PM
- [ ] **Analytics dashboard** — peak hour traffic graphs
- [ ] **ERP sync** — auto-import student data from university system
- [ ] **PWA (offline mode)** — works without internet, syncs when connected
- [ ] **Warden module** — optional approval flow for extended stays
- [ ] **Multiple gate support** — entry gate vs exit gate with gate-specific logs
