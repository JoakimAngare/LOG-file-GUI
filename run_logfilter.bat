@echo off
setlocal

REM Change to the folder where this .bat is located
cd /d "%~dp0"

REM Prefer local venv if it exists
if exist "venv\Scripts\python.exe" (
    echo Using venv\Scripts\python.exe
    "venv\Scripts\python.exe" logfilter_gui.py
) else (
    echo Using system Python
    python logfilter_gui.py
)

endlocal
