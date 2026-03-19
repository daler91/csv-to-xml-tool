@echo off
echo ============================================================
echo   SBA CSV-to-XML Tool - Setup
echo ============================================================
echo.

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ERROR: Python is not installed.
    echo.
    echo Please download Python from https://www.python.org/downloads/
    echo IMPORTANT: Check "Add Python to PATH" during installation.
    echo.
    pause
    exit /b 1
)

echo Installing required packages...
pip install -r requirements.txt
echo.

if errorlevel 1 (
    echo ERROR: Failed to install packages.
    echo Try running this as Administrator.
    pause
    exit /b 1
)

echo ============================================================
echo   Setup complete! You can now run the tool.
echo.
echo   To start: double-click "run.bat"
echo   Or type:  python run.py
echo ============================================================
echo.
pause
