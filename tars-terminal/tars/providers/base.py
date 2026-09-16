"""Provider adapter layer — the real-time integration seam.

The terminal never calls a data vendor directly. It calls a `DataProvider`,
and the registry decides which concrete adapter is live based on env config.
Swap `sample` for `fmp` (quotes/financials) + `clinicaltrials` (pipeline)
without touching the API routes or the frontend.

Every provider MUST return data only for tickers in universe.UNIVERSE.
Adapters are responsible for filtering; the router double-checks anyway.

Shape contracts (kept deliberately small and stable):

  quote(ticker) -> {
      ticker, name, price, change, change_pct, currency,
      market_cap, day_high, day_low, volume, ts (iso8601), stale (bool)
  }

  profile(ticker) -> {
      ticker, name, tier, exchange, sector, industry, employees,
      website, description
  }

  financials(ticker) -> {
      ticker, revenue_ttm, net_income_ttm, rd_expense_ttm,
      cash, debt, gross_margin, period, source
  }

  pipeline(ticker) -> [ { asset, indication, phase, modality, status, updated } ]

  news(ticker, limit) -> [ { title, url, source, published } ]
"""

from __future__ import annotations
from typing import Protocol, runtime_checkable
import os


@runtime_checkable
class DataProvider(Protocol):
    name: str

    async def quote(self, ticker: str) -> dict: ...
    async def profile(self, ticker: str) -> dict: ...
    async def financials(self, ticker: str) -> dict: ...
    async def pipeline(self, ticker: str) -> list: ...
    async def news(self, ticker: str, limit: int = 8) -> list: ...


class ProviderError(Exception):
    """Raised by adapters on upstream failure; router maps to 502."""


def build_registry() -> dict[str, DataProvider]:
    """Compose a provider per capability from env.

    QUOTE_PROVIDER    = sample | fmp | finnhub   (default: sample)
    PIPELINE_PROVIDER = sample | clinicaltrials  (default: sample)

    Missing API keys silently fall back to `sample` so the app always boots.
    """
    from .sample import SampleProvider

    sample = SampleProvider()
    reg: dict[str, DataProvider] = {
        "quote": sample,
        "profile": sample,
        "financials": sample,
        "pipeline": sample,
        "news": sample,
    }

    quote_choice = os.getenv("QUOTE_PROVIDER", "sample").lower()
    if quote_choice == "fmp" and os.getenv("FMP_API_KEY"):
        from .fmp import FMPProvider
        fmp = FMPProvider(api_key=os.environ["FMP_API_KEY"])
        reg["quote"] = fmp
        reg["profile"] = fmp
        reg["financials"] = fmp
        reg["news"] = fmp

    pipe_choice = os.getenv("PIPELINE_PROVIDER", "sample").lower()
    if pipe_choice == "clinicaltrials":
        from .clinicaltrials import ClinicalTrialsProvider
        reg["pipeline"] = ClinicalTrialsProvider()

    return reg
