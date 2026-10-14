@echo off
setlocal
cd /d "%~dp0"
set "SB_PYTHON=python"
if exist ".venv\Scripts\python.exe" set "SB_PYTHON=.venv\Scripts\python.exe"
if exist ".venv-qt\Scripts\python.exe" set "SB_PYTHON=.venv-qt\Scripts\python.exe"
echo Installing dependencies...
"%SB_PYTHON%" -m pip install -r requirements.txt pyinstaller --quiet
if errorlevel 1 exit /b 1

echo.
echo Building ScreenBlind.exe...
rem Build from the spec file — it carries the Per-Monitor V2 DPI manifest,
rem without which blinds mis-size on displays scaled above 100%.
"%SB_PYTHON%" -m PyInstaller --noconfirm ScreenBlind.spec
if errorlevel 1 exit /b 1

echo.
if exist "dist\ScreenBlind.exe" (
    echo Build successful! Executable is at: dist\ScreenBlind.exe
) else (
    echo Build failed. Check the output above for errors.
)
pause
