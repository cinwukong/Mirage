@echo off
cd /d "%~dp0"
echo Stopping any running Mirage...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'mirage' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Installing Mirage...
python -m pip install --upgrade pip
python -m pip install -r requirements.txt
if errorlevel 1 (
  echo.
  echo Install failed. Make sure Python 3.9+ is installed from python.org
  echo and that "Add Python to PATH" was ticked during setup.
  pause
  exit /b 1
)
echo.
echo Installing tray icon support...
python -m pip install pystray pillow
if errorlevel 1 echo (Tray icon couldn't be installed - Mirage still works, just without the tray icon.)
echo.
echo Starting Mirage...
start "" pythonw mirage_app.py
timeout /t 3 >nul
