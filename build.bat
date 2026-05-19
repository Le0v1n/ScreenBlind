@echo off
echo Installing dependencies...
pip install PyQt6 pyinstaller --quiet

echo.
echo Building ScreenBlind.exe...
python -m PyInstaller ^
  --onefile ^
  --windowed ^
  --name ScreenBlind ^
  --icon icon.ico ^
  --add-data "media_assets;media_assets" ^
  --add-data "icon.ico;." ^
  --hidden-import PyQt6.QtWidgets ^
  --hidden-import PyQt6.QtCore ^
  --hidden-import PyQt6.QtGui ^
  main.py

echo.
if exist "dist\ScreenBlind.exe" (
    echo Build successful! Executable is at: dist\ScreenBlind.exe
) else (
    echo Build failed. Check the output above for errors.
)
pause
