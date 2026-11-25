@echo off
rem Opens the Mirage app (or shows it if it's already running in the tray).
cd /d "%~dp0"
start "" pythonw mirage_app.py
