@echo off
cd /d "%~dp0"
start "" http://localhost:5200
py -3 app.py
