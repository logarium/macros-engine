# ENGINE CHAT WINDOW — Design Guidelines v1.0

## PURPOSE
The engine GUI becomes the single play surface. All in-character content — narrative, dialogue, intent, mechanical results — displays here. Claude Desktop is reserved for out-of-character discussion (design talk, debugging, rule questions).

## ARCHITECTURE

### Two-Place Model
- **Engine GUI** = the stage (pure play)
- **Claude Desktop** = the green room (OOC talk, design, debugging)

### Flow
1. Player types intent in engine chat box
2. Engine writes intent to shared file
3. Player alt-tabs to Claude Desktop, types nudge word (e.g. "go")
4. Claude reads intent via MCP tool, processes it
5. Claude writes narrative response via MCP tool (apply_llm_judgments or new submit tool)
6. Engine displays response in chat window
7. Player reads and continues

### Nudge System
- Player triggers Claude with a single word in Claude Desktop
- Claude calls MCP tool to read player input
- Claude processes and responds through existing creative response pipeline
- This preserves continuous conversation context (critical for narrative quality)
- API calls are explicitly NOT used — continuous context is a core feature

---

## GUI CHANGES NEEDED

### New: Chat Panel
- **Location**: Right side or bottom of main window, always visible during play
- **Components**:
  - **Display area**: Scrollable text area showing all narrative content, mechanical results, and player input
  - **Input field**: Single-line or multi-line text entry at bottom
  - **Send button**: Writes input to shared file (or Enter key)
- **Styling**: 
  - Player input: distinct color (e.g. white or light blue)
  - Claude narrative: main text color (warm, readable)
  - Mechanical results: existing color coding (dice, clocks, etc.)
  - System messages: dim/muted

### Display Rules
- Travel narration (NARR_ARRIVAL) displays in chat panel, not just the log
- NPAG results display in chat panel
- Encounter narration displays in chat panel
- Clock audit results can stay in the mechanical log (compact format)
- All creative content from apply_llm_judgments should route to chat panel

### Input Rules
- Enter sends input
- Input is written to `data/player_input.json`
- Format: `{"input": "text here", "timestamp": "ISO", "session_id": N, "zone": "current zone"}`
- File is cleared after Claude reads it
- Empty input = no file written

---

## MCP SERVER CHANGES NEEDED

### New Tool: `get_player_input`
```
@server.tool()
def get_player_input() -> str:
    """
    Read the player's latest input from the shared file.
    Returns the input text and context, or 'No input pending.'
    Clears the file after reading.
    """
```
- Reads `data/player_input.json`
- Returns input text + current zone + session context
- Deletes the file after reading (prevents re-reads)
- If no file exists, returns "No input pending."

### Updated: Creative Response Display
- When apply_llm_judgments or submit_creative_response returns narrative content, the engine should route it to the chat panel
- Mechanical state changes (clock advances, facts) go to the log as before
- The `forwarded to web UI` mechanism already exists — extend it to handle player-input responses

---

## FILE PROTOCOL

### Player Input
- **File**: `data/player_input.json`
- **Written by**: Engine GUI (on Enter/Send)
- **Read by**: MCP server (`get_player_input` tool)
- **Cleared by**: MCP server after reading

### Creative Response  
- **File**: `data/pending_creative.json` (existing)
- **Written by**: Engine (after T&P/travel)
- **Read by**: MCP server (`get_pending_requests`)
- **Cleared by**: MCP server after `apply_llm_judgments`

### Narrative Display
- **Mechanism**: Engine already receives responses via `submit_creative_response` or `apply_llm_judgments` callback
- **New requirement**: Route narrative content to chat panel display area
- **Format**: Engine parses response type — if NARR_*, NPAG, ENCOUNTER → chat panel. If CLOCK_AUDIT → log only.

---

## CLAUDE DESKTOP WORKFLOW

When player types nudge word ("go"), Claude:

1. Calls `get_player_input()` — reads what player typed in engine
2. If input is play intent (dialogue, action, exploration):
   - Process narratively using full conversation context
   - Respond via `apply_llm_judgments` or new response tool
   - Response displays in engine chat panel
3. If input is empty / no file:
   - Check `get_pending_requests()` for mechanical queue
   - Process any pending creative requests
4. If pending requests AND player input both exist:
   - Process mechanical requests first
   - Then address player intent

### Nudge Words
- Any single word works: "go", "check", "next", etc.
- Claude recognizes these as "read engine input and process"
- NOT a command — just a trigger to check the pipe

---

## WHAT NOT TO BUILD (YET)

- No API integration (continuous context is the priority)
- No auto-polling (nudge system is intentional)
- No voice input (future consideration for walks)
- No split-screen Claude Desktop embed (platform limitation)

---

## TESTING CHECKLIST

1. [ ] Player types intent in engine → file written
2. [ ] Player nudges Claude → Claude reads input via MCP
3. [ ] Claude responds → response appears in engine chat panel
4. [ ] Travel narration displays in chat panel
5. [ ] Mechanical results display in log (existing behavior preserved)
6. [ ] NPAG and encounter narration display in chat panel
7. [ ] File cleanup works (no stale input/responses)
8. [ ] Multiple exchanges work without restart
9. [ ] Engine restart doesn't lose chat history (persist to session log)
