@echo off
rem Makes Mirage start (hidden in the tray) when you log into Windows.
rem You can also turn this on/off in Mirage > Settings > Start with Windows.
cd /d "%~dp0"
python mirage_app.py --enable-startup
pause
