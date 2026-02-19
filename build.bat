@echo off
REM Build EncounterOS as a portable .exe (one file). Requires: pip install pyinstaller
echo Building EncounterOS...
pyinstaller --clean encounteros.spec
if %ERRORLEVEL% neq 0 exit /b %ERRORLEVEL%
echo.
echo Done. Run: dist\EncounterOS.exe
echo To ship: zip the folder containing the .exe (or copy the exe); config/party/data are created next to the exe on first run.
