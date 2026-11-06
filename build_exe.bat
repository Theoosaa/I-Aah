@echo off
REM ==========================================================================
REM  Baut eine eigenstaendige Windows-.exe von I-Aah (kein Python noetig zum
REM  Ausfuehren). Einmalig vorher die Build-Werkzeuge installieren:
REM
REM      pip install pyinstaller openpyxl cryptography
REM
REM  Danach dieses Skript per Doppelklick starten. Ergebnis: dist\I-Aah.exe
REM ==========================================================================
cd /d "%~dp0"

where pyinstaller >nul 2>nul
if errorlevel 1 (
    echo PyInstaller ist nicht installiert.
    echo Bitte zuerst ausfuehren:  pip install pyinstaller openpyxl cryptography
    pause
    exit /b 1
)

pyinstaller --noconfirm --clean --onefile --windowed ^
  --name I-Aah ^
  --collect-all pdfplumber ^
  --collect-all pdfminer ^
  --collect-submodules matplotlib ^
  --hidden-import openpyxl ^
  --hidden-import cryptography ^
  --hidden-import pypdf ^
  --collect-all reportlab ^
  kontoanalyse.py

echo.
if exist dist\I-Aah.exe (
    echo Fertig!  Die EXE liegt hier:  dist\I-Aah.exe
) else (
    echo Build fehlgeschlagen - siehe Ausgabe oben.
)
pause
