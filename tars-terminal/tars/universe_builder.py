"""Universe builder — the real, self-refreshing content boundary.

Instead of a hardcoded list, the universe is assembled from index holdings:
  * XBI  — SPDR S&P Biotech (equal-weight, small/mid biotech)  via SSGA .xlsx
  * IBB  — iShares Nasdaq Biotech (tracks the NBI index)        via iShares .csv
  * plus a curated set of big pharma + major ADRs the indices under-weight.

Everything is cached to disk (universe_cache.json) so the app boots even if a
source is temporarily down. Refresh on a schedule (weekly is plenty).

Each entry: {ticker, name, tier, sources:[...]}. `tier` is derived:
  big_pharma / adr from the curated map; otherwise 'biotech'.
"""

from __future__ import annotations
import csv
import io
import json
import os
import time

import httpx

try:
    import openpyxl
except ImportError:  # optional; XBI is skipped if missing
    openpyxl = None

UA = {"User-Agent": os.getenv("HTTP_UA", "TARS-Terminal/1.0 (research; contact@example.com)")}
CACHE_PATH = os.path.join(os.path.dirname(__file__), "universe_cache.json")
CACHE_TTL = 60 * 60 * 24 * 7  # 7 days

XBI_URL = ("https://www.ssga.com/library-content/products/fund-data/etfs/us/"
           "holdings-daily-us-en-xbi.xlsx")
IBB_URL = ("https://www.ishares.com/us/products/239699/"
           "ishares-nasdaq-biotechnology-etf/1467271812596.ajax"
           "?fileType=csv&fileName=IBB_holdings&dataType=fund")

# Curated: big pharma + major pharma ADRs (NYSE/NASDAQ) that XBI/IBB miss or
# under-represent. tier is authoritative here.
CURATED = {
    "LLY": ("Eli Lilly", "big_pharma"), "JNJ": ("Johnson & Johnson", "big_pharma"),
    "MRK": ("Merck & Co.", "big_pharma"), "ABBV": ("AbbVie", "big_pharma"),
    "PFE": ("Pfizer", "big_pharma"), "BMY": ("Bristol-Myers Squibb", "big_pharma"),
    "AMGN": ("Amgen", "big_pharma"), "GILD": ("Gilead Sciences", "big_pharma"),
    "NVO": ("Novo Nordisk", "adr"), "AZN": ("AstraZeneca", "adr"),
    "GSK": ("GSK", "adr"), "SNY": ("Sanofi", "adr"), "NVS": ("Novartis", "adr"),
    "TAK": ("Takeda", "adr"), "ARGX": ("argenx", "adr"), "GMAB": ("Genmab", "adr"),
    "BNTX": ("BioNTech", "adr"),
}

# Tickers to drop (tools/diagnostics/non-therapeutics sometimes in XBI/IBB).
_EXCLUDE = {"CASH", "USD", "XTSLA", "MVRXX"}


def _clean_ticker(tk: str) -> str | None:
    tk = (tk or "").strip().upper()
    if not tk or tk in _EXCLUDE:
        return None
    if not tk.isalpha() or len(tk) > 5:  # drop share-class dots, cash lines
        return None
    return tk


def _fetch_xbi() -> dict[str, str]:
    if openpyxl is None:
        return {}
    try:
        r = httpx.get(XBI_URL, headers=UA, timeout=30, follow_redirects=True)
        r.raise_for_status()
        wb = openpyxl.load_workbook(io.BytesIO(r.content), read_only=True, data_only=True)
        rows = [[c.value for c in row] for row in wb.active.iter_rows()]
        hi = next(i for i, row in enumerate(rows)
                  if row and any(str(c).strip() == "Ticker" for c in row if c))
        hdr = [str(c).strip() if c else "" for c in rows[hi]]
        ti, ni = hdr.index("Ticker"), hdr.index("Name")
        out = {}
        for row in rows[hi + 1:]:
            if not row or ti >= len(row):
                continue
            tk = _clean_ticker(str(row[ti]) if row[ti] else "")
            if tk:
                out[tk] = str(row[ni]).strip().title() if ni < len(row) and row[ni] else tk
        return out
    except Exception as e:
        print("[universe] XBI fetch failed:", e)
        return {}


def _fetch_ibb() -> dict[str, str]:
    # iShares occasionally serves an HTML interstitial instead of the CSV.
    # A Referer usually gets the real file; we detect HTML and retry, then skip.
    hdrs = dict(UA, Referer="https://www.ishares.com/us/products/239699/"
                              "ishares-nasdaq-biotechnology-etf",
                Accept="text/csv,application/octet-stream,*/*")
    text = ""
    for attempt in range(3):
        try:
            r = httpx.get(IBB_URL, headers=hdrs, timeout=40, follow_redirects=True)
            r.raise_for_status()
            body = r.content.decode("utf-8-sig", errors="replace")
            if body.lstrip()[:1] != "<" and "Ticker" in body[:5000]:
                text = body
                break
        except Exception as e:
            print(f"[universe] IBB attempt {attempt+1} error:", e)
        time.sleep(1.5)
    if not text:
        print("[universe] IBB unavailable (HTML-gated); using XBI + curated only")
        return {}
    try:
        lines = text.splitlines()
        start = next(i for i, l in enumerate(lines)
                     if l.startswith('"Ticker"') or l.startswith("Ticker,"))
        rdr = csv.reader(lines[start:])
        hdr = next(rdr)
        ti, ni = hdr.index("Ticker"), hdr.index("Name")
        ai = hdr.index("Asset Class") if "Asset Class" in hdr else None
        out = {}
        for row in rdr:
            if ti >= len(row):
                continue
            if ai is not None and ai < len(row) and row[ai].strip() not in ("Equity", ""):
                continue
            tk = _clean_ticker(row[ti])
            if tk:
                out[tk] = row[ni].strip().title() if ni < len(row) else tk
        return out
    except Exception as e:
        print("[universe] IBB fetch failed:", e)
        return {}


def _cik_map() -> dict[str, str]:
    """ticker -> zero-padded CIK, from SEC's public map (keyless)."""
    try:
        r = httpx.get("https://www.sec.gov/files/company_tickers.json",
                      headers=UA, timeout=30)
        r.raise_for_status()
        data = r.json()
        return {row["ticker"].upper(): str(row["cik_str"]).zfill(10)
                for row in data.values()}
    except Exception as e:
        print("[universe] CIK map failed:", e)
        return {}


def build(force: bool = False) -> dict:
    """Return {ticker: {name, tier, cik, sources}}. Cached to disk."""
    if not force and os.path.exists(CACHE_PATH):
        if time.time() - os.path.getmtime(CACHE_PATH) < CACHE_TTL:
            try:
                with open(CACHE_PATH) as f:
                    return json.load(f)
            except Exception:
                pass

    xbi, ibb = _fetch_xbi(), _fetch_ibb()
    uni: dict[str, dict] = {}

    def add(tk, name, tier, source):
        e = uni.setdefault(tk, {"name": name, "tier": tier, "sources": []})
        if source not in e["sources"]:
            e["sources"].append(source)
        # curated tier wins; better name if we had a placeholder
        if tier in ("big_pharma", "adr"):
            e["tier"] = tier
        if name and (not e["name"] or e["name"] == tk):
            e["name"] = name

    for tk, name in xbi.items():
        add(tk, name, "biotech", "XBI")
    for tk, name in ibb.items():
        add(tk, name, "biotech", "IBB")
    for tk, (name, tier) in CURATED.items():
        add(tk, name, tier, "curated")

    ciks = _cik_map()
    for tk, meta in uni.items():
        meta["cik"] = ciks.get(tk, "")

    result = dict(sorted(uni.items()))
    if result:
        try:
            with open(CACHE_PATH, "w") as f:
                json.dump(result, f, ensure_ascii=False)
        except Exception as e:
            print("[universe] cache write failed:", e)
    elif os.path.exists(CACHE_PATH):  # all sources down -> keep last good
        with open(CACHE_PATH) as f:
            return json.load(f)
    return result


if __name__ == "__main__":
    u = build(force=True)
    tiers = {}
    for meta in u.values():
        tiers[meta["tier"]] = tiers.get(meta["tier"], 0) + 1
    print(f"universe size: {len(u)}  by tier: {tiers}")
    print("sample:", list(u.items())[:5])
