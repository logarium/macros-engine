"""
MACROS Engine v4.0 — Full Audit Session Report Generator (DG-19)
Generates self-contained HTML reports matching the comprehensive audit format.
All 18+ sections with inline CSS, table of contents, color-coded progress bars,
collapsible history entries, and defensive data access.
"""

from datetime import datetime


def generate_session_report(state, session_id: int) -> str:
    """Generate a comprehensive full-audit HTML session report. Returns a complete HTML string."""

    parts = []
    parts.append(_head(state, session_id))
    parts.append(_toc(state))
    parts.append(_session_summaries(state))
    parts.append(_session_meta(state))
    parts.append(_pc_state(state))
    parts.append(_risk_flags(state))
    parts.append(_clocks_active(state))
    parts.append(_fired_triggers(state))
    parts.append(_engines(state))
    parts.append(_zones(state))
    parts.append(_companions(state))
    parts.append(_all_npcs(state))
    parts.append(_factions(state))
    parts.append(_relationships(state))
    parts.append(_discoveries(state))
    parts.append(_ua_log(state))
    parts.append(_divine(state))
    parts.append(_threads(state))
    parts.append(_seed_overrides(state))
    parts.append(_losses(state))
    parts.append(_adjudication_log(state, session_id))
    parts.append("</body></html>")

    return "\n".join(parts)


# ─────────────────────────────────────────────────────
# CSS
# ─────────────────────────────────────────────────────

_CSS = (
    "body{background:#0d0d1a;color:#d4d4d4;font-family:'Segoe UI',Consolas,sans-serif;"
    "max-width:1100px;margin:0 auto;padding:24px;line-height:1.5}\n"
    "h1{color:#e67e22;border-bottom:3px solid #e67e22;padding-bottom:10px;font-size:1.8em;letter-spacing:1px}\n"
    "h2{color:#f39c12;margin-top:36px;border-bottom:1px solid #555;padding-bottom:6px;font-size:1.3em}\n"
    "h3{color:#e0c068;margin-top:18px;font-size:1.1em}\n"
    "h4{color:#aaa;margin-top:12px;font-size:0.95em}\n"
    "table{border-collapse:collapse;width:100%;margin:8px 0 16px 0;font-size:0.9em}\n"
    "th{background:#1a1a30;color:#f39c12;text-align:left;padding:7px 10px;border:1px solid #333;font-weight:600}\n"
    "td{padding:5px 10px;border:1px solid #2a2a2a;vertical-align:top}\n"
    "tr:nth-child(even){background:#12122a}\n"
    "tr:nth-child(odd){background:#0d0d1a}\n"
    ".bar-bg{background:#1a1a30;border-radius:4px;height:12px;width:140px;display:inline-block;vertical-align:middle}\n"
    ".bar-fill{height:12px;border-radius:4px}\n"
    ".fired{color:#e74c3c;font-weight:bold}\n"
    ".muted{color:#666;font-size:0.85em}\n"
    ".tag{display:inline-block;padding:1px 6px;border-radius:3px;font-size:0.8em;margin:1px 2px}\n"
    ".tag-cadence{background:#2a1a40;color:#9b59b6;border:1px solid #9b59b6}\n"
    ".tag-fired{background:#3a1a1a;color:#e74c3c;border:1px solid #e74c3c}\n"
    ".tag-companion{background:#1a2a40;color:#3498db;border:1px solid #3498db}\n"
    ".tag-with-pc{background:#1a3a1a;color:#27ae60;border:1px solid #27ae60}\n"
    ".section{background:#111128;padding:14px 16px;border-radius:6px;margin:8px 0;border-left:3px solid #e67e22}\n"
    ".section-inner{background:#0e0e22;padding:10px 14px;border-radius:4px;margin:6px 0;border-left:2px solid #555}\n"
    ".meta-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin:12px 0}\n"
    ".meta-box{background:#111128;padding:10px;border-radius:6px;text-align:center;border:1px solid #2a2a40}\n"
    ".meta-label{color:#888;font-size:0.8em;text-transform:uppercase;letter-spacing:1px}\n"
    ".meta-value{color:#f39c12;font-size:1.4em;font-weight:bold}\n"
    ".summary-block{background:#111128;padding:16px;border-radius:6px;margin:8px 0;line-height:1.7;"
    "white-space:pre-wrap;font-size:0.92em}\n"
    ".hist-entry{margin:3px 0;padding:3px 0;border-bottom:1px solid #1a1a2a;font-size:0.88em}\n"
    ".hist-session{color:#e67e22;font-weight:bold;min-width:30px;display:inline-block}\n"
    ".hist-date{color:#888;min-width:70px;display:inline-block}\n"
    "ul{margin:4px 0;padding-left:20px}\n"
    "li{margin:2px 0;font-size:0.92em}\n"
    ".toc{background:#111128;padding:16px;border-radius:6px;margin:16px 0}\n"
    ".toc a{color:#3498db;text-decoration:none}\n"
    ".toc a:hover{text-decoration:underline}\n"
    ".toc li{margin:4px 0}\n"
    "details{margin:4px 0}\n"
    "details summary{cursor:pointer;color:#e0c068;font-weight:500}\n"
    "details summary:hover{color:#f39c12}\n"
)


# ─────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────

def _esc(text) -> str:
    """HTML-escape a string."""
    return (
        str(text)
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&#x27;")
    )


def _g(obj, field, default=""):
    """Defensively get an attribute or dict key."""
    if isinstance(obj, dict):
        return obj.get(field, default)
    return getattr(obj, field, default)


def _history_html(entries):
    """Render a list of history entries (strings or dicts) as hist-entry divs."""
    if not entries:
        return ""
    lines = []
    for e in entries:
        if isinstance(e, dict):
            sess = _g(e, "session", "")
            date = _g(e, "date", "")
            text = _g(e, "event", _g(e, "text", _g(e, "detail", str(e))))
            lines.append(
                f"<div class='hist-entry'>"
                f"<span class='hist-session'>S{_esc(sess)}</span> "
                f"<span class='hist-date'>{_esc(date)}</span> "
                f"{_esc(text)}</div>"
            )
        else:
            lines.append(f"<div class='hist-entry'>{_esc(e)}</div>")
    return "\n".join(lines)


def _sort_session_key(sid):
    """Sort key for session ID strings — numeric first, then alpha."""
    try:
        return (0, int(sid), "")
    except (ValueError, TypeError):
        # Try to extract leading number
        num_part = ""
        rest = str(sid)
        for ch in rest:
            if ch.isdigit():
                num_part += ch
            else:
                break
        if num_part:
            return (0, int(num_part), rest[len(num_part):])
        return (1, 0, str(sid))


def _progress_color(progress, max_progress):
    """Return color for progress bar: >=80% red, >=50% orange, else teal."""
    pct = (progress / max_progress * 100) if max_progress > 0 else 0
    if pct >= 80:
        return "#e74c3c"
    if pct >= 50:
        return "#e67e22"
    return "#27ae60"


def _progress_pct(progress, max_progress):
    """Return integer percentage."""
    if max_progress <= 0:
        return 0
    return int(progress / max_progress * 100)


def _disposition_color(disp):
    """Color-code faction disposition."""
    d = str(disp).lower()
    if "hostile" in d:
        return "#e74c3c"
    if "friendly" in d or "loyal" in d or "allied" in d:
        return "#27ae60"
    return "#d4d4d4"


def _threat_color(threat):
    """Color-code zone threat level."""
    t = str(threat).lower()
    if "high" in t or "lethal" in t or "escalat" in t:
        return "#e74c3c"
    if "moderate" in t or "medium" in t:
        return "#e67e22"
    if "stabilized" in t or "low" in t:
        return "#27ae60"
    return "#d4d4d4"


def _risk_color(level):
    """Color-code risk flag level."""
    lv = str(level).upper()
    if "CRITICAL" in lv:
        return "#e74c3c"
    if "HIGH" in lv:
        return "#e67e22"
    if "MODERATE" in lv:
        return "#f1c40f"
    return "#d4d4d4"


def _certainty_color(cert):
    """Color-code discovery certainty."""
    c = str(cert).lower()
    if "confirmed" in c:
        return "#27ae60"
    if "uncertain" in c:
        return "#e67e22"
    if "inferred" in c:
        return "#f1c40f"
    if "rumor" in c or "rumour" in c:
        return "#e74c3c"
    return "#d4d4d4"


def _status_color(status):
    """Color-code NPC status."""
    s = str(status).lower()
    if "dead" in s:
        return "#e74c3c"
    if "missing" in s:
        return "#e67e22"
    return "#d4d4d4"


def _bullet_list(items, label=""):
    """Render a list as <ul> with optional bold label prefix."""
    if not items:
        return ""
    prefix = f"<b>{_esc(label)}</b>" if label else ""
    inner = "\n".join(f"<li>{_esc(i)}</li>" for i in items)
    return f"{prefix}<ul>\n{inner}\n</ul>"


# ─────────────────────────────────────────────────────
# SECTION BUILDERS
# ─────────────────────────────────────────────────────

def _head(state, session_id):
    """Header block: doctype, CSS, h1, meta-grid, intensity line."""
    return (
        f"<!DOCTYPE html><html><head><meta charset='utf-8'>\n"
        f"<title>Gammaria \u2014 Full Audit Report</title>\n"
        f"<style>\n{_CSS}</style></head><body>\n\n"
        f"<h1>GAMMARIA \u2014 Session {session_id} Full Audit Report</h1>\n"
        f"<div class='meta-grid'>\n"
        f"<div class='meta-box'><div class='meta-label'>Session</div>"
        f"<div class='meta-value'>{session_id}</div></div>\n"
        f"<div class='meta-box'><div class='meta-label'>Date</div>"
        f"<div class='meta-value'>{_esc(state.in_game_date)}</div></div>\n"
        f"<div class='meta-box'><div class='meta-label'>Zone</div>"
        f"<div class='meta-value'>{_esc(state.pc_zone)}</div></div>\n"
        f"<div class='meta-box'><div class='meta-label'>Season</div>"
        f"<div class='meta-value'>{_esc(state.season)}</div></div>\n"
        f"</div>\n"
        f"<p class='muted'>Intensity: {_esc(state.campaign_intensity)}"
        f" | Seasonal Pressure: {_esc(state.seasonal_pressure)}</p>"
    )


def _toc(state):
    """Table of contents."""
    pc_name = _g(state.pc_state, "name", "PC") if state.pc_state else "PC"
    items = [
        ("summaries", "Session Summaries"),
        ("session-meta", "Session Meta (Tone / Pacing / Pressure)"),
        ("pc", f"PC State \u2014 {_esc(pc_name)}"),
        ("risk-flags", "NPC Risk Flags"),
        ("clocks", "Clocks (Active)"),
        ("fired", "Fired Triggers"),
        ("engines", "Engines"),
        ("zones", "Zone Summary"),
        ("companions", "Companions"),
        ("npcs", "All NPCs"),
        ("factions", "Factions"),
        ("relationships", "Relationships"),
        ("discoveries", "Discoveries"),
        ("ua-log", "Unknown Anomalies (UA Log)"),
        ("divine", "Divine / Metaphysical Consequences"),
        ("threads", "Unresolved Threads"),
        ("seed-overrides", "Seed Overrides"),
        ("losses", "Losses &amp; Irreversibles"),
        ("log", "Adjudication Log"),
    ]
    li = "\n".join(f"<li><a href='#{aid}'>{label}</a></li>" for aid, label in items)
    return f"<div class='toc'><strong>Contents</strong><ul>\n{li}\n</ul></div>"


def _session_summaries(state):
    """Section: all session summaries sorted numerically."""
    lines = ["<h2 id='summaries'>Session Summaries</h2>"]
    summaries = state.session_summaries or {}
    if not summaries:
        lines.append("<p class='muted'>No session summaries recorded.</p>")
        return "\n".join(lines)

    sorted_keys = sorted(summaries.keys(), key=_sort_session_key)
    for sid in sorted_keys:
        text = summaries[sid]
        # If the value is a dict (e.g. session_meta accidentally stored), render as string
        if isinstance(text, dict):
            text = str(text)
        lines.append(f"<h3>Session {_esc(sid)}</h3>")
        lines.append(f"<div class='summary-block'>{_esc(text)}</div>")

    return "\n".join(lines)


def _session_meta(state):
    """Section: session meta (tone_shift, pacing, next_session_pressure) per session."""
    lines = ["<h2 id='session-meta'>Session Meta \u2014 Tone / Pacing / Pressure</h2>"]
    meta_dict = state.session_meta or {}
    if not meta_dict:
        lines.append("<p class='muted'>No session meta recorded.</p>")
        return "\n".join(lines)

    sorted_keys = sorted(meta_dict.keys(), key=_sort_session_key)
    for sid in sorted_keys:
        m = meta_dict[sid]
        if not isinstance(m, dict):
            continue
        tone = _g(m, "tone_shift", "")
        pacing = _g(m, "pacing", "")
        pressure = _g(m, "next_session_pressure", "")
        if not (tone or pacing or pressure):
            continue

        lines.append(f"<h3>Session {_esc(sid)}</h3>")
        lines.append("<div class='section'>")
        if tone:
            lines.append(f"<b>Tone Shift:</b> {_esc(tone)}<br>")
        if pacing:
            lines.append(f"<b>Pacing:</b> {_esc(pacing)}<br>")
        if pressure:
            lines.append(
                f"<b>Next Session Pressure:</b><br>"
                f"<div style='white-space:pre-wrap;margin-left:12px;font-size:0.9em'>"
                f"{_esc(pressure)}</div>"
            )
        lines.append("</div>")

    return "\n".join(lines)


def _pc_state(state):
    """Section: PC state — reputation, affection, equipment, goals, psych, secrets, history."""
    pc = state.pc_state
    pc_name = _g(pc, "name", "PC") if pc else "PC"
    lines = [f"<h2 id='pc'>PC State \u2014 {_esc(pc_name)}</h2>"]

    if not pc:
        lines.append("<p class='muted'>No PC state recorded.</p>")
        return "\n".join(lines)

    lines.append("<div class='section'>")

    # Reputation
    rep = _g(pc, "reputation", "")
    lines.append(f"<b>Reputation:</b> {_esc(rep) if rep else '\u2014'}<br>")

    # Reputation levels
    rep_levels = _g(pc, "reputation_levels", {})
    if rep_levels and isinstance(rep_levels, dict):
        lines.append("<b>Reputation Levels:</b><ul>")
        for zone, level in sorted(rep_levels.items()):
            lines.append(f"<li><b>{_esc(zone)}:</b> {_esc(level)}</li>")
        lines.append("</ul>")

    # Affection summary
    aff = _g(pc, "affection_summary", "")
    if aff:
        lines.append(f"<b>Affection Summary:</b> {_esc(aff)}<br>")

    # Equipment
    equip = _g(pc, "equipment_notes", "")
    if equip:
        lines.append(f"<b>Equipment:</b> {_esc(equip)}<br>")

    # Conditions
    conditions = _g(pc, "conditions", [])
    if conditions:
        lines.append("<h4>Conditions</h4><ul>")
        for c in conditions:
            lines.append(f"<li>{_esc(c)}</li>")
        lines.append("</ul>")

    # Goals
    goals = _g(pc, "goals", [])
    lines.append("<h4>Goals</h4>")
    if goals:
        lines.append("<ul>")
        for g in goals:
            lines.append(f"<li>{_esc(g)}</li>")
        lines.append("</ul>")
    else:
        lines.append("<p class='muted'>None</p>")

    # Psychological state
    psych = _g(pc, "psychological_state", [])
    lines.append("<h4>Psychological State</h4>")
    if psych:
        lines.append("<ul>")
        for p in psych:
            lines.append(f"<li>{_esc(p)}</li>")
        lines.append("</ul>")
    else:
        lines.append("<p class='muted'>None</p>")

    # Secrets
    secrets = _g(pc, "secrets", [])
    lines.append("<h4>Secrets</h4>")
    if secrets:
        lines.append("<ul>")
        for s in secrets:
            lines.append(f"<li>{_esc(s)}</li>")
        lines.append("</ul>")
    else:
        lines.append("<p class='muted'>None</p>")

    # History
    history = _g(pc, "history", [])
    if history:
        lines.append("<h4>History</h4>")
        lines.append(_history_html(history))

    lines.append("</div>")
    return "\n".join(lines)


def _risk_flags(state):
    """Section: NPC risk flags table."""
    lines = ["<h2 id='risk-flags'>NPC Risk Flags</h2>"]
    flags = state.npc_risk_flags or []
    if not flags:
        lines.append("<p class='muted'>No risk flags recorded.</p>")
        return "\n".join(lines)

    lines.append(
        "<table><tr><th>NPC</th><th>Risk Type</th><th>Level</th>"
        "<th>Triggers</th><th>Consequences</th><th>Basis</th></tr>"
    )
    for rf in flags:
        npc = _g(rf, "npc_name", _g(rf, "npc", ""))
        rtype = _g(rf, "risk_type", "")
        level = _g(rf, "level", "")
        triggers = _g(rf, "triggers", "")
        consequences = _g(rf, "consequences", "")
        basis = _g(rf, "basis", "")
        color = _risk_color(level)

        lines.append(
            f"<tr><td><b>{_esc(npc)}</b></td>"
            f"<td>{_esc(rtype)}</td>"
            f"<td style='color:{color};font-weight:bold'>{_esc(level)}</td>"
            f"<td style='font-size:0.85em'>{_esc(triggers)}</td>"
            f"<td style='font-size:0.85em'>{_esc(consequences)}</td>"
            f"<td style='font-size:0.8em'>{_esc(basis)}</td></tr>"
        )
    lines.append("</table>")
    return "\n".join(lines)


def _clocks_active(state):
    """Section: active/halted clocks with full detail."""
    lines = ["<h2 id='clocks'>Clocks \u2014 Active</h2>"]
    clocks = state.clocks or {}
    if not clocks:
        lines.append("<p class='muted'>No clocks registered.</p>")
        return "\n".join(lines)

    # Sort: active first, then halted; by progress pct descending
    active_clocks = [
        c for c in clocks.values()
        if _g(c, "status", "active") in ("active", "halted")
    ]
    active_clocks.sort(
        key=lambda c: -_progress_pct(_g(c, "progress", 0), _g(c, "max_progress", 1))
    )

    if not active_clocks:
        lines.append("<p class='muted'>No active or halted clocks.</p>")
        return "\n".join(lines)

    for c in active_clocks:
        name = _g(c, "name", "Unknown")
        owner = _g(c, "owner", "")
        progress = _g(c, "progress", 0)
        max_prog = _g(c, "max_progress", 1)
        status = _g(c, "status", "active")
        is_cadence = _g(c, "is_cadence", False)
        adv = _g(c, "advance_bullets", [])
        halt = _g(c, "halt_conditions", [])
        red = _g(c, "reduce_conditions", [])
        trigger = _g(c, "trigger_on_completion", "")
        notes = _g(c, "notes", "")
        fired = _g(c, "trigger_fired", False)

        pct = _progress_pct(progress, max_prog)
        color = _progress_color(progress, max_prog)

        lines.append("<div class='section'>")

        # Name with color and tags
        tags = ""
        if is_cadence:
            tags += " <span class='tag tag-cadence'>CADENCE</span>"
        if fired:
            tags += " <span class='tag tag-fired'>FIRED</span>"

        lines.append(f"<b style='color:{color}'>{_esc(name)}</b>{tags}<br>")

        if owner:
            lines.append(f"<span class='muted'>Owner: {_esc(owner)}</span><br>")

        # Progress bar
        lines.append(
            f"<div class=\"bar-bg\"><div class=\"bar-fill\" "
            f"style=\"background:{color};width:{pct}%\"></div></div> "
            f"<b>{progress}/{max_prog}</b><br>"
        )

        # ADV bullets
        if adv:
            lines.append("<b>ADV:</b><ul>")
            for a in adv:
                lines.append(f"<li>{_esc(a)}</li>")
            lines.append("</ul>")

        # HALT conditions
        if halt:
            lines.append("<b>HALT:</b><ul>")
            for h in halt:
                lines.append(f"<li>{_esc(h)}</li>")
            lines.append("</ul>")

        # RED (reduce) conditions
        if red:
            lines.append("<b style='color:#27ae60'>RED:</b><ul>")
            for r in red:
                lines.append(f"<li>{_esc(r)}</li>")
            lines.append("</ul>")

        # Trigger text
        if trigger:
            lines.append(f"<b>TRIGGER:</b> {_esc(trigger)}<br>")

        # Notes
        if notes:
            lines.append(f"<span class='muted'>Notes: {_esc(notes)}</span><br>")

        lines.append("</div>")

    return "\n".join(lines)


def _fired_triggers(state):
    """Section: clocks where trigger_fired == True."""
    lines = ["<h2 id='fired'>Fired Triggers</h2>"]
    clocks = state.clocks or {}

    fired = [
        c for c in clocks.values()
        if _g(c, "trigger_fired", False)
    ]

    if not fired:
        lines.append("<p class='muted'>No triggers have fired.</p>")
        return "\n".join(lines)

    lines.append("<table><tr><th>Clock</th><th>Trigger Text</th></tr>")
    for c in sorted(fired, key=lambda x: _g(x, "name", "")):
        name = _g(c, "name", "Unknown")
        trigger_text = _g(c, "trigger_fired_text", _g(c, "trigger_on_completion", ""))
        if not trigger_text:
            trigger_text = "(fired)"
        lines.append(
            f"<tr><td class='fired'>{_esc(name)}</td>"
            f"<td>{_esc(trigger_text)}</td></tr>"
        )
    lines.append("</table>")
    return "\n".join(lines)


def _engines(state):
    """Section: engines with detail."""
    lines = ["<h2 id='engines'>Engines</h2>"]
    engines = state.engines or {}
    if not engines:
        lines.append("<p class='muted'>No engines registered.</p>")
        return "\n".join(lines)

    for e in sorted(engines.values(), key=lambda x: _g(x, "name", "")):
        name = _g(e, "name", "Unknown")
        version = _g(e, "version", "")
        status = _g(e, "status", "active")
        cadence = _g(e, "cadence", False)
        auth = _g(e, "authority_tier", "")
        zone_scope = _g(e, "zone_scope", "")
        state_scope = _g(e, "state_scope", "")
        trigger_event = _g(e, "trigger_event", "")
        resolution = _g(e, "resolution_method", "")
        linked = _g(e, "linked_clocks", [])
        last_date = _g(e, "last_run_date", "")
        last_sess = _g(e, "last_run_session", 0)
        roll_hist = _g(e, "roll_history", [])

        lines.append("<div class='section'>")

        ver_str = f" <span class='muted'>v{_esc(version)}</span>" if version else ""
        cad_str = "Yes" if cadence else "No"
        lines.append(
            f"<b>{_esc(name)}</b>{ver_str} | Status: {_esc(status)} | Cadence: {cad_str}<br>"
        )

        if auth or zone_scope:
            lines.append(
                f"<b>Authority:</b> {_esc(auth)}"
                f" | <b>Zone Scope:</b> {_esc(zone_scope)}<br>"
            )
        if state_scope:
            lines.append(f"<b>State Scope:</b> {_esc(state_scope)}<br>")
        if trigger_event:
            lines.append(f"<b>Trigger:</b> {_esc(trigger_event)}<br>")
        if resolution:
            lines.append(f"<b>Resolution:</b> {_esc(resolution)}<br>")
        if linked:
            lines.append(f"<b>Linked Clocks:</b> {_esc(', '.join(str(lc) for lc in linked))}<br>")
        if last_date or last_sess:
            lines.append(
                f"<span class='muted'>Last run: {_esc(last_date)}"
                f" (Session {last_sess})</span><br>"
            )

        # Roll history
        if roll_hist:
            lines.append(
                f"<details><summary>Roll History ({len(roll_hist)} entries)</summary>"
                f"<div style='font-size:0.85em;padding:6px'>"
            )
            for rh in roll_hist:
                lines.append(f"{_esc(str(rh))}<br>")
            lines.append("</div></details>")

        lines.append("</div>")

    return "\n".join(lines)


def _zones(state):
    """Section: zone summary table."""
    lines = ["<h2 id='zones'>Zone Summary</h2>"]
    zones = state.zones or {}
    if not zones:
        lines.append("<p class='muted'>No zones registered.</p>")
        return "\n".join(lines)

    lines.append(
        "<table><tr><th>Zone</th><th>Threat</th><th>Intensity</th>"
        "<th>Controlling Faction</th><th>Situation</th></tr>"
    )
    for z in sorted(zones.values(), key=lambda x: _g(x, "name", "")):
        name = _g(z, "name", "")
        threat = _g(z, "threat_level", "")
        intensity = _g(z, "intensity", "")
        faction = _g(z, "controlling_faction", "")
        situation = _g(z, "situation_summary", _g(z, "description", ""))

        t_color = _threat_color(threat)
        lines.append(
            f"<tr><td><b>{_esc(name)}</b></td>"
            f"<td style='color:{t_color}'>{_esc(threat) if threat else '\u2014'}</td>"
            f"<td>{_esc(intensity)}</td>"
            f"<td>{_esc(faction) if faction else '\u2014'}</td>"
            f"<td style='font-size:0.85em'>{_esc(situation) if situation else '\u2014'}</td></tr>"
        )
    lines.append("</table>")
    return "\n".join(lines)


def _companions(state):
    """Section: companions with full NPC + CompanionDetail data."""
    lines = ["<h2 id='companions'>Companions</h2>"]

    # Find companion NPCs
    comp_npcs = [
        n for n in (state.npcs or {}).values()
        if _g(n, "is_companion", False)
    ]
    comp_npcs.sort(key=lambda x: _g(x, "name", ""))

    if not comp_npcs:
        lines.append("<p class='muted'>No companions registered.</p>")
        return "\n".join(lines)

    for n in comp_npcs:
        name = _g(n, "name", "Unknown")
        zone = _g(n, "zone", "")
        with_pc = _g(n, "with_pc", False)

        # Header line
        location = ""
        if not with_pc and zone:
            location = f" @ {_esc(zone)}"
        tags = "<span class='tag tag-companion'>COMPANION</span> "
        if with_pc:
            tags_after = " <span class='tag tag-with-pc'>WITH PC</span>"
        else:
            tags_after = ""
        lines.append(f"<h3>{tags}{_esc(name)}{tags_after}{location}</h3>")
        lines.append("<div class='section'>")

        # NPC fields
        role = _g(n, "role", "")
        trait = _g(n, "trait", "")
        appearance = _g(n, "appearance", "")
        faction = _g(n, "faction", "")
        objective = _g(n, "objective", "")
        knowledge = _g(n, "knowledge", "")
        neg_knowledge = _g(n, "negative_knowledge", _g(n, "does_not_know", ""))
        next_action = _g(n, "next_action", "")

        if role:
            lines.append(f"<b>Role:</b> {_esc(role)}<br>")
        if trait:
            lines.append(f"<b>Trait:</b> {_esc(trait)}<br>")
        if appearance:
            lines.append(f"<b>Appearance:</b> {_esc(appearance)}<br>")
        if faction:
            lines.append(f"<b>Faction:</b> {_esc(faction)}<br>")
        if objective:
            lines.append(f"<b>Objective:</b> {_esc(objective)}<br>")
        if knowledge:
            lines.append(f"<b>Knowledge:</b> {_esc(knowledge)}<br>")
        if neg_knowledge:
            lines.append(f"<b>Does NOT Know:</b> {_esc(neg_knowledge)}<br>")
        if next_action:
            lines.append(f"<b>Next Action:</b> {_esc(next_action)}<br>")

        # BX stats
        bx_parts = []
        for field, label in [
            ("bx_ac", "AC"), ("bx_hd", "HD"), ("bx_hp", "HP"),
            ("bx_at", "AT"), ("bx_dmg", "Dmg"), ("bx_ml", "ML"),
        ]:
            val = _g(n, field, 0)
            if field == "bx_hp":
                hp = _g(n, "bx_hp", 0)
                hp_max = _g(n, "bx_hp_max", 0)
                if hp or hp_max:
                    bx_parts.append(f"HP={hp}/{hp_max}")
            elif field == "bx_dmg":
                if val:
                    bx_parts.append(f"Dmg={val}")
            elif field == "bx_at":
                if val:
                    bx_parts.append(f"AT=+{val}")
            else:
                if val:
                    bx_parts.append(f"{label}={val}")
        if bx_parts:
            lines.append(f"<b>BX:</b> {' '.join(bx_parts)}<br>")

        # CompanionDetail
        comp_detail = (state.companions or {}).get(name)
        if comp_detail:
            lines.append("<div class='section-inner'>")

            trust = _g(comp_detail, "trust_in_pc", "")
            mot = _g(comp_detail, "motivation_shift", "")
            loy = _g(comp_detail, "loyalty_change", "")
            stress = _g(comp_detail, "stress_or_fatigue", "")
            griev = _g(comp_detail, "grievances", "")
            agency = _g(comp_detail, "agency_notes", "")
            flash = _g(comp_detail, "future_flashpoints", "")
            affection = _g(comp_detail, "affection_levels", {})

            lines.append(f"<b>Trust in PC:</b> {_esc(trust) if trust else '\u2014'}<br>")
            lines.append(f"<b>Motivation Shift:</b> {_esc(mot) if mot else '\u2014'}<br>")
            lines.append(f"<b>Loyalty Change:</b> {_esc(loy) if loy else '\u2014'}<br>")
            lines.append(f"<b>Stress/Fatigue:</b> {_esc(stress) if stress else '\u2014'}<br>")
            lines.append(f"<b>Grievances:</b> {_esc(griev) if griev else '\u2014'}<br>")
            lines.append(f"<b>Agency Notes:</b> {_esc(agency) if agency else '\u2014'}<br>")
            lines.append(f"<b>Flashpoints:</b> {_esc(flash) if flash else '\u2014'}<br>")

            # Affection levels
            if affection and isinstance(affection, dict):
                lines.append("<b>Affection:</b><ul>")
                for person, level in sorted(affection.items()):
                    lines.append(f"<li><b>{_esc(person)}:</b> {_esc(level)}</li>")
                lines.append("</ul>")

            # Companion history
            comp_hist = _g(comp_detail, "history", [])
            if comp_hist:
                lines.append("<b>Companion History:</b>")
                lines.append(_history_html(comp_hist))

            lines.append("</div>")

        # NPC history
        npc_hist = _g(n, "history", [])
        if npc_hist:
            lines.append("<b>NPC History:</b>")
            lines.append(_history_html(npc_hist))

        lines.append("</div>")

    return "\n".join(lines)


def _all_npcs(state):
    """Section: all NPCs grouped by zone, with collapsible history."""
    lines = ["<h2 id='npcs'>All NPCs</h2>"]
    npcs = state.npcs or {}
    if not npcs:
        lines.append("<p class='muted'>No NPCs registered.</p>")
        return "\n".join(lines)

    # Skip companion NPCs (they're in the companions section already)
    non_companion = [
        n for n in npcs.values()
        if not _g(n, "is_companion", False)
    ]

    # Group by zone
    zone_groups = {}
    for n in non_companion:
        zone = _g(n, "zone", "") or "Unknown"
        zone_groups.setdefault(zone, []).append(n)

    if not zone_groups:
        lines.append("<p class='muted'>No non-companion NPCs registered.</p>")
        return "\n".join(lines)

    for zone_name in sorted(zone_groups.keys()):
        npcs_in_zone = sorted(zone_groups[zone_name], key=lambda x: _g(x, "name", ""))
        lines.append(f"<h3>{_esc(zone_name)}</h3>")
        lines.append(
            "<table><tr><th>Name</th><th>Role</th><th>Status</th>"
            "<th>Trait</th><th>Objective</th></tr>"
        )
        for n in npcs_in_zone:
            name = _g(n, "name", "")
            role = _g(n, "role", "")
            status = _g(n, "status", "active")
            trait = _g(n, "trait", "")
            objective = _g(n, "objective", "")
            s_color = _status_color(status)

            lines.append(
                f"<tr><td>{_esc(name)}</td>"
                f"<td>{_esc(role)}</td>"
                f"<td style='color:{s_color}'>{_esc(status)}</td>"
                f"<td>{_esc(trait)}</td>"
                f"<td>{_esc(objective)}</td></tr>"
            )
        lines.append("</table>")

        # History entries in collapsible details for NPCs with history
        for n in npcs_in_zone:
            hist = _g(n, "history", [])
            if hist:
                name = _g(n, "name", "")
                lines.append(
                    f"<details><summary>{_esc(name)} \u2014 "
                    f"{len(hist)} history entries</summary>"
                )
                lines.append(_history_html(hist))
                lines.append("</details>")

    return "\n".join(lines)


def _factions(state):
    """Section: factions table."""
    lines = ["<h2 id='factions'>Factions</h2>"]
    factions = state.factions or {}
    if not factions:
        lines.append("<p class='muted'>No factions registered.</p>")
        return "\n".join(lines)

    lines.append(
        "<table><tr><th>Faction</th><th>Status</th><th>Disposition</th>"
        "<th>Trend</th><th>Last Action</th></tr>"
    )
    for f in sorted(factions.values(), key=lambda x: _g(x, "name", "")):
        name = _g(f, "name", "")
        status = _g(f, "status", "")
        disp = _g(f, "disposition", "unknown")
        trend = _g(f, "trend", "")
        last_action = _g(f, "last_action", "")
        d_color = _disposition_color(disp)

        lines.append(
            f"<tr><td>{_esc(name)}</td>"
            f"<td>{_esc(status)}</td>"
            f"<td style='color:{d_color}'>{_esc(disp)}</td>"
            f"<td>{_esc(trend)}</td>"
            f"<td>{_esc(last_action) if last_action else '\u2014'}</td></tr>"
        )
    lines.append("</table>")
    return "\n".join(lines)


def _relationships(state):
    """Section: relationships table with collapsible history."""
    lines = ["<h2 id='relationships'>Relationships</h2>"]
    rels = state.relationships or {}
    if not rels:
        lines.append("<p class='muted'>No relationships registered.</p>")
        return "\n".join(lines)

    lines.append(
        "<table><tr><th>Parties</th><th>Type</th><th>Trust</th>"
        "<th>Loyalty</th><th>Current State</th></tr>"
    )
    for r in sorted(rels.values(), key=lambda x: _g(x, "id", "")):
        # Build parties string
        npc_a = _g(r, "npc_a", "")
        npc_b = _g(r, "npc_b", "")
        parties = _g(r, "parties", "")
        if not parties:
            parties = f"{npc_a} \u2194 {npc_b}" if (npc_a or npc_b) else "\u2014"

        rel_type = _g(r, "rel_type", _g(r, "type", ""))
        trust = _g(r, "trust", "")
        loyalty = _g(r, "loyalty", "")
        current = _g(r, "current_state", "")

        lines.append(
            f"<tr><td>{_esc(parties)}</td>"
            f"<td>{_esc(rel_type)}</td>"
            f"<td>{_esc(trust)}</td>"
            f"<td>{_esc(loyalty)}</td>"
            f"<td>{_esc(current)}</td></tr>"
        )
    lines.append("</table>")

    # Collapsible history for relationships with history
    for r in sorted(rels.values(), key=lambda x: _g(x, "id", "")):
        hist = _g(r, "history", [])
        if hist:
            npc_a = _g(r, "npc_a", "")
            npc_b = _g(r, "npc_b", "")
            parties = _g(r, "parties", "")
            if not parties:
                parties = f"{npc_a} \u2194 {npc_b}" if (npc_a or npc_b) else _g(r, "id", "")

            lines.append(
                f"<details><summary>{_esc(parties)} \u2014 "
                f"{len(hist)} history entries</summary>"
            )
            lines.append(_history_html(hist))
            lines.append("</details>")

    return "\n".join(lines)


def _discoveries(state):
    """Section: discoveries table."""
    lines = ["<h2 id='discoveries'>Discoveries</h2>"]
    discs = state.discoveries or []
    if not discs:
        lines.append("<p class='muted'>No discoveries recorded.</p>")
        return "\n".join(lines)

    lines.append(
        "<table><tr><th>ID</th><th>Zone</th><th>Certainty</th>"
        "<th>Source</th><th>Info</th></tr>"
    )
    for d in discs:
        did = _g(d, "id", "")
        zone = _g(d, "zone", "")
        cert = _g(d, "certainty", "uncertain")
        source = _g(d, "source", "")
        info = _g(d, "info", "")
        c_color = _certainty_color(cert)

        lines.append(
            f"<tr><td style='font-size:0.8em'>{_esc(did)}</td>"
            f"<td>{_esc(zone) if zone else '\u2014'}</td>"
            f"<td style='color:{c_color}'>{_esc(cert)}</td>"
            f"<td>{_esc(source)}</td>"
            f"<td>{_esc(info)}</td></tr>"
        )
    lines.append("</table>")
    return "\n".join(lines)


def _ua_log(state):
    """Section: Unknown Anomalies log table."""
    lines = ["<h2 id='ua-log'>Unknown Anomalies (UA Log)</h2>"]
    uas = state.ua_log or []
    if not uas:
        lines.append("<p class='muted'>No UA entries.</p>")
        return "\n".join(lines)

    lines.append(
        "<table><tr><th>UA ID</th><th>Status</th><th>Zone</th>"
        "<th>Description</th><th>Touched</th><th>Promotion</th></tr>"
    )
    for ua in uas:
        uid = _g(ua, "id", _g(ua, "ua_id", ""))
        status = _g(ua, "status", "")
        zone = _g(ua, "zone", "")
        desc = _g(ua, "description", "")
        touched = _g(ua, "touched", "")
        promo = _g(ua, "promotion", "")
        s_color = "#27ae60" if "ACTIVE" in str(status).upper() else "#d4d4d4"

        lines.append(
            f"<tr><td><b>{_esc(uid)}</b></td>"
            f"<td style='color:{s_color}'>{_esc(status)}</td>"
            f"<td>{_esc(zone)}</td>"
            f"<td>{_esc(desc)}</td>"
            f"<td>{_esc(touched)}</td>"
            f"<td>{_esc(promo)}</td></tr>"
        )
    lines.append("</table>")
    return "\n".join(lines)


def _divine(state):
    """Section: divine/metaphysical consequences."""
    lines = ["<h2 id='divine'>Divine / Metaphysical Consequences</h2>"]
    divines = state.divine_metaphysical or []
    if not divines:
        lines.append("<p class='muted'>No divine/metaphysical entries.</p>")
        return "\n".join(lines)

    # Group by name/entity
    groups = {}
    for d in divines:
        name = _g(d, "name", _g(d, "entity", _g(d, "deity", "Unknown")))
        groups.setdefault(name, []).append(d)

    for name in sorted(groups.keys()):
        entries = groups[name]
        lines.append(f"<h3>{_esc(name)}</h3>")

        for d in entries:
            lines.append("<div class='section'>")

            intervention = _g(d, "intervention", "")
            cost = _g(d, "cost", _g(d, "cost_incurred", ""))
            effects = _g(d, "effects", _g(d, "lingering_effects", ""))
            visibility = _g(d, "visibility", "")

            if intervention:
                lines.append(f"<b>Intervention:</b> {_esc(intervention)}<br>")
            if cost:
                lines.append(f"<b>Cost Incurred:</b> {_esc(cost)}<br>")
            if effects:
                lines.append(f"<b>Lingering Effects:</b> {_esc(effects)}<br>")
            if visibility:
                lines.append(f"<b>Visibility:</b> {_esc(visibility)}<br>")

            lines.append("</div>")

    return "\n".join(lines)


def _threads(state):
    """Section: unresolved threads — open and resolved."""
    lines = ["<h2 id='threads'>Unresolved Threads</h2>"]
    threads = state.unresolved_threads or []
    if not threads:
        lines.append("<p class='muted'>No threads recorded.</p>")
        return "\n".join(lines)

    # Split open vs resolved
    open_threads = [t for t in threads if not _g(t, "resolved", False)]
    resolved_threads = [t for t in threads if _g(t, "resolved", False)]

    # Open threads
    lines.append(f"<h3>Open ({len(open_threads)})</h3>")
    if open_threads:
        lines.append(
            "<table><tr><th>ID</th><th>Zone</th><th>Session</th><th>Description</th></tr>"
        )
        for t in open_threads:
            tid = _g(t, "id", "")
            zone = _g(t, "zone", "")
            sess = _g(t, "session_created", "")
            desc = _g(t, "description", "")
            lines.append(
                f"<tr><td style='font-size:0.8em'>{_esc(tid)}</td>"
                f"<td>{_esc(zone)}</td>"
                f"<td>S{_esc(str(sess))}</td>"
                f"<td>{_esc(desc)}</td></tr>"
            )
        lines.append("</table>")
    else:
        lines.append("<p class='muted'>None open.</p>")

    # Resolved threads in collapsible
    if resolved_threads:
        lines.append(f"<details><summary>Resolved ({len(resolved_threads)})</summary>")
        lines.append("<table><tr><th>ID</th><th>Zone</th><th>Resolution</th></tr>")
        for t in resolved_threads:
            tid = _g(t, "id", "")
            zone = _g(t, "zone", "")
            resolution = _g(t, "resolution", "")
            lines.append(
                f"<tr><td style='font-size:0.8em'>{_esc(tid)}</td>"
                f"<td>{_esc(zone)}</td>"
                f"<td>{_esc(resolution)}</td></tr>"
            )
        lines.append("</table></details>")

    return "\n".join(lines)


def _seed_overrides(state):
    """Section: seed overrides."""
    lines = ["<h2 id='seed-overrides'>Seed Overrides</h2>"]
    overrides = state.seed_overrides or []
    if not overrides:
        lines.append("<p class='muted'>No seed overrides.</p>")
        return "\n".join(lines)

    for s in overrides:
        section = _g(s, "section", "")
        nature = _g(s, "nature", "")
        reason = _g(s, "reason", "")
        details = _g(s, "details", "")

        lines.append("<div class='section'>")
        if section:
            lines.append(f"<b>Section:</b> {_esc(section)}<br>")
        if nature:
            lines.append(f"<b>Nature:</b> {_esc(nature)}<br>")
        if reason:
            lines.append(f"<b>Reason:</b> {_esc(reason)}<br>")
        if details:
            lines.append(
                f"<b>Details:</b><br>"
                f"<div style='white-space:pre-wrap;margin-left:12px;font-size:0.9em'>"
                f"{_esc(details)}</div>"
            )
        lines.append("</div>")

    return "\n".join(lines)


def _losses(state):
    """Section: losses and irreversibles."""
    lines = ["<h2 id='losses'>Losses &amp; Irreversibles</h2>"]
    losses = state.losses_irreversibles or []
    if not losses:
        lines.append("<p class='muted'>No losses or irreversibles recorded.</p>")
        return "\n".join(lines)

    for loss in losses:
        if isinstance(loss, dict):
            session = _g(loss, "session", "")
            date = _g(loss, "date", "")
            text = _g(loss, "text", _g(loss, "description", _g(loss, "detail", str(loss))))
            lines.append(
                f"<div class='section'><b>S{_esc(str(session))}</b> "
                f"{_esc(date)} \u2014 {_esc(text)}</div>"
            )
        else:
            lines.append(f"<div class='section'>{_esc(str(loss))}</div>")

    return "\n".join(lines)


def _adjudication_log(state, session_id):
    """Section: adjudication log in collapsible details."""
    lines = ["<h2 id='log'>Adjudication Log</h2>"]
    log = state.adjudication_log or []
    if not log:
        lines.append("<p class='muted'>No log entries.</p>")
        return "\n".join(lines)

    count = len(log)
    lines.append(f"<details><summary>{count} entries (click to expand)</summary>")
    lines.append(
        "<table><tr><th>Session</th><th>Date</th><th>Type</th><th>Detail</th></tr>"
    )

    for entry in log:
        sess = _g(entry, "session", "")
        date = _g(entry, "date", "")
        etype = _g(entry, "type", "")
        detail = _g(entry, "detail", _g(entry, "summary", ""))
        if isinstance(detail, dict):
            detail = str(detail)
        # Truncate long details
        detail_str = str(detail)[:200] if detail else ""

        lines.append(
            f"<tr><td>S{_esc(str(sess))}</td>"
            f"<td>{_esc(str(date))}</td>"
            f"<td>{_esc(etype)}</td>"
            f"<td style='font-size:0.85em'>{_esc(detail_str)}</td></tr>"
        )

    lines.append("</table></details>")
    return "\n".join(lines)
