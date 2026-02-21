"""
MACROS Engine — MCP Setup Helper
Called by install_mcp.bat to write Claude Desktop config.
"""

import json
import os
import sys


def write_config():
    """Write the Claude Desktop config with the macros-engine MCP server."""
    # Get paths from command line args
    if len(sys.argv) < 3:
        print("Usage: setup_helper.py <python_path> <server_path>")
        sys.exit(1)

    python_path = sys.argv[1]
    server_path = sys.argv[2]

    # Claude Desktop config location
    appdata = os.environ.get("APPDATA", "")
    if not appdata:
        print("ERROR: APPDATA environment variable not found")
        sys.exit(1)

    config_dir = os.path.join(appdata, "Claude")
    config_path = os.path.join(config_dir, "claude_desktop_config.json")

    # Create directory if needed
    os.makedirs(config_dir, exist_ok=True)

    # Load existing config or start fresh
    existing = {}
    if os.path.exists(config_path):
        try:
            with open(config_path, "r", encoding="utf-8") as f:
                existing = json.load(f)
            print(f"  Loaded existing config ({len(existing.get('mcpServers', {}))} servers)")
        except Exception as e:
            print(f"  Could not read existing config: {e}")
            print(f"  Creating new config")

    # Add/update macros-engine server
    if "mcpServers" not in existing:
        existing["mcpServers"] = {}

    existing["mcpServers"]["macros-engine"] = {
        "command": python_path,
        "args": [server_path]
    }

    # Write config
    with open(config_path, "w", encoding="utf-8") as f:
        json.dump(existing, f, indent=2)

    print(f"[OK] Config written to: {config_path}")
    print(f"  Python: {python_path}")
    print(f"  Server: {server_path}")

    # Show what was written
    print(f"\n  Config contents:")
    for name, srv in existing.get("mcpServers", {}).items():
        print(f"    {name}: {srv.get('command', '?')} {' '.join(srv.get('args', []))}")


def verify_server():
    """Verify the MCP server can be imported."""
    if len(sys.argv) < 3:
        print("Usage: setup_helper.py <python_path> <server_path>")
        sys.exit(1)

    server_path = sys.argv[2]
    engine_dir = os.path.dirname(os.path.abspath(server_path))

    # Add engine dir to path
    sys.path.insert(0, engine_dir)

    try:
        # Test that all engine modules import
        from models import GameState, state_to_json, state_from_json
        print("  [OK] models.py")

        from dice import roll_dice
        result = roll_dice("2d6")
        print(f"  [OK] dice.py (test roll: {result['total']})")

        from engine import run_day
        print("  [OK] engine.py")

        from campaign_state import load_gammaria_state
        print("  [OK] campaign_state.py")

        from claude_integration import build_state_summary
        print("  [OK] claude_integration.py")

        # Test that fastmcp is available
        from mcp.server.fastmcp import FastMCP
        print("  [OK] fastmcp package")

        print("\n[OK] All modules verified successfully")

    except ImportError as e:
        print(f"\n  ERROR: Import failed — {e}")
        print(f"  Make sure all .py files are in: {engine_dir}")
        sys.exit(1)
    except Exception as e:
        print(f"\n  ERROR: {e}")
        sys.exit(1)


if __name__ == "__main__":
    print("\n--- Writing Claude Desktop Config ---")
    write_config()

    print("\n--- Verifying Server Modules ---")
    verify_server()

    print("\n--- SETUP COMPLETE ---")
