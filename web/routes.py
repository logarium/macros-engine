"""
MACROS Engine v4.0 — FastAPI Routes
Player-facing endpoints + Creative API for MCP bridge.
"""

import json
import os
from fastapi import FastAPI, WebSocket, WebSocketDisconnect, Request
from fastapi.staticfiles import StaticFiles
from fastapi.responses import HTMLResponse, FileResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional

from game_loop import GameLoop
from web.websocket import ConnectionManager


# ─────────────────────────────────────────────────────
# APP SETUP
# ─────────────────────────────────────────────────────

app = FastAPI(title="Gammaria — MACROS Engine", version="4.0")
manager = ConnectionManager()
game = GameLoop()


def init_game(data_dir: str = None):
    """Initialize the game loop. Called from gammaria.py."""
    game.init(data_dir)

    # Wire up WebSocket callbacks
    def on_phase_change(phase, data):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast("phase_change", data))
        except RuntimeError:
            pass

    def on_log_entry(entry):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast("log_entry", entry))
        except RuntimeError:
            pass

    def on_narration(narr_type, text):
        import asyncio
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(manager.broadcast("narration", {
                "type": narr_type, "text": text,
            }))
        except RuntimeError:
            pass

    game._on_phase_change = on_phase_change
    game._on_log_entry = on_log_entry
    game._on_narration = on_narration


# ─────────────────────────────────────────────────────
# STATIC FILES
# ─────────────────────────────────────────────────────

static_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
app.mount("/static", StaticFiles(directory=static_dir), name="static")

# Serve portrait images from macros-engine/images/
images_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "images")
if os.path.isdir(images_dir):
    app.mount("/images", StaticFiles(directory=images_dir), name="images")


@app.get("/", response_class=HTMLResponse)
async def index():
    index_path = os.path.join(static_dir, "index.html")
    with open(index_path, "r", encoding="utf-8") as f:
        html = f.read()
    # Cache-bust static assets so browser always loads latest code
    import time
    ver = str(int(time.time()))
    html = html.replace('style.css"', f'style.css?v={ver}"')
    html = html.replace('app.js"', f'app.js?v={ver}"')
    return HTMLResponse(
        content=html,
        headers={"Cache-Control": "no-cache, no-store, must-revalidate"},
    )


# ─────────────────────────────────────────────────────
# WEBSOCKET
# ─────────────────────────────────────────────────────

@app.websocket("/ws")
async def websocket_endpoint(ws: WebSocket):
    await manager.connect(ws)
    try:
        # Send initial state on connect
        state_data = game.get_full_state()
        await ws.send_text(json.dumps({"event": "state_update", "data": state_data}))

        # Keep connection alive, receive any client messages
        while True:
            data = await ws.receive_text()
            # Client can send ping/keepalive; we don't need to act on it
    except WebSocketDisconnect:
        manager.disconnect(ws)
    except Exception:
        manager.disconnect(ws)


# ─────────────────────────────────────────────────────
# PLAYER-FACING API
# ─────────────────────────────────────────────────────

@app.get("/api/state")
async def get_state():
    """Full game state for UI rendering."""
    return JSONResponse(game.get_full_state())


class TravelRequest(BaseModel):
    destination: str


@app.post("/api/travel")
async def travel(req: TravelRequest):
    """Player clicks a CP button."""
    result = game.travel_to(req.destination)

    # Broadcast state update to all connected clients
    state_data = game.get_full_state()
    await manager.broadcast("state_update", state_data)

    if result.get("success") and game.creative_queue.pending_count() > 0:
        await manager.broadcast("creative_pending", {
            "count": game.creative_queue.pending_count(),
            "types": game.creative_queue.pending_types(),
        })

    return JSONResponse(result)


class RestRequest(BaseModel):
    days: int = 1


@app.post("/api/rest")
async def rest(req: RestRequest):
    """Player voluntarily rests — runs T&P for N days without travel."""
    result = game.rest_days(req.days)

    state_data = game.get_full_state()
    await manager.broadcast("state_update", state_data)

    if result.get("success") and game.creative_queue.pending_count() > 0:
        await manager.broadcast("creative_pending", {
            "count": game.creative_queue.pending_count(),
            "types": game.creative_queue.pending_types(),
        })

    return JSONResponse(result)


@app.post("/api/save")
async def save_game():
    """Save current game state."""
    filename = game.save_game()
    return JSONResponse({"success": True, "filename": filename})


class LoadRequest(BaseModel):
    filename: str


@app.post("/api/load")
async def load_game(req: LoadRequest):
    """Load a save file."""
    result = game.load_game(req.filename)
    if result.get("success"):
        state_data = game.get_full_state()
        await manager.broadcast("state_update", state_data)
    return JSONResponse(result)


@app.get("/api/saves")
async def list_saves():
    """List available save files."""
    return JSONResponse({"saves": game.list_saves()})


# ─────────────────────────────────────────────────────
# SESSION LIFECYCLE (DG-19)
# ─────────────────────────────────────────────────────

@app.post("/api/session/start")
async def start_session():
    """SSM — Start new session."""
    result = game.start_session()
    if result.get("success"):
        state_data = game.get_full_state()
        await manager.broadcast("state_update", state_data)
    return JSONResponse(result)


@app.post("/api/session/end")
async def end_session():
    """ENDS — End current session."""
    result = game.end_session()
    if result.get("success"):
        state_data = game.get_full_state()
        await manager.broadcast("state_update", state_data)
        if game.creative_queue.pending_count() > 0:
            await manager.broadcast("creative_pending", {
                "count": game.creative_queue.pending_count(),
                "types": game.creative_queue.pending_types(),
            })
    return JSONResponse(result)


@app.get("/api/session/report/{session_id}")
async def get_session_report(session_id: int):
    """Get or generate HTML report for a session."""
    html = game.get_session_report(session_id)
    return HTMLResponse(content=html)


# ─────────────────────────────────────────────────────
# COMBAT (DG-16)
# ─────────────────────────────────────────────────────

class CombatStartRequest(BaseModel):
    npc_name: str


@app.post("/api/combat/start")
async def start_combat(req: CombatStartRequest):
    """Start combat with an NPC in the current zone."""
    result = game.start_combat_with_npc(req.npc_name)
    state_data = game.get_full_state()
    await manager.broadcast("state_update", state_data)
    if result.get("success"):
        await manager.broadcast("combat_update", result.get("combat", {}))
    return JSONResponse(result)


class CombatActionRequest(BaseModel):
    action: str  # "ATTACK" or "FLEE"


@app.post("/api/combat/action")
async def combat_action(req: CombatActionRequest):
    """Player chose ATTACK or FLEE for this combat round."""
    result = game.combat_action(req.action)

    # Broadcast state update
    state_data = game.get_full_state()
    await manager.broadcast("state_update", state_data)

    # If combat ended and narration queued, notify
    if game.creative_queue.pending_count() > 0:
        await manager.broadcast("creative_pending", {
            "count": game.creative_queue.pending_count(),
            "types": game.creative_queue.pending_types(),
        })

    return JSONResponse(result)


@app.get("/api/combat/state")
async def get_combat_state():
    """Get current combat state for UI rendering."""
    if game.combat_state:
        return JSONResponse({"active": True, **game.combat_state.to_ui_dict()})
    return JSONResponse({"active": False})


# ─────────────────────────────────────────────────────
# CREATIVE API (for MCP bridge)
# ─────────────────────────────────────────────────────

@app.get("/api/creative/pending")
async def get_creative_pending():
    """
    Get pending creative requests for Claude.
    The MCP server calls this endpoint.
    """
    return JSONResponse(game.get_creative_pending())


class CreativeSubmitRequest(BaseModel):
    response_json: str


@app.post("/api/creative/submit")
async def submit_creative_response(req: CreativeSubmitRequest):
    """
    Submit creative responses from Claude.
    The MCP server calls this endpoint.
    """
    result = game.receive_creative_response(req.response_json)

    if result.get("success"):
        state_data = game.get_full_state()
        await manager.broadcast("state_update", state_data)
        await manager.broadcast("creative_resolved", {
            "responses_applied": result.get("responses_applied", 0),
        })
    else:
        # DG-23: Broadcast error to UI
        await manager.broadcast("error", {
            "message": result.get("error", "Creative response failed"),
            "retry_attempted": result.get("retry_attempted", False),
        })

    return JSONResponse(result)


# ─────────────────────────────────────────────────────
# FORGE API (manual forge triggering)
# ─────────────────────────────────────────────────────

@app.post("/api/forge")
async def trigger_forge(request: Request):
    """Player triggers a forge from the FORGE tab."""
    body = await request.json()
    forge_type = body.get("forge_type")
    params = body.get("params", {})
    result = game.trigger_forge(forge_type, params)

    if result.get("success"):
        state_data = game.get_full_state()
        await manager.broadcast("state_update", state_data)
        await manager.broadcast("creative_pending", {
            "count": game.creative_queue.pending_count(),
            "types": game.creative_queue.pending_types(),
        })

    return JSONResponse(result)


# Also accept raw JSON body (for flexibility)
@app.post("/api/creative/submit_raw")
async def submit_creative_response_raw(request: Request):
    """Alternative endpoint that accepts raw JSON body."""
    body = await request.body()
    result = game.receive_creative_response(body.decode("utf-8"))

    if result.get("success"):
        state_data = game.get_full_state()
        await manager.broadcast("state_update", state_data)
        await manager.broadcast("creative_resolved", {
            "responses_applied": result.get("responses_applied", 0),
        })
    else:
        await manager.broadcast("error", {
            "message": result.get("error", "Creative response failed"),
        })

    return JSONResponse(result)


# ─────────────────────────────────────────────────────
# MODE MACROS (DG-22)
# ─────────────────────────────────────────────────────

class ModeRequest(BaseModel):
    mode: Optional[str] = None


@app.post("/api/mode")
async def set_mode(req: ModeRequest):
    """Set or clear narrative mode."""
    result = game.set_mode(req.mode)
    if result.get("success"):
        state_data = game.get_full_state()
        await manager.broadcast("state_update", state_data)
    return JSONResponse(result)


@app.post("/api/rumor")
async def trigger_rumor():
    """Trigger a one-shot RUMOR request."""
    result = game.trigger_rumor()
    if result.get("success"):
        state_data = game.get_full_state()
        await manager.broadcast("state_update", state_data)
        if game.creative_queue.pending_count() > 0:
            await manager.broadcast("creative_pending", {
                "count": game.creative_queue.pending_count(),
                "types": game.creative_queue.pending_types(),
            })
    return JSONResponse(result)


# ─────────────────────────────────────────────────────
# ENGINE CHAT (player input)
# ─────────────────────────────────────────────────────

class ChatInputRequest(BaseModel):
    text: str


@app.post("/api/chat/input")
async def submit_player_input(req: ChatInputRequest):
    """Player types in-character intent via chat panel."""
    result = game.receive_player_input(req.text)
    if result.get("success"):
        state_data = game.get_full_state()
        await manager.broadcast("state_update", state_data)
        if game.creative_queue.pending_count() > 0:
            await manager.broadcast("creative_pending", {
                "count": game.creative_queue.pending_count(),
                "types": game.creative_queue.pending_types(),
            })
    return JSONResponse(result)
