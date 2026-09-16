"""Universe accessor — sources from the index-built cache, static fallback.

At import it loads universe_cache.json (produced by universe_builder). If the
cache is missing it tries a live build; if that also fails it uses a tiny
static seed so the app still boots. Refresh the cache with:
    python -m tars.universe_builder
"""

from __future__ import annotations
import json
import os

_CACHE = os.path.join(os.path.dirname(__file__), "universe_cache.json")

_STATIC_SEED = {
    "LLY": {"name": "Eli Lilly", "tier": "big_pharma", "cik": "0000059478"},
    "MRK": {"name": "Merck & Co.", "tier": "big_pharma", "cik": "0000310158"},
    "VRTX": {"name": "Vertex Pharmaceuticals", "tier": "biotech", "cik": "0000875320"},
    "AMGN": {"name": "Amgen", "tier": "big_pharma", "cik": "0000318154"},
    "NVO": {"name": "Novo Nordisk", "tier": "adr", "cik": ""},
}

TIERS = {"big_pharma": "Big Pharma", "biotech": "Biotech", "adr": "ADR"}


def _load() -> dict:
    if os.path.exists(_CACHE):
        try:
            with open(_CACHE) as f:
                return json.load(f)
        except Exception:
            pass
    try:
        from .universe_builder import build
        u = build()
        if u:
            return u
    except Exception as e:
        print("[universe] live build failed, using static seed:", e)
    return dict(_STATIC_SEED)


UNIVERSE = _load()


def refresh() -> int:
    """Force a rebuild from index sources; returns new size."""
    global UNIVERSE
    from .universe_builder import build
    UNIVERSE = build(force=True)
    return len(UNIVERSE)


def is_allowed(ticker: str) -> bool:
    return (ticker or "").upper() in UNIVERSE


def get(ticker: str):
    return UNIVERSE.get((ticker or "").upper())


def search(q: str, limit: int = 50):
    q = (q or "").strip().lower()
    rows = []
    for tk, meta in UNIVERSE.items():
        if not q or q in tk.lower() or q in meta["name"].lower():
            rows.append({"ticker": tk, **meta})
    rows.sort(key=lambda r: (r["tier"], r["ticker"]))
    return rows[:limit]
