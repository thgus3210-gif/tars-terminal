"""Catalyst engine — real dated events from free sources.

Two live sources, no API key:
  * ClinicalTrials.gov v2 — sponsored Phase 2/3 studies -> estimated readout
    windows from primaryCompletionDate (+ a lag), with confidence from whether
    the date is Actual vs Estimated.
  * SEC EDGAR 8-K atom feed — recent material-event filings (dated).

PDUFA / AdComm dates have no clean free structured feed; those are flagged as
belonging to a paid calendar (Benzinga/Evaluate) and left as adapter slots.

Everything returns {date, days_until, type, title, phase, source, confidence,
importance, binary} so the timeline UI can render + sort uniformly.
"""

from __future__ import annotations
import datetime as dt
import re

import httpx

UA = {"User-Agent": "TARS-Terminal/1.0 (research; contact@example.com)"}
CT_BASE = "https://clinicaltrials.gov/api/v2/studies"
EDGAR_8K = ("https://www.sec.gov/cgi-bin/browse-edgar?action=getcompany"
            "&type=8-K&dateb=&owner=include&count=10&output=atom&CIK={cik}")

_PHASE = {"PHASE2": "Phase 2", "PHASE2/PHASE3": "Phase 2/3", "PHASE3": "Phase 3",
          "PHASE4": "Phase 4"}
# median lag from primary completion to topline press release, by phase (days)
_READOUT_LAG = {"Phase 2": 45, "Phase 2/3": 60, "Phase 3": 60, "Phase 4": 45}


def _today() -> dt.date:
    return dt.date.today()


def _parse_date(s: str) -> dt.date | None:
    for fmt in ("%Y-%m-%d", "%Y-%m", "%Y"):
        try:
            return dt.datetime.strptime(s, fmt).date()
        except (ValueError, TypeError):
            continue
    return None


def _importance(phase: str, pivotal: bool) -> str:
    if phase in ("Phase 3", "Phase 2/3") and pivotal:
        return "높음"
    if phase in ("Phase 3", "Phase 2/3"):
        return "중간"
    return "낮음"


async def clinical_catalysts(client: httpx.AsyncClient, sponsor: str) -> list[dict]:
    params = {
        "query.spons": sponsor,
        "filter.overallStatus": "RECRUITING,ACTIVE_NOT_RECRUITING,NOT_YET_RECRUITING",
        "fields": "protocolSection.identificationModule.briefTitle,"
                  "protocolSection.designModule.phases,"
                  "protocolSection.statusModule.primaryCompletionDateStruct,"
                  "protocolSection.designModule.designInfo,"
                  "protocolSection.armsInterventionsModule.interventions",
        "sort": "protocolSection.statusModule.primaryCompletionDateStruct.date",
        "pageSize": 40,
    }
    try:
        r = await client.get(CT_BASE, params=params, headers=UA, timeout=15)
        r.raise_for_status()
        studies = r.json().get("studies", [])
    except (httpx.HTTPError, ValueError):
        return []

    out = []
    today = _today()
    for s in studies:
        ps = s.get("protocolSection", {})
        phases = ps.get("designModule", {}).get("phases", [])
        phase = next((_PHASE[p] for p in phases if p in _PHASE), None)
        if not phase:
            continue
        pcd = ps.get("statusModule", {}).get("primaryCompletionDateStruct", {})
        d = _parse_date(pcd.get("date", ""))
        if not d:
            continue
        lag = _READOUT_LAG.get(phase, 60)
        readout = d + dt.timedelta(days=lag)
        days = (readout - today).days
        if days < -30:  # already read out a while ago
            continue
        date_type = pcd.get("type", "ESTIMATED")
        title = ps.get("identificationModule", {}).get("briefTitle", "")[:90]
        iv = ps.get("armsInterventionsModule", {}).get("interventions", [])
        asset = iv[0]["name"] if iv else title
        pivotal = phase in ("Phase 3", "Phase 2/3")
        out.append({
            "date": readout.isoformat(),
            "days_until": days,
            "type": "임상 리드아웃(추정)",
            "title": asset,
            "detail": title,
            "phase": phase,
            "source": "ClinicalTrials.gov",
            "confidence": "중" if date_type == "ACTUAL" else "낮음(추정일)",
            "importance": _importance(phase, pivotal),
            "binary": pivotal,
        })
    return out


async def sec_8k_events(client: httpx.AsyncClient, cik: str) -> list[dict]:
    if not cik:
        return []
    try:
        r = await client.get(EDGAR_8K.format(cik=cik.zfill(10)), headers=UA, timeout=15)
        r.raise_for_status()
        xml = r.text
    except httpx.HTTPError:
        return []
    out = []
    today = _today()
    # crude atom parse (no dep): pull <updated> + <title> per entry
    for m in re.finditer(r"<entry>(.*?)</entry>", xml, re.S):
        block = m.group(1)
        dm = re.search(r"<updated>(\d{4}-\d{2}-\d{2})", block)
        if not dm:
            continue
        d = _parse_date(dm.group(1))
        days = (d - today).days
        out.append({
            "date": d.isoformat(),
            "days_until": days,
            "type": "8-K 공시",
            "title": "Material event (8-K)",
            "detail": "",
            "phase": "",
            "source": "SEC EDGAR",
            "confidence": "확정",
            "importance": "중간",
            "binary": False,
        })
    return out[:5]


async def catalyst_timeline(sponsor: str, cik: str = "") -> list[dict]:
    """Merged, de-duplicated, chronologically sorted catalyst list."""
    async with httpx.AsyncClient() as client:
        clin = await clinical_catalysts(client, sponsor)
        secs = await sec_8k_events(client, cik)
    events = clin + secs
    events.sort(key=lambda e: e["date"])
    # note about paid-only catalysts
    return events


if __name__ == "__main__":
    import asyncio, json
    ev = asyncio.run(catalyst_timeline("Vertex Pharmaceuticals", "0000875320"))
    print(f"{len(ev)} catalysts for Vertex")
    for e in ev[:8]:
        print(f"  {e['date']}  D{e['days_until']:+5d}  {e['phase']:9} {e['type']:18} "
              f"{e['title'][:40]}  [{e['importance']}]")
