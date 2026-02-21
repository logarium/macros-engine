"""
MACROS Engine v2.0 — GUI Application
Run: python gui.py

v2.0 changes:
  - Tabbed left panel: Clocks, NPCs, Factions, World
  - NPC tab shows all NPCs with zone, role, companion marker
  - Faction tab shows all factions with status and disposition
  - World tab shows relationships, discoveries, threads, PC state
  - Action log: full detail (no truncation)
  - Color-coded by category throughout
"""
import tkinter as tk
from tkinter import ttk, scrolledtext, messagebox, filedialog
import json, sys, os, shutil
from datetime import datetime

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from campaign_state import load_gammaria_state
from engine import run_day
from models import GameState, Clock, state_to_json, state_from_json
from dice import roll_dice
from claude_integration import (
    write_request, response_exists, read_response, apply_response,
    launch_claude_desktop, generate_mcp_config, write_state_context,
    build_clipboard_prompt, parse_pasted_response,
)


# ── Shared pending file (GUI → MCP server) ──
def _write_pending_to_disk(requests, state, day_logs):
    """Write pending creative requests to shared file for MCP server."""
    data_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
    os.makedirs(data_dir, exist_ok=True)
    payload = {
        "requests": requests,
        "state_summary": {
            "session_id": state.session_id,
            "date": state.in_game_date,
            "zone": state.pc_zone,
            "season": state.season,
        },
        "day_logs": [{k: v for k, v in dl.items() if k != "llm_requests"} for dl in day_logs],
        "timestamp": datetime.now().isoformat(),
    }
    path = os.path.join(data_dir, "pending_creative.json")
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, indent=2)


def _clear_pending_file():
    """Remove the shared pending file."""
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "pending_creative.json")
    if os.path.exists(path):
        os.remove(path)


COLORS = {
    "bg_dark": "#1a1a2e", "bg_medium": "#16213e", "bg_light": "#0f3460",
    "bg_entry": "#2a2a4e", "text": "#e0e0e0", "text_dim": "#8888aa",
    "text_bright": "#ffffff", "accent": "#e94560", "accent2": "#ff6b6b",
    "gold": "#f4a836", "green": "#4ecca3", "yellow": "#ffd700",
    "red": "#ff4444", "orange": "#ff8c00", "blue": "#4488ff",
    "purple": "#bb88ff", "cyan": "#4ecdc4", "clock_bg": "#252545",
    "clock_fill_green": "#2d6a4f", "clock_fill_yellow": "#7c6f1b",
    "clock_fill_red": "#6b1a1a", "clock_fill_fired": "#444444",
    "button_bg": "#0f3460", "button_active": "#1a5276", "border": "#333355",
}

EVENT_TAG_MAP = {
    "T&P": None, "DICE": "dice",
    "BX_COMBAT": "encounter", "BX_ROUND": "encounter", "BX_RESULT": "encounter",
    "EL": "encounter", "EL_DEF": "encounter", "ENCOUNTER": "encounter",
    "REACTION": "encounter", "MORALE": "encounter",
    "CLOCK_ADVANCE": "clock_advance", "CLOCK_REDUCE": "clock_advance",
    "CLOCK_FORGE": "clock_advance", "CLOCK_AUDIT": "clock_advance", "TRIGGER": "trigger",
    "NPAG": "npag", "NPAG_RESOLUTION": "npag",
    "TRAVEL": "engine", "ZONE_CHANGE": "engine",
    "LLM_DECISION": "llm", "LLM_JUDGMENT": "llm", "RULING": "llm",
    "ZONE_FORGE": "forge", "NPC_FORGE": "forge", "CAN_FORGE": "forge",
    "FAC_FORGE": "forge", "PE_FORGE": "forge",
    "FACT": "dim", "NARRATIVE_BEAT": "dim",
    "SESSION": "header", "SAVE": "dim",
    "PARTY": "engine", "LOOT": "dice", "REST": "dim", "ABILITY_CHECK": "dice",
    "NPC_UPDATE": "forge", "FAC_UPDATE": "forge", "REL_UPDATE": "forge",
}

EVENT_ICON_MAP = {
    "DICE": "\U0001f3b2", "BX_COMBAT": "\u2694\ufe0f", "BX_ROUND": "\u2694\ufe0f",
    "BX_RESULT": "\u2694\ufe0f", "EL": "\u2694\ufe0f", "EL_DEF": "\u2694\ufe0f",
    "ENCOUNTER": "\u2694\ufe0f", "REACTION": "\U0001f465", "MORALE": "\U0001f3f3\ufe0f",
    "CLOCK_ADVANCE": "\u23f0", "CLOCK_REDUCE": "\u23f0", "CLOCK_FORGE": "\u23f0",
    "CLOCK_AUDIT": "\U0001f50d", "TRIGGER": "\U0001f525",
    "NPAG": "\U0001f465", "NPAG_RESOLUTION": "\U0001f465",
    "TRAVEL": "\U0001f6e4\ufe0f", "ZONE_CHANGE": "\U0001f30d",
    "LLM_DECISION": "\U0001f916", "LLM_JUDGMENT": "\U0001f916", "RULING": "\u2696\ufe0f",
    "ZONE_FORGE": "\U0001f3d7\ufe0f", "NPC_FORGE": "\U0001f464", "CAN_FORGE": "\u26a0\ufe0f",
    "FAC_FORGE": "\U0001f3db\ufe0f", "PE_FORGE": "\u2699\ufe0f",
    "FACT": "\U0001f4cc", "NARRATIVE_BEAT": "\U0001f4d6",
    "SESSION": "\U0001f4cb", "SAVE": "\U0001f4be",
    "PARTY": "\U0001f46a", "LOOT": "\U0001f4b0", "REST": "\U0001f3d5\ufe0f",
    "ABILITY_CHECK": "\U0001f3af",
    "NPC_UPDATE": "\U0001f464", "FAC_UPDATE": "\U0001f3db\ufe0f", "REL_UPDATE": "\U0001f495",
}


class MacrosGUI:
    def __init__(self):
        self.state = self._auto_load_state()
        self.pending_llm_requests = []
        self.day_logs = []
        self._last_save_mtime = 0
        self.root = tk.Tk()
        self.root.title("MACROS Engine v2.0 \u2014 Gammaria Campaign")
        self.root.configure(bg=COLORS["bg_dark"])
        self.root.geometry("1400x900")
        self.root.minsize(1100, 750)
        self.style = ttk.Style()
        self.style.theme_use("clam")
        self._configure_styles()
        self._build_ui()
        self._refresh_all()
        if hasattr(self, '_loaded_from'):
            self._log(f"\U0001f4c2 Loaded save: {self._loaded_from}", "engine")
        else:
            self._log(f"\U0001f4c2 Loaded default: Session 7 (23rd Ilrym)", "dim")
        self._replay_adjudication_log()
        self._last_save_mtime = self._get_newest_save_mtime()
        self._start_file_watcher()

    # ── State loading / file watching (unchanged) ──

    def _auto_load_state(self):
        dd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        if os.path.isdir(dd):
            saves = [f for f in os.listdir(dd) if f.startswith("save_") and f.endswith(".json")]
            if saves:
                saves.sort(key=lambda f: os.path.getmtime(os.path.join(dd, f)), reverse=True)
                try:
                    with open(os.path.join(dd, saves[0]), "r") as f:
                        state = state_from_json(f.read())
                    self._loaded_from = saves[0]
                    return state
                except Exception:
                    pass
        return load_gammaria_state()

    def _get_data_dir(self):
        return os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

    def _get_newest_save_mtime(self):
        dd = self._get_data_dir()
        if not os.path.isdir(dd): return 0
        saves = [f for f in os.listdir(dd) if f.endswith(".json") and (f.startswith("save_") or f.startswith("Session"))]
        if not saves: return 0
        saves.sort(key=lambda f: os.path.getmtime(os.path.join(dd, f)), reverse=True)
        return os.path.getmtime(os.path.join(dd, saves[0]))

    def _get_newest_save_path(self):
        dd = self._get_data_dir()
        if not os.path.isdir(dd): return None
        saves = [f for f in os.listdir(dd) if f.endswith(".json") and (f.startswith("save_") or f.startswith("Session"))]
        if not saves: return None
        saves.sort(key=lambda f: os.path.getmtime(os.path.join(dd, f)), reverse=True)
        return os.path.join(dd, saves[0])

    def _start_file_watcher(self):
        self._check_for_changes()

    def _check_for_changes(self):
        try:
            current_mtime = self._get_newest_save_mtime()
            if current_mtime > self._last_save_mtime:
                self._last_save_mtime = current_mtime
                path = self._get_newest_save_path()
                if path: self._auto_reload(path)
        except Exception: pass
        self.root.after(2000, self._check_for_changes)

    def _auto_reload(self, filepath):
        try:
            with open(filepath, "r", encoding="utf-8") as f:
                new_state = state_from_json(f.read())
            old_date = self.state.in_game_date
            old_log_count = len(self.state.adjudication_log) if hasattr(self.state, 'adjudication_log') else 0
            self.state = new_state
            self._refresh_all()
            fname = os.path.basename(filepath)
            new_log_count = len(self.state.adjudication_log) if hasattr(self.state, 'adjudication_log') else 0
            if new_log_count > old_log_count or self.state.in_game_date != old_date:
                self._log(f"\U0001f504 MCP sync: {fname} ({self.state.in_game_date})", "engine")
                self._replay_adjudication_log(skip=old_log_count)
        except Exception as e:
            self._log(f"\u274c Auto-reload failed: {e}", "trigger")

    def _replay_adjudication_log(self, skip=0):
        if not hasattr(self.state, 'adjudication_log'): return
        log = self.state.adjudication_log
        if not log: return
        entries = log[skip:]
        if not entries: return
        for entry in entries:
            etype = entry.get("type", "?")
            if etype == "T&P":
                day_log = {
                    "day_number": entry.get("day", "?"),
                    "date": entry.get("day", entry.get("date", "?")),
                    "steps": entry.get("steps", []),
                    "llm_requests": [None] * entry.get("llm_requests", 0),
                }
                self._log_day(day_log)
            else:
                tag = EVENT_TAG_MAP.get(etype, "dim")
                icon = EVENT_ICON_MAP.get(etype, "\u25aa")
                detail = entry.get("detail", "")
                if etype == "CLOCK_ADVANCE" and "clock" in entry:
                    self._log(f"  {icon} {entry['clock']}: {entry.get('old','?')}\u2192{entry.get('new','?')}", tag)
                    if entry.get("trigger_fired"):
                        self._log(f"     \U0001f525 TRG: {entry.get('trigger_text','')}", "trigger")
                elif etype == "DICE" and "expression" in entry:
                    self._log(f"  {icon} {entry['expression']} = {entry.get('dice',[])} = {entry.get('total','?')}", tag)
                elif etype == "ZONE_CHANGE" and "old_zone" in entry:
                    self._log(f"  {icon} Zone: {entry['old_zone']} \u2192 {entry['new_zone']}", tag)
                elif detail:
                    self._log(f"  {icon} [{etype}] {detail}", tag)
                else:
                    self._log(f"  {icon} [{etype}]", tag)

    # ── Styles ──

    def _configure_styles(self):
        S = self.style
        S.configure("Dark.TFrame", background=COLORS["bg_dark"])
        S.configure("Dark.TLabel", background=COLORS["bg_dark"], foreground=COLORS["text"], font=("Consolas", 10))
        S.configure("Title.TLabel", background=COLORS["bg_dark"], foreground=COLORS["gold"], font=("Consolas", 14, "bold"))
        S.configure("Header.TLabel", background=COLORS["bg_dark"], foreground=COLORS["accent"], font=("Consolas", 11, "bold"))
        S.configure("Dim.TLabel", background=COLORS["bg_dark"], foreground=COLORS["text_dim"], font=("Consolas", 9))
        S.configure("Action.TButton", background=COLORS["button_bg"], foreground=COLORS["text_bright"], font=("Consolas", 10, "bold"), padding=(12, 6))
        S.map("Action.TButton", background=[("active", COLORS["button_active"]), ("pressed", COLORS["accent"])])
        S.configure("Claude.TButton", background="#4a1942", foreground=COLORS["accent2"], font=("Consolas", 10, "bold"), padding=(12, 6))
        S.map("Claude.TButton", background=[("active", "#6b2462"), ("pressed", COLORS["accent"])])
        S.configure("Small.TButton", background=COLORS["button_bg"], foreground=COLORS["text"], font=("Consolas", 9), padding=(8, 4))
        S.map("Small.TButton", background=[("active", COLORS["button_active"])])
        # Notebook styling
        S.configure("Dark.TNotebook", background=COLORS["bg_dark"], borderwidth=0)
        S.configure("Dark.TNotebook.Tab", background=COLORS["bg_medium"], foreground=COLORS["text_dim"],
                     font=("Consolas", 9, "bold"), padding=(10, 4))
        S.map("Dark.TNotebook.Tab",
               background=[("selected", COLORS["bg_light"]), ("active", COLORS["bg_light"])],
               foreground=[("selected", COLORS["gold"]), ("active", COLORS["text_bright"])])

    # ── Main UI build ──

    def _build_ui(self):
        main = ttk.Frame(self.root, style="Dark.TFrame")
        main.pack(fill=tk.BOTH, expand=True, padx=8, pady=8)

        # Top bar
        top = ttk.Frame(main, style="Dark.TFrame"); top.pack(fill=tk.X, pady=(0, 8))
        ttk.Label(top, text="\u2694  MACROS ENGINE  \u2694", style="Title.TLabel").pack(side=tk.LEFT)
        self.meta_label = ttk.Label(top, text="", style="Dark.TLabel"); self.meta_label.pack(side=tk.RIGHT)

        # Middle: left tabs + right action log
        middle = ttk.Frame(main, style="Dark.TFrame"); middle.pack(fill=tk.BOTH, expand=True)

        # LEFT: Tabbed notebook
        left = ttk.Frame(middle, style="Dark.TFrame"); left.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=(0, 4))
        self.notebook = ttk.Notebook(left, style="Dark.TNotebook")
        self.notebook.pack(fill=tk.BOTH, expand=True)

        # Tab 1: Clocks & Engines
        self._build_clocks_tab()
        # Tab 2: NPCs
        self._build_npcs_tab()
        # Tab 3: Factions
        self._build_factions_tab()
        # Tab 4: World
        self._build_world_tab()

        # RIGHT: Action Log
        right = ttk.Frame(middle, style="Dark.TFrame", width=480); right.pack(side=tk.RIGHT, fill=tk.BOTH, padx=(4, 0)); right.pack_propagate(False)
        ttk.Label(right, text="ACTION LOG", style="Header.TLabel").pack(anchor=tk.W)
        self.log_text = scrolledtext.ScrolledText(right, wrap=tk.WORD, font=("Consolas", 9), bg=COLORS["bg_medium"], fg=COLORS["text"], insertbackground=COLORS["text"], selectbackground=COLORS["bg_light"], relief=tk.FLAT, bd=0, padx=8, pady=8)
        self.log_text.pack(fill=tk.BOTH, expand=True, pady=(4, 0))
        for tag, cfg in [
            ("header", {"foreground": COLORS["gold"], "font": ("Consolas", 10, "bold")}),
            ("engine", {"foreground": COLORS["blue"]}),
            ("clock_advance", {"foreground": COLORS["green"]}),
            ("trigger", {"foreground": COLORS["red"], "font": ("Consolas", 9, "bold")}),
            ("encounter", {"foreground": COLORS["orange"]}),
            ("npag", {"foreground": COLORS["purple"]}),
            ("dice", {"foreground": COLORS["yellow"]}),
            ("dim", {"foreground": COLORS["text_dim"]}),
            ("llm", {"foreground": COLORS["accent2"], "font": ("Consolas", 9, "italic")}),
            ("claude", {"foreground": "#cc88ff", "font": ("Consolas", 9, "bold")}),
            ("forge", {"foreground": COLORS["cyan"]}),
        ]:
            self.log_text.tag_configure(tag, **cfg)

        # Bottom bar
        bottom = ttk.Frame(main, style="Dark.TFrame"); bottom.pack(fill=tk.X, pady=(8, 0))
        ttk.Button(bottom, text="\u25b6  Run 1 Day", style="Action.TButton", command=lambda: self._run_days(1)).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Button(bottom, text="\u25b6\u25b6  Run 3 Days", style="Action.TButton", command=lambda: self._run_days(3)).pack(side=tk.LEFT, padx=(0, 4))
        ttk.Label(bottom, text="Days:", style="Dark.TLabel").pack(side=tk.LEFT, padx=(12, 2))
        self.days_var = tk.StringVar(value="1")
        tk.Entry(bottom, textvariable=self.days_var, width=4, bg=COLORS["bg_entry"], fg=COLORS["text"], insertbackground=COLORS["text"], font=("Consolas", 10), relief=tk.FLAT, bd=2).pack(side=tk.LEFT, padx=(0, 2))
        ttk.Button(bottom, text="Run", style="Small.TButton", command=self._run_n_days).pack(side=tk.LEFT, padx=(0, 8))
        ttk.Button(bottom, text="\U0001f916 Ask Claude", style="Claude.TButton", command=self._ask_claude).pack(side=tk.LEFT, padx=(8, 4))
        ttk.Button(bottom, text="\U0001f4e5 Import Response", style="Claude.TButton", command=self._import_response).pack(side=tk.LEFT, padx=(0, 4))
        self.pending_label = ttk.Label(bottom, text="", style="Dim.TLabel"); self.pending_label.pack(side=tk.LEFT, padx=(8, 0))
        ttk.Button(bottom, text="Save", style="Small.TButton", command=self._save_state).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(bottom, text="Load", style="Small.TButton", command=self._load_state).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(bottom, text="Reset", style="Small.TButton", command=self._reset_state).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(bottom, text="MCP Setup", style="Small.TButton", command=self._show_mcp_setup).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(bottom, text="2d6", style="Small.TButton", command=self._roll_2d6).pack(side=tk.RIGHT, padx=(4, 0))
        ttk.Button(bottom, text="d6", style="Small.TButton", command=self._roll_d6).pack(side=tk.RIGHT, padx=(4, 0))

    # ── Tab 1: Clocks & Engines ──

    def _build_clocks_tab(self):
        tab = tk.Frame(self.notebook, bg=COLORS["bg_dark"])
        self.notebook.add(tab, text=" \u23f0 Clocks ")

        ch = tk.Frame(tab, bg=COLORS["bg_dark"]); ch.pack(fill=tk.X, padx=4, pady=(4, 0))
        tk.Label(ch, text="CLOCKS & PRESSURE", bg=COLORS["bg_dark"], fg=COLORS["accent"], font=("Consolas", 11, "bold")).pack(side=tk.LEFT)
        self.clock_count_label = tk.Label(ch, text="", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 9))
        self.clock_count_label.pack(side=tk.RIGHT)

        cf = tk.Frame(tab, bg=COLORS["bg_dark"]); cf.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 4))
        self.clock_canvas = tk.Canvas(cf, bg=COLORS["bg_dark"], highlightthickness=0, bd=0)
        csb = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self.clock_canvas.yview)
        self.clock_inner = tk.Frame(self.clock_canvas, bg=COLORS["bg_dark"])
        self.clock_inner.bind("<Configure>", lambda e: self.clock_canvas.configure(scrollregion=self.clock_canvas.bbox("all")))
        self.clock_canvas.create_window((0, 0), window=self.clock_inner, anchor="nw")
        self.clock_canvas.configure(yscrollcommand=csb.set)
        self.clock_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); csb.pack(side=tk.RIGHT, fill=tk.Y)
        def _mw(e): self.clock_canvas.yview_scroll(-1 * (e.delta // 120), "units")
        self.clock_canvas.bind("<MouseWheel>", _mw); self.clock_inner.bind("<MouseWheel>", _mw)
        self._mw = _mw

        # Engines section at bottom of clocks tab
        ef = tk.Frame(tab, bg=COLORS["bg_dark"]); ef.pack(fill=tk.X, padx=4, pady=(0, 4))
        tk.Label(ef, text="ENGINES", bg=COLORS["bg_dark"], fg=COLORS["accent"], font=("Consolas", 11, "bold")).pack(anchor=tk.W)
        self.engine_frame = tk.Frame(ef, bg=COLORS["bg_dark"]); self.engine_frame.pack(fill=tk.X, pady=(4, 0))

    # ── Tab 2: NPCs ──

    def _build_npcs_tab(self):
        tab = tk.Frame(self.notebook, bg=COLORS["bg_dark"])
        self.notebook.add(tab, text=" \U0001f464 NPCs ")

        hdr = tk.Frame(tab, bg=COLORS["bg_dark"]); hdr.pack(fill=tk.X, padx=4, pady=(4, 0))
        tk.Label(hdr, text="NPCs & COMPANIONS", bg=COLORS["bg_dark"], fg=COLORS["accent"], font=("Consolas", 11, "bold")).pack(side=tk.LEFT)
        self.npc_count_label = tk.Label(hdr, text="", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 9))
        self.npc_count_label.pack(side=tk.RIGHT)

        cf = tk.Frame(tab, bg=COLORS["bg_dark"]); cf.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 4))
        self.npc_canvas = tk.Canvas(cf, bg=COLORS["bg_dark"], highlightthickness=0, bd=0)
        nsb = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self.npc_canvas.yview)
        self.npc_inner = tk.Frame(self.npc_canvas, bg=COLORS["bg_dark"])
        self.npc_inner.bind("<Configure>", lambda e: self.npc_canvas.configure(scrollregion=self.npc_canvas.bbox("all")))
        self.npc_canvas.create_window((0, 0), window=self.npc_inner, anchor="nw")
        self.npc_canvas.configure(yscrollcommand=nsb.set)
        self.npc_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); nsb.pack(side=tk.RIGHT, fill=tk.Y)
        def _npc_mw(e): self.npc_canvas.yview_scroll(-1 * (e.delta // 120), "units")
        self.npc_canvas.bind("<MouseWheel>", _npc_mw); self.npc_inner.bind("<MouseWheel>", _npc_mw)
        self._npc_mw = _npc_mw

    # ── Tab 3: Factions ──

    def _build_factions_tab(self):
        tab = tk.Frame(self.notebook, bg=COLORS["bg_dark"])
        self.notebook.add(tab, text=" \U0001f3db\ufe0f Factions ")

        hdr = tk.Frame(tab, bg=COLORS["bg_dark"]); hdr.pack(fill=tk.X, padx=4, pady=(4, 0))
        tk.Label(hdr, text="FACTIONS", bg=COLORS["bg_dark"], fg=COLORS["accent"], font=("Consolas", 11, "bold")).pack(side=tk.LEFT)
        self.fac_count_label = tk.Label(hdr, text="", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 9))
        self.fac_count_label.pack(side=tk.RIGHT)

        cf = tk.Frame(tab, bg=COLORS["bg_dark"]); cf.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 4))
        self.fac_canvas = tk.Canvas(cf, bg=COLORS["bg_dark"], highlightthickness=0, bd=0)
        fsb = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self.fac_canvas.yview)
        self.fac_inner = tk.Frame(self.fac_canvas, bg=COLORS["bg_dark"])
        self.fac_inner.bind("<Configure>", lambda e: self.fac_canvas.configure(scrollregion=self.fac_canvas.bbox("all")))
        self.fac_canvas.create_window((0, 0), window=self.fac_inner, anchor="nw")
        self.fac_canvas.configure(yscrollcommand=fsb.set)
        self.fac_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); fsb.pack(side=tk.RIGHT, fill=tk.Y)
        def _fac_mw(e): self.fac_canvas.yview_scroll(-1 * (e.delta // 120), "units")
        self.fac_canvas.bind("<MouseWheel>", _fac_mw); self.fac_inner.bind("<MouseWheel>", _fac_mw)
        self._fac_mw = _fac_mw

    # ── Tab 4: World ──

    def _build_world_tab(self):
        tab = tk.Frame(self.notebook, bg=COLORS["bg_dark"])
        self.notebook.add(tab, text=" \U0001f30d World ")

        cf = tk.Frame(tab, bg=COLORS["bg_dark"]); cf.pack(fill=tk.BOTH, expand=True, padx=4, pady=(4, 4))
        self.world_canvas = tk.Canvas(cf, bg=COLORS["bg_dark"], highlightthickness=0, bd=0)
        wsb = ttk.Scrollbar(cf, orient=tk.VERTICAL, command=self.world_canvas.yview)
        self.world_inner = tk.Frame(self.world_canvas, bg=COLORS["bg_dark"])
        self.world_inner.bind("<Configure>", lambda e: self.world_canvas.configure(scrollregion=self.world_canvas.bbox("all")))
        self.world_canvas.create_window((0, 0), window=self.world_inner, anchor="nw")
        self.world_canvas.configure(yscrollcommand=wsb.set)
        self.world_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True); wsb.pack(side=tk.RIGHT, fill=tk.Y)
        def _world_mw(e): self.world_canvas.yview_scroll(-1 * (e.delta // 120), "units")
        self.world_canvas.bind("<MouseWheel>", _world_mw); self.world_inner.bind("<MouseWheel>", _world_mw)
        self._world_mw = _world_mw

    # ── Drawing: Clocks ──

    def _draw_clocks(self):
        for w in self.clock_inner.winfo_children(): w.destroy()
        active, fired, halted = [], [], []
        for c in self.state.clocks.values():
            if c.trigger_fired: fired.append(c)
            elif c.status == "halted": halted.append(c)
            elif c.status != "retired": active.append(c)
        active.sort(key=lambda c: c.progress / max(c.max_progress, 1), reverse=True)
        for c in active: self._clock_row(c)
        if fired:
            tk.Frame(self.clock_inner, bg=COLORS["border"], height=1).pack(fill=tk.X, pady=4)
            tk.Label(self.clock_inner, text="TRIGGERS FIRED", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 8)).pack(anchor=tk.W)
            for c in fired: self._clock_row(c, "fired")
        if halted:
            tk.Frame(self.clock_inner, bg=COLORS["border"], height=1).pack(fill=tk.X, pady=4)
            tk.Label(self.clock_inner, text="HALTED", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 8)).pack(anchor=tk.W)
            for c in halted: self._clock_row(c, "halted")
        self.clock_count_label.configure(text=f"{len(active)} active / {len(fired)} fired / {len(halted)} halted")

    def _clock_row(self, clock, mode="active"):
        row = tk.Frame(self.clock_inner, bg=COLORS["bg_dark"]); row.pack(fill=tk.X, pady=1); row.bind("<MouseWheel>", self._mw)
        nm = clock.name + (" \u23f0" if clock.is_cadence else "")
        pct = clock.progress / max(clock.max_progress, 1)
        if mode == "fired": clr = COLORS["text_dim"]
        elif mode == "halted": clr = COLORS["yellow"]
        elif pct >= 0.75: clr = COLORS["red"]
        elif pct >= 0.5: clr = COLORS["yellow"]
        else: clr = COLORS["green"]
        lbl = tk.Label(row, text=nm, bg=COLORS["bg_dark"], fg=clr, font=("Consolas", 9), anchor=tk.W, width=45); lbl.pack(side=tk.LEFT); lbl.bind("<MouseWheel>", self._mw)
        bw, bh = 200, 14
        bar = tk.Canvas(row, width=bw, height=bh, bg=COLORS["clock_bg"], highlightthickness=0, bd=0); bar.pack(side=tk.LEFT, padx=4); bar.bind("<MouseWheel>", self._mw)
        if clock.max_progress > 0:
            fw = int(pct * bw)
            fc = COLORS["clock_fill_fired"] if mode == "fired" else COLORS["clock_fill_red"] if pct >= 0.75 else COLORS["clock_fill_yellow"] if pct >= 0.5 else COLORS["clock_fill_green"]
            if fw > 0: bar.create_rectangle(0, 0, fw, bh, fill=fc, outline="")
            for i in range(1, clock.max_progress):
                x = int((i / clock.max_progress) * bw); bar.create_line(x, 0, x, bh, fill=COLORS["border"])
        pt = "FIRED" if mode == "fired" else f"{clock.progress}/{clock.max_progress} HALT" if mode == "halted" else f"{clock.progress}/{clock.max_progress}"
        pl = tk.Label(row, text=pt, bg=COLORS["bg_dark"], fg=clr, font=("Consolas", 9, "bold"), width=12); pl.pack(side=tk.LEFT); pl.bind("<MouseWheel>", self._mw)

    def _draw_engines(self):
        for w in self.engine_frame.winfo_children(): w.destroy()
        for e in self.state.engines.values():
            row = tk.Frame(self.engine_frame, bg=COLORS["bg_dark"]); row.pack(fill=tk.X, pady=1)
            ic = "\u2699\ufe0f" if e.status == "active" else "\U0001f4a4" if e.status == "dormant" else "\u2b1b"
            cl = COLORS["green"] if e.status == "active" else COLORS["text_dim"]
            tk.Label(row, text=f"{ic}  {e.name}", bg=COLORS["bg_dark"], fg=cl, font=("Consolas", 9), anchor=tk.W).pack(side=tk.LEFT)
            tk.Label(row, text=f"[{e.version}] {e.status.upper()}", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 8)).pack(side=tk.RIGHT)

    # ── Drawing: NPCs ──

    def _draw_npcs(self):
        for w in self.npc_inner.winfo_children(): w.destroy()
        if not hasattr(self.state, 'npcs') or not self.state.npcs:
            tk.Label(self.npc_inner, text="No NPCs in save file.", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 9)).pack(anchor=tk.W, padx=4)
            self.npc_count_label.configure(text="0")
            return

        npcs = list(self.state.npcs.values())
        companions = [n for n in npcs if n.is_companion]
        others = [n for n in npcs if not n.is_companion]
        companions.sort(key=lambda n: n.name)
        others.sort(key=lambda n: (n.zone, n.name))

        if companions:
            tk.Label(self.npc_inner, text="\u2605 COMPANIONS", bg=COLORS["bg_dark"], fg=COLORS["gold"], font=("Consolas", 10, "bold")).pack(anchor=tk.W, padx=4, pady=(4, 2))
            for n in companions: self._npc_row(n)

        if others:
            tk.Frame(self.npc_inner, bg=COLORS["border"], height=1).pack(fill=tk.X, pady=4)
            tk.Label(self.npc_inner, text="OTHER NPCs", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 9)).pack(anchor=tk.W, padx=4, pady=(0, 2))
            for n in others: self._npc_row(n)

        self.npc_count_label.configure(text=f"{len(companions)} companions / {len(others)} others")

    def _npc_row(self, npc):
        row = tk.Frame(self.npc_inner, bg=COLORS["bg_dark"]); row.pack(fill=tk.X, pady=1, padx=4)
        row.bind("<MouseWheel>", self._npc_mw)

        # Status color
        if npc.status == "dead": clr = COLORS["red"]
        elif npc.with_pc: clr = COLORS["gold"]
        elif npc.is_companion: clr = COLORS["cyan"]
        else: clr = COLORS["text"]

        # Badges
        badges = ""
        if npc.is_companion: badges += "\u2605 "
        if npc.with_pc: badges += "[WITH PC] "

        name_text = f"{badges}{npc.name}"
        nl = tk.Label(row, text=name_text, bg=COLORS["bg_dark"], fg=clr, font=("Consolas", 9, "bold"), anchor=tk.W, width=32)
        nl.pack(side=tk.LEFT); nl.bind("<MouseWheel>", self._npc_mw)

        zone_text = npc.zone or "—"
        zl = tk.Label(row, text=zone_text, bg=COLORS["bg_dark"], fg=COLORS["blue"], font=("Consolas", 9), anchor=tk.W, width=18)
        zl.pack(side=tk.LEFT); zl.bind("<MouseWheel>", self._npc_mw)

        role_text = npc.role or "—"
        rl = tk.Label(row, text=role_text, bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 8), anchor=tk.W)
        rl.pack(side=tk.LEFT, fill=tk.X, expand=True); rl.bind("<MouseWheel>", self._npc_mw)

    # ── Drawing: Factions ──

    def _draw_factions(self):
        for w in self.fac_inner.winfo_children(): w.destroy()
        if not hasattr(self.state, 'factions') or not self.state.factions:
            tk.Label(self.fac_inner, text="No factions in save file.", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 9)).pack(anchor=tk.W, padx=4)
            self.fac_count_label.configure(text="0")
            return

        facs = sorted(self.state.factions.values(), key=lambda f: f.name)

        disp_colors = {
            "friendly": COLORS["green"],
            "neutral": COLORS["yellow"],
            "hostile": COLORS["red"],
            "unknown": COLORS["text_dim"],
        }

        for fac in facs:
            row = tk.Frame(self.fac_inner, bg=COLORS["bg_dark"]); row.pack(fill=tk.X, pady=1, padx=4)
            row.bind("<MouseWheel>", self._fac_mw)

            clr = disp_colors.get(fac.disposition, COLORS["text"])
            fl = tk.Label(row, text=fac.name, bg=COLORS["bg_dark"], fg=clr, font=("Consolas", 9, "bold"), anchor=tk.W, width=32)
            fl.pack(side=tk.LEFT); fl.bind("<MouseWheel>", self._fac_mw)

            disp_text = fac.disposition.upper() if fac.disposition else "—"
            dl = tk.Label(row, text=disp_text, bg=COLORS["bg_dark"], fg=clr, font=("Consolas", 9), width=10)
            dl.pack(side=tk.LEFT); dl.bind("<MouseWheel>", self._fac_mw)

            status_text = fac.status or "—"
            sl = tk.Label(row, text=status_text, bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 8), width=10)
            sl.pack(side=tk.LEFT); sl.bind("<MouseWheel>", self._fac_mw)

            if fac.notes:
                note_text = fac.notes[:60] + ("..." if len(fac.notes) > 60 else "")
                nl = tk.Label(row, text=note_text, bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 8), anchor=tk.W)
                nl.pack(side=tk.LEFT, fill=tk.X, expand=True); nl.bind("<MouseWheel>", self._fac_mw)

        self.fac_count_label.configure(text=f"{len(facs)} factions")

    # ── Drawing: World ──

    def _draw_world(self):
        for w in self.world_inner.winfo_children(): w.destroy()
        s = self.state

        # PC State
        if hasattr(s, 'pc_state') and s.pc_state:
            pc = s.pc_state
            tk.Label(self.world_inner, text="\u2694 PC STATE", bg=COLORS["bg_dark"], fg=COLORS["gold"], font=("Consolas", 10, "bold")).pack(anchor=tk.W, padx=4, pady=(4, 2))
            tk.Label(self.world_inner, text=f"  {pc.name} | {pc.reputation or '—'}", bg=COLORS["bg_dark"], fg=COLORS["text"], font=("Consolas", 9)).pack(anchor=tk.W, padx=4)
            if pc.equipment_notes:
                tk.Label(self.world_inner, text=f"  Gear: {pc.equipment_notes}", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 8)).pack(anchor=tk.W, padx=4)
            if pc.conditions:
                tk.Label(self.world_inner, text=f"  Conditions: {', '.join(pc.conditions)}", bg=COLORS["bg_dark"], fg=COLORS["red"], font=("Consolas", 8)).pack(anchor=tk.W, padx=4)
            if pc.goals:
                tk.Label(self.world_inner, text=f"  Goals ({len(pc.goals)}):", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 8)).pack(anchor=tk.W, padx=4)
                for g in pc.goals[:6]:
                    tk.Label(self.world_inner, text=f"    \u2022 {g}", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 8)).pack(anchor=tk.W, padx=4)
                if len(pc.goals) > 6:
                    tk.Label(self.world_inner, text=f"    ... +{len(pc.goals)-6} more", bg=COLORS["bg_dark"], fg=COLORS["text_dim"], font=("Consolas", 8)).pack(anchor=tk.W, padx=4)

        # Relationships
        if hasattr(s, 'relationships') and s.relationships:
            tk.Frame(self.world_inner, bg=COLORS["border"], height=1).pack(fill=tk.X, pady=4)
            tk.Label(self.world_inner, text=f"\U0001f495 RELATIONSHIPS ({len(s.relationships)})", bg=COLORS["bg_dark"], fg=COLORS["accent"], font=("Consolas", 10, "bold")).pack(anchor=tk.W, padx=4, pady=(0, 2))
            for rel in sorted(s.relationships.values(), key=lambda r: r.id):
                vis_icon = "\U0001f512" if rel.visibility == "secret" else "\U0001f50d" if rel.visibility == "restricted" else ""
                clr = COLORS["red"] if rel.rel_type in ("dislike", "hatred") else COLORS["green"] if rel.rel_type in ("love", "friends") else COLORS["yellow"]
                tk.Label(self.world_inner, text=f"  {vis_icon} {rel.npc_a} \u2194 {rel.npc_b}: {rel.rel_type} ({rel.current_state})", bg=COLORS["bg_dark"], fg=clr, font=("Consolas", 9)).pack(anchor=tk.W, padx=4)

        # Discoveries
        if hasattr(s, 'discoveries') and s.discoveries:
            tk.Frame(self.world_inner, bg=COLORS["border"], height=1).pack(fill=tk.X, pady=4)
            tk.Label(self.world_inner, text=f"\U0001f50d DISCOVERIES ({len(s.discoveries)})", bg=COLORS["bg_dark"], fg=COLORS["accent"], font=("Consolas", 10, "bold")).pack(anchor=tk.W, padx=4, pady=(0, 2))
            for disc in s.discoveries:
                cert_clr = COLORS["green"] if disc.certainty == "confirmed" else COLORS["yellow"] if disc.certainty == "inferred" else COLORS["text_dim"]
                info_short = disc.info[:70] + ("..." if len(disc.info) > 70 else "")
                tk.Label(self.world_inner, text=f"  [{disc.certainty.upper()[:4]}] {info_short}", bg=COLORS["bg_dark"], fg=cert_clr, font=("Consolas", 8)).pack(anchor=tk.W, padx=4)

        # Unresolved Threads
        if hasattr(s, 'unresolved_threads') and s.unresolved_threads:
            open_threads = [t for t in s.unresolved_threads if not t.resolved]
            if open_threads:
                tk.Frame(self.world_inner, bg=COLORS["border"], height=1).pack(fill=tk.X, pady=4)
                tk.Label(self.world_inner, text=f"\U0001f9f5 OPEN THREADS ({len(open_threads)})", bg=COLORS["bg_dark"], fg=COLORS["accent"], font=("Consolas", 10, "bold")).pack(anchor=tk.W, padx=4, pady=(0, 2))
                for t in open_threads:
                    zone_tag = f" [{t.zone}]" if t.zone else ""
                    tk.Label(self.world_inner, text=f"  \u2022 {t.description}{zone_tag}", bg=COLORS["bg_dark"], fg=COLORS["purple"], font=("Consolas", 8)).pack(anchor=tk.W, padx=4)

        # Losses
        if hasattr(s, 'losses_irreversibles') and s.losses_irreversibles:
            tk.Frame(self.world_inner, bg=COLORS["border"], height=1).pack(fill=tk.X, pady=4)
            tk.Label(self.world_inner, text=f"\U0001f480 LOSSES ({len(s.losses_irreversibles)})", bg=COLORS["bg_dark"], fg=COLORS["red"], font=("Consolas", 10, "bold")).pack(anchor=tk.W, padx=4, pady=(0, 2))
            for loss in s.losses_irreversibles:
                tk.Label(self.world_inner, text=f"  \u2022 {loss.get('description', '?')} (S{loss.get('session','?')})", bg=COLORS["bg_dark"], fg=COLORS["red"], font=("Consolas", 8)).pack(anchor=tk.W, padx=4)

    # ── Meta / Pending ──

    def _update_meta(self):
        s = self.state
        self.meta_label.configure(text=f"Session {s.session_id}  \u00b7  {s.in_game_date}  \u00b7  {s.pc_zone}  \u00b7  {s.season}  \u00b7  {s.campaign_intensity}")

    def _update_pending(self):
        n = len(self.pending_llm_requests)
        self.pending_label.configure(text=f"\u26a1 {n} pending for Claude" if n else "", foreground=COLORS["accent2"] if n else COLORS["text_dim"])

    # ── Logging ──

    def _log(self, text, tag=None):
        self.log_text.configure(state=tk.NORMAL)
        self.log_text.insert(tk.END, text + "\n", tag if tag else ())
        self.log_text.see(tk.END); self.log_text.configure(state=tk.DISABLED)

    def _log_day(self, dl):
        self._log(f"\u2550" * 35, "header")
        self._log(f"  DAY {dl.get('day_number','?')} \u2014 {dl.get('date','?')}", "header")
        self._log(f"\u2550" * 35, "header")
        for step in dl.get("steps", []):
            sn, r = step["step"], step.get("result", step.get("results", {}))
            if sn == "date_advance":
                if r.get("season_changed"): self._log(f"  \U0001f4c5 {r['new_date']} \u2014 SEASON: {r['new_season']}", "engine")
                else: self._log(f"  \U0001f4c5 {r['new_date']}", "dim")
            elif sn.startswith("engine:"):
                en = sn.split(":", 1)[1]
                if r.get("skipped"): self._log(f"  \u2699\ufe0f  {en}: SKIP", "dim")
                elif r.get("status") == "inert": self._log(f"  \u2699\ufe0f  {en}: INERT", "dim")
                elif "roll" in r:
                    self._log(f"  \u2699\ufe0f  {en}: 2d6={r['roll']['total']} \u2192 {r.get('outcome_band','')}", "engine")
                    for ce in r.get("clock_effects_applied", []):
                        if "error" in ce: self._log(f"     \u274c {ce.get('clock','?')}: {ce['error']}", "trigger")
                        elif not ce.get("skipped"): self._log(f"     \u2192 {ce['clock']}: {ce.get('old','?')}\u2192{ce.get('new','?')}", "clock_advance")
                else: self._log(f"  \u2699\ufe0f  {en}: {r.get('note', r.get('status','ran'))}", "engine")
            elif sn == "cadence_clocks":
                for cr in step.get("results", []):
                    if "error" not in cr:
                        self._log(f"  \u23f0 {cr['clock']}: {cr['old']}\u2192{cr['new']}/{cr['max']}", "clock_advance")
                        if cr.get("trigger_fired"): self._log(f"     \U0001f525 TRIGGER: {cr.get('trigger_text','')}", "trigger")
            elif sn == "clock_audit":
                for a in r.get("auto_advanced", []):
                    ar = a["advance_result"]
                    self._log(f"  \U0001f50d {a['clock']}: {ar['old']}\u2192{ar['new']}/{ar.get('max','?')}", "clock_advance")
                    if ar.get("trigger_fired"): self._log(f"     \U0001f525 TRIGGER: {ar.get('trigger_text','')}", "trigger")
                for rv in r.get("needs_llm_review", []): self._log(f"  \u2753 {rv['clock']}: needs Claude ({len(rv['ambiguous_bullets'])} bullets)", "llm")
                if not r.get("auto_advanced") and not r.get("needs_llm_review"): self._log(f"  \U0001f50d Audit: no advances", "dim")
            elif sn == "encounter_gate":
                rv = r["roll"]["total"]
                if r["passed"]: self._log(f"  \u2694\ufe0f  Encounter: PASS (d6={rv}) \u2192 {r.get('encounter',{}).get('description','no table')[:55]}", "encounter")
                else: self._log(f"  \u2694\ufe0f  Encounter: fail (d6={rv})", "dim")
            elif sn == "npag_gate":
                rv = r["roll"]["total"]
                if r["passed"]: self._log(f"  \U0001f465 NPAG: PASS (d6={rv}) \u2192 {r['npc_count']['count']} NPCs", "npag")
                else: self._log(f"  \U0001f465 NPAG: fail (d6={rv})", "dim")
        llm = dl.get("llm_requests", [])
        if llm: self._log(f"  \U0001f4cb {len(llm)} queued for Claude", "llm")
        self._log("")

    # ── Actions ──

    def _run_n_days(self):
        try:
            n = int(self.days_var.get())
            if 1 <= n <= 30: self._run_days(n)
            else: messagebox.showwarning("Invalid", "Enter 1-30")
        except ValueError: messagebox.showwarning("Invalid", "Enter a number")

    def _run_days(self, n):
        if not self.state.pc_zone: messagebox.showerror("Error", "PC Zone is blank"); return
        self._log(f"\u2554{'=' * 37}\u2557", "header")
        self._log(f"\u2551  TIME & PRESSURE \u2014 {n} DAY(S)         \u2551", "header")
        self._log(f"\u2551  From: {self.state.in_game_date:<28s} \u2551", "header")
        self._log(f"\u255a{'=' * 37}\u255d", "header")
        self.day_logs = []
        for i in range(n):
            dl = run_day(self.state); dl["day_number"] = i + 1
            self.day_logs.append(dl); self._log_day(dl)
            for req in dl.get("llm_requests", []): self.pending_llm_requests.append(req)
        self._log(f"T&P complete. Date: {self.state.in_game_date}", "header")
        if self.pending_llm_requests: self._log(f"\u26a1 {len(self.pending_llm_requests)} total pending for Claude", "llm")
        self._log(""); self._refresh_all()
        if self.pending_llm_requests: _write_pending_to_disk(self.pending_llm_requests, self.state, self.day_logs)

    def _ask_claude(self):
        if not self.pending_llm_requests:
            messagebox.showinfo("No Requests", "No pending items.\nRun T&P days first."); return
        prompt = build_clipboard_prompt(self.pending_llm_requests, self.state, self.day_logs)
        write_request(self.pending_llm_requests, self.state, self.day_logs)
        n = len(self.pending_llm_requests)
        types = {}
        for r in self.pending_llm_requests: types[r.get("type","?")] = types.get(r.get("type","?"),0)+1
        ts = ", ".join(f"{v} {k}" for k,v in types.items())
        self._log(f"\U0001f916 Built prompt with {n} requests ({ts})", "claude")
        self._log(f"\U0001f916 Prompt size: {len(prompt):,} chars", "claude")
        win = tk.Toplevel(self.root); win.title("Ask Claude \u2014 Copy & Paste"); win.configure(bg=COLORS["bg_dark"]); win.geometry("800x600")
        ttk.Label(win, text="COPY THIS PROMPT \u2192 PASTE INTO CLAUDE", style="Header.TLabel").pack(pady=(12,4))
        ttk.Label(win, text=f"{n} requests \u00b7 {len(prompt):,} chars \u00b7 all data embedded", style="Dim.TLabel").pack(pady=(0,8))
        txt = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Consolas",9), bg=COLORS["bg_medium"], fg=COLORS["text"], relief=tk.FLAT, padx=12, pady=12, height=20)
        txt.pack(fill=tk.BOTH, expand=True, padx=12); txt.insert(tk.END, prompt); txt.configure(state=tk.DISABLED)
        bf = tk.Frame(win, bg=COLORS["bg_dark"]); bf.pack(fill=tk.X, padx=12, pady=12)
        def copy_prompt():
            win.clipboard_clear(); win.clipboard_append(prompt)
            self._log("\U0001f4cb Prompt copied to clipboard!", "claude")
            copy_btn.configure(text="\u2705 Copied!"); win.after(2000, lambda: copy_btn.configure(text="\U0001f4cb Copy to Clipboard"))
        copy_btn = ttk.Button(bf, text="\U0001f4cb Copy to Clipboard", style="Action.TButton", command=copy_prompt); copy_btn.pack(side=tk.LEFT, padx=(0,8))
        ttk.Label(bf, text="Then paste into Claude \u2192 copy response \u2192 Import Response", style="Dim.TLabel").pack(side=tk.LEFT)
        ttk.Button(bf, text="Close", style="Small.TButton", command=win.destroy).pack(side=tk.RIGHT)

    def _import_response(self):
        if response_exists():
            if messagebox.askyesno("Response Found", "Found claude_response.json in data folder.\nImport from file?\n\n(No = paste text instead)"):
                self._do_import_file(); return
        self._show_paste_dialog()

    def _show_paste_dialog(self):
        win = tk.Toplevel(self.root); win.title("Import Claude Response"); win.configure(bg=COLORS["bg_dark"]); win.geometry("800x600")
        ttk.Label(win, text="PASTE CLAUDE'S RESPONSE BELOW", style="Header.TLabel").pack(pady=(12,4))
        ttk.Label(win, text="Copy Claude's JSON response and paste it here", style="Dim.TLabel").pack(pady=(0,8))
        txt = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Consolas",9), bg=COLORS["bg_entry"], fg=COLORS["text"], insertbackground=COLORS["text"], relief=tk.FLAT, padx=12, pady=12, height=20)
        txt.pack(fill=tk.BOTH, expand=True, padx=12)
        bf = tk.Frame(win, bg=COLORS["bg_dark"]); bf.pack(fill=tk.X, padx=12, pady=12)
        def do_import():
            raw = txt.get("1.0", tk.END).strip()
            if not raw: messagebox.showwarning("Empty", "Paste Claude's response first.", parent=win); return
            try:
                resp = parse_pasted_response(raw)
                if "responses" not in resp: messagebox.showerror("Invalid", "JSON doesn't contain 'responses' array.", parent=win); return
                entries = apply_response(self.state, resp); self._log_import(entries)
                self.pending_llm_requests = []; self.day_logs = []; _clear_pending_file(); self._refresh_all(); win.destroy()
            except json.JSONDecodeError as e:
                messagebox.showerror("Parse Error", f"Could not parse JSON:\n{str(e)[:200]}\n\nMake sure you copied the complete JSON response.", parent=win)
            except Exception as e: messagebox.showerror("Import Error", str(e), parent=win)
        def load_file():
            dd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
            fp = filedialog.askopenfilename(title="Load Response File", initialdir=dd, filetypes=[("JSON","*.json"),("All","*.*")], parent=win)
            if not fp: return
            try:
                with open(fp,"r",encoding="utf-8") as f: content = f.read()
                txt.delete("1.0", tk.END); txt.insert(tk.END, content)
            except Exception as e: messagebox.showerror("File Error", str(e), parent=win)
        ttk.Button(bf, text="\u2705 Import", style="Action.TButton", command=do_import).pack(side=tk.LEFT, padx=(0,8))
        ttk.Button(bf, text="\U0001f4c2 Load from File", style="Small.TButton", command=load_file).pack(side=tk.LEFT, padx=(0,8))
        ttk.Button(bf, text="Close", style="Small.TButton", command=win.destroy).pack(side=tk.RIGHT)

    def _do_import_file(self):
        try:
            resp = read_response()
            if not resp: messagebox.showinfo("No Response", "No response file found."); return
            entries = apply_response(self.state, resp); self._log_import(entries)
            self.pending_llm_requests = []; self.day_logs = []; _clear_pending_file(); self._refresh_all()
        except Exception as e: messagebox.showerror("Import Error", str(e))

    def _log_import(self, entries):
        self._log(f"\u2554{'=' * 37}\u2557", "claude")
        self._log(f"\u2551  CLAUDE RESPONSE IMPORTED           \u2551", "claude")
        self._log(f"\u255a{'=' * 37}\u255d", "claude")
        for e in entries:
            if "content_preview" in e: self._log(f"  \U0001f916 [{e['type']}] {e['content_preview']}", "claude")
            elif e.get("applied") == "clock_advance":
                r = e["result"]; self._log(f"     \u2192 {r['clock']}: {r['old']}\u2192{r['new']}", "clock_advance")
            elif e.get("applied") == "clock_reduce":
                r = e["result"]; self._log(f"     \u2192 {r['clock']}: reduced", "clock_advance")
            elif e.get("applied") == "fact": self._log(f"     \U0001f4cc {e['text'][:60]}", "dim")
            elif e.get("error"): self._log(f"     \u274c {e['error']}", "trigger")
        self._log(f"  \u2705 Applied. Queue cleared.", "claude"); self._log("")

    def _show_mcp_setup(self):
        instructions, cj = generate_mcp_config()
        win = tk.Toplevel(self.root); win.title("MCP Setup"); win.configure(bg=COLORS["bg_dark"]); win.geometry("750x600")
        txt = scrolledtext.ScrolledText(win, wrap=tk.WORD, font=("Consolas",9), bg=COLORS["bg_medium"], fg=COLORS["text"], relief=tk.FLAT, padx=12, pady=12)
        txt.pack(fill=tk.BOTH, expand=True, padx=12, pady=12); txt.insert(tk.END, instructions); txt.configure(state=tk.DISABLED)
        bf = tk.Frame(win, bg=COLORS["bg_dark"]); bf.pack(fill=tk.X, padx=12, pady=(0,12))
        def cp(): win.clipboard_clear(); win.clipboard_append(cj); self._log("\U0001f4cb MCP config copied", "engine")
        ttk.Button(bf, text="\U0001f4cb Copy Config", style="Action.TButton", command=cp).pack(side=tk.LEFT)
        ttk.Button(bf, text="Close", style="Small.TButton", command=win.destroy).pack(side=tk.RIGHT)

    def _save_state(self):
        dd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"); os.makedirs(dd, exist_ok=True)
        fn = os.path.join(dd, f"save_{self.state.in_game_date.replace(' ', '_')}.json")
        with open(fn, "w") as f: f.write(state_to_json(self.state))
        self._last_save_mtime = os.path.getmtime(fn)
        self._log(f"\U0001f4be Saved: {os.path.basename(fn)}", "engine")
        messagebox.showinfo("Saved", f"Saved to {os.path.basename(fn)}")

    def _load_state(self):
        dd = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")
        if not os.path.isdir(dd): dd = "."
        fp = filedialog.askopenfilename(title="Load Save", initialdir=dd, filetypes=[("JSON","*.json"),("All","*.*")])
        if not fp: return
        try:
            with open(fp, "r") as f: self.state = state_from_json(f.read())
            self.pending_llm_requests = []; self.day_logs = []; _clear_pending_file()
            self._last_save_mtime = os.path.getmtime(fp)
            self._refresh_all()
            self.log_text.configure(state=tk.NORMAL); self.log_text.delete("1.0", tk.END); self.log_text.configure(state=tk.DISABLED)
            self._log(f"\U0001f4c2 Loaded: {os.path.basename(fp)}", "engine")
            self._log(f"   {self.state.in_game_date} \u00b7 {self.state.pc_zone} \u00b7 Session {self.state.session_id}", "dim")
            self._replay_adjudication_log()
        except Exception as e: messagebox.showerror("Load Error", str(e))

    def _reset_state(self):
        if messagebox.askyesno("Reset", "Reset to Session 7?\nDiscards unsaved changes."):
            self.state = load_gammaria_state(); self.pending_llm_requests = []; self.day_logs = []; _clear_pending_file()
            self._refresh_all(); self._log("\U0001f504 Reset to Session 7", "header")

    def _roll_d6(self):
        r = roll_dice("1d6"); self._log(f"  \U0001f3b2 d6 = {r['total']}", "dice")
    def _roll_2d6(self):
        r = roll_dice("2d6"); self._log(f"  \U0001f3b2 2d6 = {r['dice']} = {r['total']}", "dice")

    def _refresh_all(self):
        self._update_meta()
        self._draw_clocks()
        self._draw_engines()
        self._draw_npcs()
        self._draw_factions()
        self._draw_world()
        self._update_pending()

    def run(self):
        self.root.mainloop()

if __name__ == "__main__":
    MacrosGUI().run()
