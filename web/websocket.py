"""
MACROS Engine v4.0 — WebSocket Manager
Pushes real-time state updates to connected browser clients.
"""

import json
import asyncio
from fastapi import WebSocket


class ConnectionManager:
    """Manages active WebSocket connections and broadcasts events."""

    def __init__(self):
        self.active: list[WebSocket] = []

    async def connect(self, ws: WebSocket):
        await ws.accept()
        self.active.append(ws)

    def disconnect(self, ws: WebSocket):
        if ws in self.active:
            self.active.remove(ws)

    async def broadcast(self, event: str, data: dict = None):
        """Send an event to all connected clients."""
        message = json.dumps({"event": event, "data": data or {}})
        disconnected = []
        for ws in self.active:
            try:
                await ws.send_text(message)
            except Exception:
                disconnected.append(ws)
        for ws in disconnected:
            self.disconnect(ws)

    async def broadcast_sync(self, event: str, data: dict = None):
        """
        Synchronous-friendly broadcast. Schedules the async broadcast
        on the running event loop. Safe to call from non-async code.
        """
        try:
            loop = asyncio.get_running_loop()
            loop.create_task(self.broadcast(event, data))
        except RuntimeError:
            pass  # No event loop running — skip (e.g., during init)

    @property
    def client_count(self) -> int:
        return len(self.active)
