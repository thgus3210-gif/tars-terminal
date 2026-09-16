"""Deterministic sample provider — no network, always available.

Numbers are illustrative placeholders (seeded per-ticker so they're stable
between calls but obviously not real market data). It exists so the whole
app runs end-to-end with zero API keys, and as a reference for the exact
shapes a real adapter must return.
"""

from __future__ import annotations
import hashlib
import random
from datetime import datetime, timezone

from ..universe import UNIVERSE, get as u_get, is_allowed


def _rng(ticker: str, salt: str = "") -> random.Random:
    h = hashlib.sha256(f"{ticker}:{salt}".encode()).hexdigest()
    return random.Random(int(h[:12], 16))


def _now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


_PHASES = ["Preclinical", "Phase 1", "Phase 2", "Phase 3", "Filed", "Approved"]
_MODALITIES = ["Small molecule", "mAb", "siRNA", "Gene therapy", "Cell therapy", "Peptide"]
_AREAS = ["Oncology", "Immunology", "Neuroscience", "Rare disease",
          "Cardiometabolic", "Infectious disease"]


class SampleProvider:
    name = "sample"

    def _require(self, ticker: str):
        if not is_allowed(ticker):
            raise KeyError(ticker)
        return u_get(ticker)

    async def quote(self, ticker: str) -> dict:
        meta = self._require(ticker)
        r = _rng(ticker, "quote")
        price = round(r.uniform(40, 900), 2)
        change = round(r.uniform(-3, 3), 2)
        return {
            "ticker": ticker.upper(),
            "name": meta["name"],
            "price": price,
            "change": change,
            "change_pct": round(change / price * 100, 2),
            "currency": "USD",
            "market_cap": int(price * r.uniform(1.5e8, 2.5e9)),
            "day_high": round(price * 1.012, 2),
            "day_low": round(price * 0.987, 2),
            "volume": int(r.uniform(5e5, 3e7)),
            "ts": _now(),
            "stale": True,   # sample data is never live
        }

    async def profile(self, ticker: str) -> dict:
        meta = self._require(ticker)
        return {
            "ticker": ticker.upper(),
            "name": meta["name"],
            "tier": meta["tier"],
            "exchange": "NASDAQ" if meta["tier"] == "biotech" else "NYSE",
            "sector": "Healthcare",
            "industry": "Biotechnology" if meta["tier"] == "biotech"
                        else "Drug Manufacturers—General",
            "employees": _rng(ticker, "emp").randint(1_500, 130_000),
            "website": f"https://example.com/{ticker.lower()}",
            "description": f"{meta['name']} — placeholder profile from the sample "
                           f"provider. Wire a real adapter for live data.",
        }

    async def financials(self, ticker: str) -> dict:
        self._require(ticker)
        r = _rng(ticker, "fin")
        rev = int(r.uniform(1e9, 6e10))
        return {
            "ticker": ticker.upper(),
            "revenue_ttm": rev,
            "net_income_ttm": int(rev * r.uniform(-0.2, 0.35)),
            "rd_expense_ttm": int(rev * r.uniform(0.12, 0.45)),
            "cash": int(r.uniform(5e8, 2e10)),
            "debt": int(r.uniform(0, 3e10)),
            "gross_margin": round(r.uniform(0.55, 0.9), 3),
            "period": "TTM (sample)",
            "source": "sample",
        }

    async def pipeline(self, ticker: str) -> list:
        self._require(ticker)
        r = _rng(ticker, "pipe")
        n = r.randint(3, 7)
        out = []
        for i in range(n):
            out.append({
                "asset": f"{ticker.upper()}-{r.randint(100, 999)}",
                "indication": r.choice(_AREAS),
                "phase": r.choice(_PHASES),
                "modality": r.choice(_MODALITIES),
                "status": r.choice(["Active", "Recruiting", "On hold", "Completed"]),
                "updated": _now()[:10],
            })
        return out

    async def news(self, ticker: str, limit: int = 8) -> list:
        meta = self._require(ticker)
        r = _rng(ticker, "news")
        heads = [
            f"{meta['name']} reports pipeline update",
            f"Analysts weigh in on {ticker.upper()} readout",
            f"{meta['name']} presents data at medical congress",
            f"{ticker.upper()} FDA milestone in focus",
        ]
        return [{
            "title": heads[i % len(heads)],
            "url": "https://example.com/news",
            "source": "Sample Wire",
            "published": _now(),
        } for i in range(min(limit, 4))]
