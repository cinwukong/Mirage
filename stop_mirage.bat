@echo off
rem Stops Mirage completely (you can also use Quit in the tray menu or app).
powershell -NoProfile -Command "Get-CimInstance Win32_Process | Where-Object { $_.Name -like 'python*' -and $_.CommandLine -match 'mirage' } | ForEach-Object { Stop-Process -Id $_.ProcessId -Force }"
echo Mirage stopped.
timeout /t 2 >nul
