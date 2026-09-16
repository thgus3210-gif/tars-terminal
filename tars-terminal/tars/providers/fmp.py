"""Financial Modeling Prep adapter — example real-time quote/financials source.

Set QUOTE_PROVIDER=fmp and FMP_API_KEY=... to activate. Any vendor with
per-ticker quote/profile/income endpoints (Finnhub, Polygon, Tiingo, Alpha
Vantage) maps onto the same methods — copy this file and change the URLs.

Design notes baked in here:
  * Short TTL in-memory cache so a busy watchlist doesn't hammer the vendor
    (quotes ~15s, profile/financials ~12h).
  * Universe filter first — we never spend a request on an off-universe ticker.
  * ProviderError on upstream failure; the router degrades gracefully.
"""

from __future__ import annotations
import time
from datetime import datetime, timezone

import httpx

from ..universe import is_allowed, get as u_get
from .base import ProviderError

_BASE = "https://financialmodelingprep.com/api/v3"


class _TTLCache:
    def __init__(self):
        self._d: dict[str, tuple[float, object]] = {}

    def get(self, key, ttl):
        hit = self._d.get(key)
        if hit and (time.time() - hit[0]) < ttl:
            return hit[1]
        return None

    def put(self, key, value):
        self._d[key] = (time.time(), value)


class FMPProvider:
    name = "fmp"

    def __init__(self, api_key: str, timeout: float = 8.0):
        self._key = api_key
        self._cache = _TTLCache()
        self._client = httpx.AsyncClient(timeout=timeout)

    def _require(self, ticker: str):
        if not is_allowed(ticker):
            raise KeyError(ticker)
        return u_get(ticker)

    async def _get(self, path: str, **params):
        params["apikey"] = self._key
        try:
            r = await self._client.get(f"{_BASE}/{path}", params=params)
            r.raise_for_status()
            return r.json()
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"FMP {path}: {e}") from e

    async def quote(self, ticker: str) -> dict:
        meta = self._require(ticker)
        tk = ticker.upper()
        cached = self._cache.get(("q", tk), ttl=15)
        if cached:
            return cached
        data = await self._get(f"quote/{tk}")
        if not data:
            raise ProviderError(f"no quote for {tk}")
        q = data[0]
        out = {
            "ticker": tk,
            "name": meta["name"],
            "price": q.get("price"),
            "change": q.get("change"),
            "change_pct": q.get("changesPercentage"),
            "currency": "USD",
            "market_cap": q.get("marketCap"),
            "day_high": q.get("dayHigh"),
            "day_low": q.get("dayLow"),
            "volume": q.get("volume"),
            "ts": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "stale": False,
        }
        self._cache.put(("q", tk), out)
        return out

    async def profile(self, ticker: str) -> dict:
        meta = self._require(ticker)
        tk = ticker.upper()
        cached = self._cache.get(("p", tk), ttl=43200)
        if cached:
            return cached
        data = await self._get(f"profile/{tk}")
        p = data[0] if data else {}
        out = {
            "ticker": tk,
            "name": meta["name"],
            "tier": meta["tier"],
            "exchange": p.get("exchangeShortName"),
            "sector": p.get("sector"),
            "industry": p.get("industry"),
            "employees": p.get("fullTimeEmployees"),
            "website": p.get("website"),
            "description": p.get("description"),
        }
        self._cache.put(("p", tk), out)
        return out

    async def financials(self, ticker: str) -> dict:
        self._require(ticker)
        tk = ticker.upper()
        cached = self._cache.get(("f", tk), ttl=43200)
        if cached:
            return cached
        inc = await self._get(f"income-statement/{tk}", period="annual", limit=1)
        bal = await self._get(f"balance-sheet-statement/{tk}", period="annual", limit=1)
        i = inc[0] if inc else {}
        b = bal[0] if bal else {}
        rev = i.get("revenue") or 0
        out = {
            "ticker": tk,
            "revenue_ttm": rev,
            "net_income_ttm": i.get("netIncome"),
            "rd_expense_ttm": i.get("researchAndDevelopmentExpenses"),
            "cash": b.get("cashAndCashEquivalents"),
            "debt": b.get("totalDebt"),
            "gross_margin": round(i.get("grossProfit", 0) / rev, 3) if rev else None,
            "period": i.get("date", "annual"),
            "source": "fmp",
        }
        self._cache.put(("f", tk), out)
        return out

    async def news(self, ticker: str, limit: int = 8) -> list:
        self._require(ticker)
        tk = ticker.upper()
        data = await self._get("stock_news", tickers=tk, limit=limit)
        return [{
            "title": n.get("title"),
            "url": n.get("url"),
            "source": n.get("site"),
            "published": n.get("publishedDate"),
        } for n in (data or [])]

    async def pipeline(self, ticker: str) -> list:
        # FMP has no pipeline data; use ClinicalTrialsProvider for that capability.
        return []
