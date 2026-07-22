@echo off
title Campus Gate Server (Internet Demo - works from any network)
cd /d "%~dp0"
echo ============================================================
echo   CAMPUS GATE  -  INTERNET DEMO
echo   Phone can use its OWN mobile data - no shared Wi-Fi needed.
echo   (Laptop itself must have internet, on any network.)
echo ============================================================
echo.
python internet_demo.py
echo.
echo Press any key to close.
pause >nul
