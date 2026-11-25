@echo off
cd /d "%~dp0"
rem If this copy was unzipped inside an existing Mirage folder, update that install instead.
set "TARGET="
if exist "%~dp0..\model\" if exist "%~dp0..\mirage.py" set "TARGET=%~dp0.."
if defined TARGET (
  echo Updating your existing Mirage...
  for %%F in ("%~dp0*") do copy /y "%%F" "%TARGET%\" >nul
  start "" /d "%TARGET%" cmd /c install.bat
  exit /b
)
echo Stopping any running Mirage...
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'mirage' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Installing Mirage...
if exist "%~dp0Mirage-main\install.bat" (timeout /t 2 >nul & rd /s /q "%~dp0Mirage-main" >nul 2>&1)
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
