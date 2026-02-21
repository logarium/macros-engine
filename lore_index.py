"""
MACROS Engine v4.0 — Lore Index (DG-20)
Parses docs/ lore files into indexed sections for targeted context injection.
Lazy singleton: loads once on first access, cached for session lifetime.
"""

import os
import re
import logging

logger = logging.getLogger("macros.lore")

# ─────────────────────────────────────────────────────
# ALL-CAPS HEADER REGEX
# Matches lines like "BARROW MOORS", "FISHER'S BEACH", "FORT SEAWATCH - DOCKS AND ALLEYS"
# ─────────────────────────────────────────────────────
_CAPS_HEADER_RE = re.compile(r"^[A-Z][A-Z\s\'\'\-\&\u2019]+$")

# NPC section header: §1 — VALANIA LORETHOR
_NPC_SECTION_RE = re.compile(r"^§\d+\s*[—\-–]\s*(.+)$")

# World section header: [WORLD OVERVIEW]
_WORLD_SECTION_RE = re.compile(r"^\[([^\]]+)\]$")

# PARTY-SEED character header
_SEED_PC_RE = re.compile(r"^PC_Name:\s*(.+)$")
_SEED_NPC_RE = re.compile(r"^PARTY_NPC_Name:\s*(.+)$")

# BX-PLUG section separator
_BX_SEPARATOR_RE = re.compile(r"^─{10,}$")

# BX-PLUG major section header (e.g., "0. BX-PLUG MACRO", "1. DATA DEFINITIONS")
_BX_MAJOR_RE = re.compile(r"^(\d+)\.\s+(.+)")

# Preamble lines to skip (common to lore files)
_PREAMBLE_MARKERS = ("Source:", "Authority:", "(")


# ─────────────────────────────────────────────────────
# LORE INDEX CLASS
# ─────────────────────────────────────────────────────

class LoreIndex:
    """Indexed lore data parsed from docs/ files."""

    def __init__(self):
        self.places = {}        # zone_name -> atmosphere text
        self.npcs = {}          # npc_name -> backstory text
        self.factions = {}      # faction_name -> lore text
        self.world = {}         # section_name -> world lore text
        self.party_seed = {}    # character_name -> seed text
        self.forge_specs = {}   # spec_name -> full spec text
        self.bx_sections = {}   # section_number_str -> section text

    # ── Lookup helpers ────────────────────────────────

    def get_zone_lore(self, zone_name: str) -> str:
        """Return atmosphere text for a zone, case-insensitive."""
        return _ci_lookup(self.places, zone_name)

    def get_npc_lore(self, npc_name: str, max_lines: int = 30) -> str:
        """Return NPC backstory, optionally truncated to max_lines."""
        text = _ci_lookup(self.npcs, npc_name)
        if text and max_lines > 0:
            lines = text.strip().split("\n")
            if len(lines) > max_lines:
                return "\n".join(lines[:max_lines]) + "\n[...truncated]"
        return text

    def get_faction_lore(self, faction_name: str) -> str:
        """Return faction lore text, case-insensitive."""
        return _ci_lookup(self.factions, faction_name)

    def get_world_section(self, section_key: str) -> str:
        """Return a world lore section by bracket key."""
        return _ci_lookup(self.world, section_key)

    def get_party_seed(self, character_name: str) -> str:
        """Return PARTY-SEED entry for a character."""
        return _ci_lookup(self.party_seed, character_name)

    def get_forge_spec(self, forge_name: str) -> str:
        """Return full forge spec text (e.g., 'NPC-FORGE')."""
        return self.forge_specs.get(forge_name, "")

    def get_bx_plug(self, section_ids: list) -> str:
        """Return concatenated BX-PLUG sections by ID (e.g., ['0', '1', '6'])."""
        parts = []
        for sid in section_ids:
            text = self.bx_sections.get(str(sid), "")
            if text:
                parts.append(text.strip())
        return "\n\n".join(parts)


# ─────────────────────────────────────────────────────
# CASE-INSENSITIVE LOOKUP
# ─────────────────────────────────────────────────────

def _ci_lookup(d: dict, key: str) -> str:
    """Case-insensitive dict lookup. Try exact, then lowered, then partial."""
    if not key:
        return ""
    # Exact
    if key in d:
        return d[key]
    # Case-insensitive
    key_lower = key.lower()
    for k, v in d.items():
        if k.lower() == key_lower:
            return v
    # Partial match (first name or substring)
    for k, v in d.items():
        if key_lower in k.lower():
            return v
    return ""


# ─────────────────────────────────────────────────────
# PARSERS
# ─────────────────────────────────────────────────────

def _read_file(path: str) -> str:
    """Read a file with UTF-8 encoding, handling BOM."""
    try:
        with open(path, "r", encoding="utf-8-sig") as f:
            return f.read()
    except FileNotFoundError:
        logger.warning(f"Lore file not found: {path}")
        return ""
    except Exception as e:
        logger.error(f"Error reading lore file {path}: {e}")
        return ""


def _is_preamble(line: str) -> bool:
    """Check if a line is a preamble line (Source:, Authority:, parenthetical)."""
    stripped = line.strip()
    return any(stripped.startswith(m) for m in _PREAMBLE_MARKERS)


def _parse_places(text: str) -> dict:
    """Parse LORE-PLACES: ALL-CAPS headers → atmosphere paragraphs."""
    result = {}
    lines = text.split("\n")
    current_name = None
    current_lines = []
    past_preamble = False

    for line in lines:
        stripped = line.strip()

        # Skip empty lines at start and preamble
        if not past_preamble:
            if not stripped or _is_preamble(stripped) or stripped.startswith("LORE-PLACES"):
                continue
            past_preamble = True

        # Check for ALL-CAPS section header
        if stripped and _CAPS_HEADER_RE.match(stripped):
            # Save previous section
            if current_name:
                result[current_name] = "\n".join(current_lines).strip()
            current_name = _normalize_zone_name(stripped)
            current_lines = []
        elif current_name is not None:
            current_lines.append(line.rstrip())

    # Save last section
    if current_name:
        result[current_name] = "\n".join(current_lines).strip()

    return result


def _normalize_zone_name(caps_name: str) -> str:
    """Convert ALL-CAPS zone name to title case matching game state keys.
    E.g., 'FORT SEAWATCH' → 'Fort Seawatch', 'FISHER'S BEACH' → "Fisher's Beach"
    """
    # Title case, but handle apostrophes and small words
    words = caps_name.strip().split()
    result = []
    for i, w in enumerate(words):
        # Handle words with apostrophes
        if "'" in w or "\u2019" in w:
            # Split on apostrophe, capitalize first part, lowercase rest
            parts = re.split(r"[''\u2019]", w)
            titled = parts[0].capitalize() + "'" + "".join(p.lower() for p in parts[1:])
            result.append(titled)
        elif w == "-":
            result.append("-")
        elif w == "&":
            result.append("&")
        else:
            result.append(w.capitalize())
    return " ".join(result)


def _parse_npcs(text: str) -> dict:
    """Parse LORE-NPCS: §N — NAME sections separated by ──── lines."""
    result = {}
    lines = text.split("\n")
    current_name = None
    current_lines = []

    for line in lines:
        stripped = line.strip()

        # Check for section header: §1 — VALANIA LORETHOR
        m = _NPC_SECTION_RE.match(stripped)
        if m:
            # Save previous section
            if current_name:
                result[current_name] = "\n".join(current_lines).strip()
            current_name = m.group(1).strip()
            # Normalize: "VALANIA LORETHOR" → "Valania Lorethor"
            current_name = current_name.title()
            current_lines = []
            continue

        # Skip separator lines
        if _BX_SEPARATOR_RE.match(stripped):
            continue

        if current_name is not None:
            current_lines.append(line.rstrip())

    # Save last section
    if current_name:
        result[current_name] = "\n".join(current_lines).strip()

    return result


def _parse_factions(text: str) -> dict:
    """Parse LORE-FACTIONS: ALL-CAPS faction names → lore paragraphs."""
    result = {}
    lines = text.split("\n")
    current_name = None
    current_lines = []
    past_preamble = False

    for line in lines:
        stripped = line.strip()

        # Skip preamble
        if not past_preamble:
            if not stripped or _is_preamble(stripped) or stripped.startswith("LORE-FACTIONS"):
                continue
            # "FOUNDATIONAL FACTIONS (from NSV-FACTIONS)" has lowercase — skip it
            if "(" in stripped:
                continue
            past_preamble = True

        # Check for ALL-CAPS section header
        if stripped and _CAPS_HEADER_RE.match(stripped):
            if current_name:
                result[current_name] = "\n".join(current_lines).strip()
            current_name = stripped.title()
            current_lines = []
        elif current_name is not None:
            current_lines.append(line.rstrip())

    if current_name:
        result[current_name] = "\n".join(current_lines).strip()

    return result


def _parse_world(text: str) -> dict:
    """Parse LORE-WORLD: [SECTION] bracket headers → content."""
    result = {}
    lines = text.split("\n")
    current_section = None
    current_lines = []

    for line in lines:
        stripped = line.strip()

        m = _WORLD_SECTION_RE.match(stripped)
        if m:
            if current_section:
                result[current_section] = "\n".join(current_lines).strip()
            current_section = m.group(1).strip()
            current_lines = []
        elif current_section is not None:
            current_lines.append(line.rstrip())

    if current_section:
        result[current_section] = "\n".join(current_lines).strip()

    return result


def _parse_party_seed(text: str) -> dict:
    """Parse PARTY-SEED: PC_Name: / PARTY_NPC_Name: delimiters."""
    result = {}
    lines = text.split("\n")
    current_name = None
    current_lines = []

    for line in lines:
        stripped = line.strip()

        # Check for PC header
        m = _SEED_PC_RE.match(stripped)
        if m:
            if current_name:
                result[current_name] = "\n".join(current_lines).strip()
            current_name = m.group(1).strip()
            current_lines = [line.rstrip()]
            continue

        # Check for NPC header
        m = _SEED_NPC_RE.match(stripped)
        if m:
            if current_name:
                result[current_name] = "\n".join(current_lines).strip()
            current_name = m.group(1).strip()
            current_lines = [line.rstrip()]
            continue

        if current_name is not None:
            current_lines.append(line.rstrip())

    if current_name:
        result[current_name] = "\n".join(current_lines).strip()

    return result


def _parse_bx_plug(text: str) -> dict:
    """Parse BX-PLUG.txt: split on ──── separators, key by major section number."""
    result = {}
    lines = text.split("\n")
    chunks = []
    current_chunk = []

    for line in lines:
        if _BX_SEPARATOR_RE.match(line.strip()):
            if current_chunk:
                chunks.append("\n".join(current_chunk))
                current_chunk = []
        else:
            current_chunk.append(line.rstrip())

    if current_chunk:
        chunks.append("\n".join(current_chunk))

    # Key each chunk by its first major section number
    for chunk in chunks:
        stripped = chunk.strip()
        if not stripped:
            continue
        m = _BX_MAJOR_RE.match(stripped)
        if m:
            section_id = m.group(1)
            result[section_id] = stripped
        elif not result:
            # Pre-section content (unlikely but handle gracefully)
            result["preamble"] = stripped

    return result


# ─────────────────────────────────────────────────────
# LOADER
# ─────────────────────────────────────────────────────

_FORGE_SPEC_FILES = [
    "NPC-FORGE.txt",
    "EL-FORGE.txt",
    "FAC-FORGE.txt",
    "CL-FORGE.txt",
    "CAN-FORGE.txt",
    "PE-FORGE.txt",
    "UA-FORGE.txt",
    "ZONE-FORGE.txt",
]


def _load_index(docs_dir: str) -> LoreIndex:
    """Load and parse all lore files from docs_dir."""
    idx = LoreIndex()

    # LORE-PLACES
    text = _read_file(os.path.join(docs_dir, "LORE-PLACES v1.0.txt"))
    if text:
        idx.places = _parse_places(text)
        logger.info(f"Lore: loaded {len(idx.places)} place entries")

    # LORE-NPCS
    text = _read_file(os.path.join(docs_dir, "LORE-NPCS v2.0.txt"))
    if text:
        idx.npcs = _parse_npcs(text)
        logger.info(f"Lore: loaded {len(idx.npcs)} NPC entries")

    # LORE-FACTIONS
    text = _read_file(os.path.join(docs_dir, "LORE-FACTIONS v1.0.txt"))
    if text:
        idx.factions = _parse_factions(text)
        logger.info(f"Lore: loaded {len(idx.factions)} faction entries")

    # LORE-WORLD
    text = _read_file(os.path.join(docs_dir, "LORE-WORLD v1.0.txt"))
    if text:
        idx.world = _parse_world(text)
        logger.info(f"Lore: loaded {len(idx.world)} world sections")

    # PARTY-SEED
    text = _read_file(os.path.join(docs_dir, "PARTY-SEED.txt"))
    if text:
        idx.party_seed = _parse_party_seed(text)
        logger.info(f"Lore: loaded {len(idx.party_seed)} party seed entries")

    # Forge specs (loaded in full)
    for fname in _FORGE_SPEC_FILES:
        text = _read_file(os.path.join(docs_dir, fname))
        if text:
            spec_name = fname.replace(".txt", "")
            idx.forge_specs[spec_name] = text.strip()
    logger.info(f"Lore: loaded {len(idx.forge_specs)} forge specs")

    # BX-PLUG sections
    text = _read_file(os.path.join(docs_dir, "BX-PLUG.txt"))
    if text:
        idx.bx_sections = _parse_bx_plug(text)
        logger.info(f"Lore: loaded {len(idx.bx_sections)} BX-PLUG sections")

    return idx


# ─────────────────────────────────────────────────────
# PUBLIC API
# ─────────────────────────────────────────────────────

_index = None


def get_lore_index(docs_dir: str = None) -> LoreIndex:
    """Return cached LoreIndex, building it on first call."""
    global _index
    if _index is None:
        if docs_dir is None:
            docs_dir = os.path.join(os.path.dirname(__file__), "docs")
        _index = _load_index(docs_dir)
    return _index


def reset_lore_index():
    """Reset cached index (for testing or if docs change)."""
    global _index
    _index = None
