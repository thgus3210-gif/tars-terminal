"""Free, diverse news/event ingestion — no API keys.

Sources (all keyless):
  * SEC EDGAR full-text search  — recent 8-Ks matching clinical/regulatory
    keywords, mapped to universe tickers by CIK.
  * ClinicalTrials.gov v2        — recently updated studies (results posted).
  * FDA press-release RSS        — approvals, actions, safety.
  * openFDA drugsfda            — recent approval submissions.
  * Trade-press RSS             — FierceBiotech, Endpoints, STAT, GlobeNewswire
    (Clinical Trials) headlines.

Every item is normalized to:
  {source, title, summary, url, published, ticker (or None)}

Ticker resolution: explicit "(NASDAQ: XXX)" / "$XXX" patterns first, then a
name-alias match against the universe. Items that resolve to a universe ticker
AND yield a target/modality via the ontology become read-through events.
"""

from __future__ import annotations
import datetime as dt
import html
import re
import xml.etree.ElementTree as ET

import httpx

from . import universe

UA = {"User-Agent": "TARS-Terminal/1.0 (research; contact@example.com)"}

RSS_FEEDS = [
    ("FDA", "https://www.fda.gov/about-fda/contact-fda/stay-informed/rss-feeds/press-releases/rss.xml"),
    ("FierceBiotech", "https://www.fiercebiotech.com/rss/xml"),
    ("Endpoints", "https://endpts.com/feed/"),
    ("STAT", "https://www.statnews.com/feed/"),
    ("GlobeNewswire-Trials", "https://www.globenewswire.com/RssFeed/subjectcode/29-Clinical%20Trials/feedTitle/GlobeNewswire%20-%20Clinical%20Trials"),
]
EDGAR_FTS = "https://efts.sec.gov/LATEST/search-index"
CT_UPDATED = "https://clinicaltrials.gov/api/v2/studies"

_SUFFIX = re.compile(r"\b(inc|corp|corporation|ltd|plc|co|company|holdings|therapeutics|"
                     r"pharmaceuticals|pharma|biosciences|sciences|nv|sa|ag|as)\b\.?", re.I)


def _clean(s: str) -> str:
    return html.unescape(re.sub(r"<[^>]+>", "", s or "")).strip()


# ---------- ticker resolution ----------
def _alias_index() -> dict[str, str]:
    """Lowercased distinctive company-name core -> ticker. Deliberately does NOT
    include bare ticker symbols (many biotech tickers are English/disease words:
    RARE, VERA, SAGE), which would false-match. Symbols resolve only via the
    explicit (NASDAQ: X) / $X patterns or SEC CIK."""
    idx = {}
    for tk, meta in universe.UNIVERSE.items():
        core = _SUFFIX.sub("", meta["name"]).strip().lower()
        core = re.sub(r"[^a-z0-9 ]", "", core).strip()
        if core and (len(core) >= 6 or " " in core):
            idx.setdefault(core, tk)
    return idx


_ALIAS = None


def resolve_ticker(text: str) -> str | None:
    global _ALIAS
    if _ALIAS is None:
        _ALIAS = _alias_index()
    t = text or ""
    m = re.search(r"\((?:NASDAQ|NYSE|NYSE American|OTC)[:\s]+([A-Z]{1,5})\)", t)
    if m and universe.is_allowed(m.group(1)):
        return m.group(1).upper()
    m = re.search(r"\$([A-Z]{1,5})\b", t)
    if m and universe.is_allowed(m.group(1)):
        return m.group(1).upper()
    low = t.lower()
    # longest alias first to avoid short false hits
    for alias in sorted(_ALIAS, key=len, reverse=True):
        if len(alias) < 4:
            continue
        if re.search(r"\b" + re.escape(alias) + r"\b", low):
            return _ALIAS[alias]
    return None


# ---------- parsers ----------
def _parse_rss(source: str, xml_text: str) -> list[dict]:
    out = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return out
    # RSS <item> and Atom <entry>
    items = root.iter("item")
    ns = {"a": "http://www.w3.org/2005/Atom"}
    entries = list(items) or root.findall(".//a:entry", ns)
    for it in entries:
        def g(tag, atom=None):
            e = it.find(tag)
            if e is None and atom is not None:
                e = it.find(atom, ns)
            return _clean(e.text) if e is not None and e.text else ""
        title = g("title", "a:title")
        if not title:
            continue
        link_e = it.find("link")
        link = (link_e.text if link_e is not None and link_e.text else
                (it.find("a:link", ns).get("href") if it.find("a:link", ns) is not None else ""))
        desc = g("description", "a:summary")
        pub = g("pubDate", "a:updated")
        out.append({"source": source, "title": title, "summary": desc[:300],
                    "url": link or "", "published": pub})
    return out


async def _fetch_rss(client, source, url) -> list[dict]:
    try:
        r = await client.get(url, headers=UA, timeout=20, follow_redirects=True)
        r.raise_for_status()
        return _parse_rss(source, r.text)
    except (httpx.HTTPError, Exception):
        return []


async def _fetch_edgar_8k(client, keywords="clinical OR endpoint OR FDA OR approval") -> list[dict]:
    """Recent 8-Ks matching clinical/regulatory keywords."""
    try:
        params = {"q": keywords, "forms": "8-K", "dateRange": "custom"}
        r = await client.get(EDGAR_FTS, params={"q": '"primary endpoint" OR "FDA" OR "topline"',
                                                "forms": "8-K"}, headers=UA, timeout=20)
        r.raise_for_status()
        hits = r.json().get("hits", {}).get("hits", [])
    except (httpx.HTTPError, ValueError, Exception):
        return []
    out = []
    for h in hits[:40]:
        src = h.get("_source", {})
        ciks = src.get("cik", [])
        ciks = ciks if isinstance(ciks, list) else [ciks]
        # resolve any CIK to a universe ticker
        tk = None
        for c in ciks:
            czf = str(c).zfill(10)
            for utk, meta in universe.UNIVERSE.items():
                if meta.get("cik") == czf:
                    tk = utk
                    break
            if tk:
                break
        display = src.get("display_names", [""])
        name = display[0] if display else ""
        out.append({"source": "SEC 8-K", "title": f"{name}: 8-K filing",
                    "summary": _clean(str(src.get("file_type", ""))),
                    "url": "https://www.sec.gov/cgi-bin/browse-edgar",
                    "published": src.get("file_date", ""), "ticker": tk})
    return out


async def _fetch_ct_updated(client) -> list[dict]:
    since = (dt.date.today() - dt.timedelta(days=7)).isoformat()
    params = {
        "filter.advanced": f"AREA[LastUpdatePostDate]RANGE[{since},MAX]",
        "filter.overallStatus": "COMPLETED,ACTIVE_NOT_RECRUITING,TERMINATED",
        "fields": "protocolSection.identificationModule.briefTitle,"
                  "protocolSection.identificationModule.organization,"
                  "protocolSection.sponsorCollaboratorsModule.leadSponsor,"
                  "protocolSection.designModule.phases,"
                  "protocolSection.statusModule.lastUpdatePostDateStruct",
        "pageSize": 40,
    }
    try:
        r = await client.get(CT_UPDATED, params=params, headers=UA, timeout=20)
        r.raise_for_status()
        studies = r.json().get("studies", [])
    except (httpx.HTTPError, ValueError):
        return []
    out = []
    for s in studies:
        ps = s.get("protocolSection", {})
        spons = ps.get("sponsorCollaboratorsModule", {}).get("leadSponsor", {}).get("name", "")
        title = ps.get("identificationModule", {}).get("briefTitle", "")
        pub = ps.get("statusModule", {}).get("lastUpdatePostDateStruct", {}).get("date", "")
        out.append({"source": "ClinicalTrials.gov", "title": f"{spons}: {title}"[:140],
                    "summary": "", "url": "https://clinicaltrials.gov",
                    "published": pub, "ticker": resolve_ticker(spons)})
    return out


async def ingest_all() -> list[dict]:
    """Fetch every free source, normalize, resolve tickers."""
    async with httpx.AsyncClient() as client:
        results = []
        for source, url in RSS_FEEDS:
            results.append(await _fetch_rss(client, source, url))
        results.append(await _fetch_edgar_8k(client))
        results.append(await _fetch_ct_updated(client))
    items = [it for group in results for it in group]
    for it in items:
        if "ticker" not in it or not it["ticker"]:
            it["ticker"] = resolve_ticker(it["title"]) or resolve_ticker(it.get("summary", ""))
    # de-dupe by (title)
    seen, deduped = set(), []
    for it in items:
        key = it["title"][:80]
        if key in seen:
            continue
        seen.add(key)
        deduped.append(it)
    return deduped


if __name__ == "__main__":
    import asyncio
    items = asyncio.run(ingest_all())
    by_src = {}
    for it in items:
        by_src[it["source"]] = by_src.get(it["source"], 0) + 1
    resolved = [it for it in items if it["ticker"]]
    print(f"ingested {len(items)} items from {len(by_src)} sources: {by_src}")
    print(f"resolved to universe tickers: {len(resolved)}")
    for it in resolved[:12]:
        print(f"  [{it['source']:20}] {it['ticker']:5} {it['title'][:70]}")
