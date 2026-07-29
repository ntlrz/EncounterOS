@echo off
REM Build EncounterOS as a portable onedir distribution. Requires: pip install pyinstaller
echo Building EncounterOS...
pyinstaller --clean encounteros.spec
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
echo.
echo Done. Run: dist\EncounterOS\EncounterOS.exe
echo To ship: zip the complete dist\EncounterOS folder; config/party/data are created next to the exe on first run.
