@echo off
title Campus Gate Server (Phone Demo - HTTPS)
cd /d "%~dp0backend"
echo ============================================================
echo   CAMPUS GATE  -  PHONE DEMO (HTTPS)
echo ============================================================
echo.
echo   Step 1: creating a certificate for this Wi-Fi address...
python gen_cert.py
echo.
echo   Step 2: starting the secure server...
echo.
echo   On THIS laptop open:   https://localhost:8443
echo        (warden login, and the phone-connect QR page)
echo.
echo   On the PHONE: open https://localhost:8443 here first, click
echo   "Use on phone - connect and QR" on the login page, then scan
echo   the QR with the phone. Accept the security notice once.
echo.
echo   Keep this window OPEN. Close it to stop the server.
echo ============================================================
echo.
python -m uvicorn main:app --host 0.0.0.0 --port 8443 --ssl-keyfile certs/server.key --ssl-certfile certs/server.crt
echo.
echo Server stopped. Press any key to close.
pause >nul
