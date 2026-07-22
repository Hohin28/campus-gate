from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from database import Base, engine
from routes import auth, lookup, vehicle, logs, plate, warden, arrivals

Base.metadata.create_all(bind=engine)

app = FastAPI(title="Campus Gate")

app.include_router(auth.router, prefix="/api")
app.include_router(lookup.router, prefix="/api")
app.include_router(vehicle.router, prefix="/api")
app.include_router(logs.router, prefix="/api")
app.include_router(plate.router, prefix="/api")
app.include_router(warden.router, prefix="/api")
app.include_router(arrivals.router, prefix="/api")

app.mount("/static", StaticFiles(directory="E:/campus-gate/frontend"), name="static")

@app.on_event("startup")
def warm_ocr():
    """Load the OCR model in the background at boot so the guard's first
    plate scan doesn't wait ~10s for model initialisation."""
    import threading
    def _warm():
        try:
            plate.warm_up()
        except Exception:
            pass  # OCR stays lazy-loaded if warm-up fails
    threading.Thread(target=_warm, daemon=True).start()

@app.get("/")
def serve_frontend():
    return FileResponse("E:/campus-gate/frontend/index.html")

@app.get("/face")
def serve_face_station():
    """Dedicated Face Scan station page (demo stand-in for the college's
    face-recognition system). Enter a roll number here -> the student appears
    in the gate app's Live Entry list."""
    return FileResponse("E:/campus-gate/frontend/face-sim.html")

@app.get("/connect")
def serve_connect():
    return FileResponse("E:/campus-gate/frontend/connect.html")

@app.get("/api/server-info")
def server_info():
    """Used by the connect page to build the phone URL + QR code."""
    import socket
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        s.connect(("8.8.8.8", 80))
        ip = s.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        s.close()
    # Internet-demo tunnel (started by internet_demo.py) writes its public
    # URL here; when present the phone should use it — works from any network.
    public_url = None
    try:
        with open("E:/campus-gate/frontend/tunnel.txt") as f:
            public_url = f.read().strip() or None
    except OSError:
        pass
    return {"lan_ip": ip, "https_port": 8443, "public_url": public_url}