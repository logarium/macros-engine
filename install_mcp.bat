@echo off
echo.
echo ============================================================
echo   MACROS ENGINE v2.0 — MCP INSTALLER
echo   One-time setup for Claude Desktop integration
echo ============================================================
echo.

:: Check Python
python --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Python not found. Install from python.org
    pause
    exit /b 1
)
echo [OK] Python found

:: Check Node.js
node --version >nul 2>&1
if %errorlevel% neq 0 (
    echo ERROR: Node.js not found. Install from nodejs.org
    pause
    exit /b 1
)
echo [OK] Node.js found

:: Install fastmcp
echo.
echo Installing FastMCP (Python MCP SDK)...
pip install fastmcp 2>nul
pip install "mcp[cli]" 2>nul
echo [OK] FastMCP installed

:: Get paths
set "SERVER_PATH=%~dp0mcp_server.py"
for /f "delims=" %%i in ('where python') do (
    set "PYTHON_PATH=%%i"
    goto :found_python
)
:found_python

echo.
echo Server path: %SERVER_PATH%
echo Python path: %PYTHON_PATH%

:: Run the helper script to write config and verify
echo.
python "%~dp0setup_helper.py" "%PYTHON_PATH%" "%SERVER_PATH%"

if %errorlevel% neq 0 (
    echo.
    echo ============================================================
    echo   SETUP FAILED — see errors above
    echo ============================================================
    echo.
    echo If the config write failed, you can edit it manually:
    echo   1. Open Claude Desktop
    echo   2. Settings ^> Developer ^> Edit Config
    echo   3. Add this to the JSON:
    echo.
    echo   "mcpServers": {
    echo     "macros-engine": {
    echo       "command": "%PYTHON_PATH%",
    echo       "args": ["%SERVER_PATH%"]
    echo     }
    echo   }
    echo.
    pause
    exit /b 1
)

echo.
echo ============================================================
echo   SETUP COMPLETE
echo ============================================================
echo.
echo NEXT STEPS:
echo   1. Close Claude Desktop completely
echo      (right-click tray icon, Quit — not just close window)
echo   2. Reopen Claude Desktop
echo   3. Look for the HAMMER ICON in the chat input box
echo   4. Start a new conversation and say:
echo      "Load the Gammaria campaign and show me the game state"
echo.
pause
