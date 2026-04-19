@echo off
REM NEXUS v4.0 — Setup script (Windows)

echo ======================================
echo  NEXUS v4.0 -- Setup
echo ======================================

where python >nul 2>nul
if errorlevel 1 (
    echo [X] python not found. Please install Python 3.8 or later.
    exit /b 1
)

if not exist .venv (
    echo [*] Creating virtual environment...
    python -m venv .venv
)

call .venv\Scripts\activate.bat

python -m pip install --upgrade pip --quiet

if exist requirements.txt (
    echo [*] Installing dependencies from requirements.txt...
    pip install -r requirements.txt --quiet
) else (
    echo [*] Installing baseline dependencies...
    pip install requests pyyaml --quiet
)

echo.
echo [OK] Setup complete.
echo.
echo Next step: validate your hardware
echo     .venv\Scripts\activate.bat
echo     python tools\validate_v4.py --target ^<BMC_IP^> --user ^<user^> --pass ^<password^>
echo.
