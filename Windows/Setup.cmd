@echo off
setlocal
cd /d "%~dp0"
python -m venv .venv
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -m pip install -r requirements.txt
if errorlevel 1 goto failed
".venv\Scripts\python.exe" -c "import tkinter; from PySide6 import QtWidgets"
if errorlevel 1 goto failed
echo Setup complete. Open Start Widget.vbs to run the tracker.
pause
exit /b 0
:failed
echo Setup failed. Install Python 3.10 or newer with Tkinter and add Python to PATH.
pause
exit /b 1
