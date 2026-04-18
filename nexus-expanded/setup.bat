@echo off
REM NEXUS Trial Package Installer for Windows

echo.
echo === NEXUS Trial v3.0 Setup ===
echo.

REM Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install Python 3.8+ and try again.
    exit /b 1
)

for /f "tokens=2" %%i in ('python --version 2^>^&1') do set PYTHON_VERSION=%%i
echo ✓ Python %PYTHON_VERSION% detected

REM Install dependencies
echo.
echo Installing Python dependencies...
python -m pip install -q -r requirements.txt
if %errorlevel% neq 0 (
    echo ✗ Failed to install dependencies
    exit /b 1
)
echo ✓ Dependencies installed

REM Verify binaries
echo.
echo Validating proprietary binaries...

if exist "02_Proprietary_Engine\spigot_torch_LINUX_x86_64" (
    echo ✓ Linux x86_64 binary
)

if exist "02_Proprietary_Engine\spigot_torch_BMC_ARM64" (
    echo ✓ BMC ARM64 binary
)

if exist "02_Proprietary_Engine\spigot_torch_WINDOWS_x64.exe" (
    echo ✓ Windows x64 binary
)

REM Verify Python modules
echo.
echo Validating open-source modules...

for %%F in ("03_Core_Logic\solver_wrapper.py" "03_Core_Logic\nexus_orchestrator.py" "04_Infrastructure\redfish_client.py" "05_Testing_Tools\workload_proxy_ingress.py" "05_Testing_Tools\mock_workload_generator.py" "06_Configuration\chassis_map.json") do (
    if exist %%F (
        echo ✓ %%F
    ) else (
        echo ✗ %%F ^(MISSING^)
    )
)

echo.
echo === Setup Complete ===
echo.
echo Next steps:
echo 1. Edit 06_Configuration\chassis_map.json with your Redfish control IDs
echo 2. Run: python 03_Core_Logic\nexus_orchestrator.py --help
echo.
echo For detailed instructions, see: 01_Documentation\README.md
echo.
pause
