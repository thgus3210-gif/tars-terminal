"""ClinicalTrials.gov v2 adapter — pipeline capability, no API key required.

Set PIPELINE_PROVIDER=clinicaltrials to activate. Maps a company's sponsored
interventional trials into the pipeline shape. This is the pragmatic keyless
option; for a curated, deduplicated asset-level pipeline (one row per drug,
not per trial) a commercial source like Springer AdisInsight, Citeline, or
Evaluate is the upgrade — same `pipeline()` contract, different fetch.
"""

from __future__ import annotations
import time

import httpx

from ..universe import is_allowed, get as u_get
from .base import ProviderError

_BASE = "https://clinicaltrials.gov/api/v2/studies"
_PHASE_MAP = {
    "EARLY_PHASE1": "Phase 1", "PHASE1": "Phase 1", "PHASE1/PHASE2": "Phase 1/2",
    "PHASE2": "Phase 2", "PHASE2/PHASE3": "Phase 2/3", "PHASE3": "Phase 3",
    "PHASE4": "Phase 4", "NA": "N/A",
}


class ClinicalTrialsProvider:
    name = "clinicaltrials"

    def __init__(self, timeout: float = 10.0):
        self._client = httpx.AsyncClient(timeout=timeout)
        self._cache: dict[str, tuple[float, list]] = {}

    async def pipeline(self, ticker: str) -> list:
        if not is_allowed(ticker):
            raise KeyError(ticker)
        meta = u_get(ticker)
        tk = ticker.upper()

        hit = self._cache.get(tk)
        if hit and time.time() - hit[0] < 21600:  # 6h
            return hit[1]

        # Sponsor names rarely equal the display name; use the company short name.
        sponsor = meta["name"].split(",")[0].split(" Inc")[0].strip()
        params = {
            "query.spons": sponsor,
            "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,NOT_YET_RECRUITING",
            "fields": "protocolSection.identificationModule.briefTitle,"
                      "protocolSection.conditionsModule.conditions,"
                      "protocolSection.designModule.phases,"
                      "protocolSection.statusModule.overallStatus,"
                      "protocolSection.statusModule.lastUpdatePostDateStruct.date,"
                      "protocolSection.armsInterventionsModule.interventions",
            "pageSize": 25,
        }
        try:
            r = await self._client.get(_BASE, params=params)
            r.raise_for_status()
            studies = r.json().get("studies", [])
        except (httpx.HTTPError, ValueError) as e:
            raise ProviderError(f"ClinicalTrials: {e}") from e

        rows = []
        for s in studies:
            ps = s.get("protocolSection", {})
            ident = ps.get("identificationModule", {})
            cond = ps.get("conditionsModule", {}).get("conditions", [])
            phases = ps.get("designModule", {}).get("phases", ["NA"])
            status = ps.get("statusModule", {}).get("overallStatus", "")
            updated = (ps.get("statusModule", {})
                         .get("lastUpdatePostDateStruct", {}).get("date", ""))
            iv = ps.get("armsInterventionsModule", {}).get("interventions", [])
            asset = iv[0]["name"] if iv else ident.get("briefTitle", "")[:40]
            modality = iv[0].get("type", "").title() if iv else "—"
            rows.append({
                "asset": asset,
                "indication": cond[0] if cond else "—",
                "phase": _PHASE_MAP.get(phases[0], phases[0] if phases else "N/A"),
                "modality": modality,
                "status": status.replace("_", " ").title(),
                "updated": updated,
            })

        self._cache[tk] = (time.time(), rows)
        return rows

    # Non-pipeline capabilities delegate to sample so the registry can mix freely.
    async def quote(self, ticker: str) -> dict:
        from .sample import SampleProvider
        return await SampleProvider().quote(ticker)

    async def profile(self, ticker: str) -> dict:
        from .sample import SampleProvider
        return await SampleProvider().profile(ticker)

    async def financials(self, ticker: str) -> dict:
        from .sample import SampleProvider
        return await SampleProvider().financials(ticker)

    async def news(self, ticker: str, limit: int = 8) -> list:
        from .sample import SampleProvider
        return await SampleProvider().news(ticker, limit)
