@echo off
echo Installing dependencies...
pip install PyQt6 pyinstaller --quiet

echo.
echo Building ScreenBlind.exe...
rem Build from the spec file — it carries the Per-Monitor V2 DPI manifest,
rem without which blinds mis-size on displays scaled above 100%.
python -m PyInstaller --noconfirm ScreenBlind.spec

echo.
if exist "dist\ScreenBlind.exe" (
    echo Build successful! Executable is at: dist\ScreenBlind.exe
) else (
    echo Build failed. Check the output above for errors.
)
pause
