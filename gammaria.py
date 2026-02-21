"""
GAMMARIA — MACROS Engine v4.1
Standalone game application. The engine is the outer loop.
Claude is called only for creative content via MCP.

Run:  python gammaria.py
Open: http://localhost:8000
"""

import os
import sys
import threading
import time
import webbrowser
import uvicorn

# When running under pythonw.exe, stdout/stderr are None — redirect to devnull
if sys.stdout is None:
    sys.stdout = open(os.devnull, 'w')
if sys.stderr is None:
    sys.stderr = open(os.devnull, 'w')

# Ensure engine directory is on the path
ENGINE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, ENGINE_DIR)

from web.routes import app, init_game

PORT = 8000
DATA_DIR = os.path.join(ENGINE_DIR, "data")


def _open_browser():
    """Open the browser after the server has had time to start."""
    time.sleep(2.5)
    webbrowser.open(f"http://localhost:{PORT}")


def main():
    # Initialize game state
    init_game(DATA_DIR)

    print("=" * 50)
    print("  GAMMARIA — MACROS Engine v4.1")
    print("=" * 50)
    print(f"  Server: http://localhost:{PORT}")
    print(f"  Data:   {DATA_DIR}")
    print()
    print("  Browser will open automatically.")
    print("  Connect Claude Desktop MCP for creative content.")
    print("  Press Ctrl+C to stop.")
    print("=" * 50)
    print()

    # Open browser on a background thread so server starts first
    threading.Thread(target=_open_browser, daemon=True).start()

    # Start server (blocking)
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="warning")


if __name__ == "__main__":
    main()
