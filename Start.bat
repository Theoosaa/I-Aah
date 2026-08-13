@echo off
REM Startet die Kontoanalyse. Beim ersten Mal Abhaengigkeiten installieren:
REM   pip install -r requirements.txt
cd /d "%~dp0"
python kontoanalyse.py
if errorlevel 1 pause
