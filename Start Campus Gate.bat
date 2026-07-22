@echo off
title Campus Gate Server
cd /d "%~dp0backend"
echo ============================================================
echo   CAMPUS GATE  -  server starting...
echo ============================================================
echo.
echo   When you see "Application startup complete", open a browser
echo   on THIS computer and go to:
echo.
echo        http://localhost:8000
echo.
echo   Keep this window OPEN while using the app.
echo   Close this window to stop the server.
echo ============================================================
echo.
python -m uvicorn main:app --host 0.0.0.0 --port 8000
echo.
echo Server stopped. Press any key to close.
pause >nul
