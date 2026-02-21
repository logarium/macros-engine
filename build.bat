@echo off
echo ================================================
echo   GAMMARIA — MACROS Engine Build
echo ================================================
echo.
echo Installing dependencies...
pip install -r requirements.txt
pip install pyinstaller
echo.
echo Building executable...
pyinstaller --onefile --name Gammaria ^
    --add-data "web;web" ^
    --add-data "docs;docs" ^
    --add-data "data;data" ^
    --hidden-import uvicorn.logging ^
    --hidden-import uvicorn.protocols.http ^
    --hidden-import uvicorn.protocols.http.auto ^
    --hidden-import uvicorn.protocols.websockets ^
    --hidden-import uvicorn.protocols.websockets.auto ^
    --hidden-import uvicorn.lifespan ^
    --hidden-import uvicorn.lifespan.on ^
    gammaria.py
echo.
echo ================================================
echo   Build complete: dist\Gammaria.exe
echo ================================================
pause
