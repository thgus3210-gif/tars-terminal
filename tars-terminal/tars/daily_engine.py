"""Daily read-through engine.

Pipeline:  ingest -> extract(entities) -> classify(outcome) -> peer map -> rank.

Ingest (live, keyless):
  * SEC 8-K atom feeds for universe CIKs (dated material events)
  * ClinicalTrials.gov studies WITH results, recently updated
  (Paid news — Benzinga/Finnhub — plugs into `ingest_news` as another source.)

Extract: ontology-constrained. A controlled target/modality vocabulary with
synonyms is matched against headline+summary. An optional LLM extractor can be
slotted in (set LLM_EXTRACTOR) for messier prose; the ontology still validates
its output so it can't invent targets.

Peer map: the direction matrix from the design, scored by overlap. The pipeline
KB (ticker -> programs) is injected; in production it is populated from
AdisInsight, so read-through covers the whole universe, not just seed names.
"""

from __future__ import annotations
import re

# --------- controlled ontology (extend from AdisInsight in prod) ---------
TARGET_SYNONYMS = {
    "GLP-1": ["glp-1", "glp1", "glucagon-like peptide", "semaglutide", "tirzepatide",
              "orforglipron", "retatrutide", "survodutide"],
    "Lp(a)": ["lp(a)", "lipoprotein(a)", "apo(a)", "olpasiran", "pelacarsen", "lepodisiran"],
    "Amyloid-β": ["amyloid", "abeta", "aβ", "donanemab", "lecanemab", "leqembi"],
    "PD-1": ["pd-1", "pd1", "programmed death-1", "pembrolizumab", "nivolumab"],
    "PD-L1": ["pd-l1", "pdl1", "programmed death-ligand"],
    "KRAS G12C": ["kras g12c", "g12c", "sotorasib", "adagrasib"],
    "BCMA": ["bcma", "b-cell maturation"],
    "TL1A": ["tl1a", "tnfsf15"],
    "IL-23": ["il-23", "il23", "interleukin-23", "risankizumab", "guselkumab"],
    "Factor XIa": ["factor xi", "fxi", "fxia", "milvexian", "asundexian"],
    "FcRn": ["fcrn", "efgartigimod", "rozanolixizumab"],
    "TTR": ["ttr", "transthyretin", "vutrisiran", "patisiran", "tafamidis"],
    "TYK2": ["tyk2", "deucravacitinib"],
    "CFTR": ["cftr", "trikafta", "vanzacaftor"],
}
MODALITY_SYNONYMS = {
    "siRNA": ["sirna", "rnai", "small interfering rna"],
    "ASO": ["antisense", "aso", "oligonucleotide"],
    "mRNA": ["mrna", "messenger rna"],
    "ADC": ["antibody-drug conjugate", "adc"],
    "Bispecific": ["bispecific", "bi-specific", "cd3x"],
    "Cell therapy": ["car-t", "car t", "cell therapy", "til "],
    "Gene therapy": ["gene therapy", "aav", "adeno-associated"],
    "Gene editing": ["crispr", "base editing", "prime editing", "gene editing"],
    "mAb": ["monoclonal antibody", "mab "],
    "Small molecule": ["small molecule", "oral inhibitor"],
    "Peptide": ["peptide"],
    "Radioligand": ["radioligand", "radiopharmaceutical", "psma"],
}

# outcome cues (rule-based; LLM extractor can override with validation)
_POS = ["met primary", "met the primary", "statistically significant", "positive topline",
        "achieved", "superiority", "approval", "approved", "met all"]
_NEG_EFF = ["did not meet", "failed to meet", "missed primary", "not statistically",
            "did not achieve", "misses"]
_NEG_SAF = ["safety signal", "clinical hold", "serious adverse", "death", "toxicity",
            "discontinu", "halt"]


def _match(text: str, syn: dict) -> str | None:
    t = text.lower()
    for canon, keys in syn.items():
        if any(k in t for k in keys):
            return canon
    return None


def classify_outcome(text: str) -> str:
    t = text.lower()
    if any(k in t for k in _NEG_SAF):
        return "fail_safety"
    if any(k in t for k in _NEG_EFF):
        return "fail_efficacy"
    if any(k in t for k in _POS):
        return "success"
    return "mixed"


def extract_event(ticker: str, text: str) -> dict | None:
    """Ontology-constrained extraction from a headline/summary."""
    tgt = _match(text, TARGET_SYNONYMS)
    mod = _match(text, MODALITY_SYNONYMS)
    if not tgt and not mod:
        return None  # nothing actionable for class read-through
    phase = None
    pm = re.search(r"phase\s*(1/2|2/3|1|2|3|4)", text.lower())
    if pm:
        phase = "Phase " + pm.group(1)
    return {
        "ticker": ticker.upper(),
        "target": tgt,
        "modality": mod,
        "phase": phase,
        "outcome": classify_outcome(text),
        "headline": text[:160],
    }


# ------------------------- peer read-through -------------------------
def read_through(event: dict, pipeline_kb: dict) -> list[dict]:
    """Rank universe peers by class overlap + apply the direction matrix.

    pipeline_kb: {ticker: [{a, tgt, mod, ind, ph}, ...]}
    """
    T, M = event.get("target"), event.get("modality")
    outcome = event.get("outcome", "mixed")
    src_ind = None
    # infer source indication from the originating company's matching program
    for p in pipeline_kb.get(event["ticker"], []):
        if p.get("tgt") == T or p.get("mod") == M:
            src_ind = p.get("ind")
            break

    rows = []
    for tk, progs in pipeline_kb.items():
        if tk == event["ticker"]:
            continue
        best = None
        for p in progs:
            sameT = T is not None and p.get("tgt") == T
            sameM = M is not None and p.get("mod") == M
            sameI = src_ind is not None and p.get("ind") == src_ind
            if not sameT and not sameM:
                continue
            overlap = (3 if sameT else 0) + (2 if sameM else 0) + (2 if sameI else 0)
            direction, why = "neu", ""
            if outcome == "success":
                if sameT and sameI:
                    direction, why = "mixed", "타깃 검증(+) & 직접 경쟁(−)"
                elif sameT:
                    direction, why = "pos", "타깃 검증(+)"
                elif sameM:
                    direction, why = "pos", "플랫폼/모달리티 검증(+)"
            elif outcome == "fail_efficacy":
                if sameT:
                    direction, why = "neg", "타깃 리스크(−)"
                else:
                    direction, why = "neu", "영향 제한적"
            elif outcome == "fail_safety":
                if sameM:
                    direction, why, overlap = "neg", "모달리티 안전성 우려(−)", overlap + 1
                elif sameT:
                    direction, why = "neg", "타깃 안전성(−)"
            else:
                why = "경쟁 구도 유지" if sameT else "약한 read-through"
            if not why:
                continue
            cand = {"ticker": tk, "asset": p.get("a"), "target": p.get("tgt"),
                    "modality": p.get("mod"), "phase": p.get("ph"),
                    "overlap": overlap, "direction": direction, "why": why,
                    "same_target": sameT, "same_modality": sameM, "same_indication": sameI}
            if best is None or cand["overlap"] > best["overlap"]:
                best = cand
        if best:
            rows.append(best)
    rows.sort(key=lambda r: r["overlap"], reverse=True)
    return rows


async def daily_feed(pipeline_kb: dict, limit: int = 60) -> dict:
    """Ingest all free sources, extract class events, attach peer read-through.

    Returns {items: [...], read_through: [...], sources: {...}}.
    - items: every normalized headline (with resolved ticker when possible).
    - read_through: the subset that yielded a target/modality AND resolved to a
      universe ticker, each with ranked peer impact.
    """
    from .news_sources import ingest_all
    items = await ingest_all()
    by_src: dict[str, int] = {}
    for it in items:
        by_src[it["source"]] = by_src.get(it["source"], 0) + 1

    read = []
    for it in items:
        tk = it.get("ticker")
        if not tk:
            continue
        ev = extract_event(tk, it["title"] + " " + it.get("summary", ""))
        if not ev or (not ev["target"] and not ev["modality"]):
            continue
        peers = read_through(ev, pipeline_kb)[:8]
        read.append({"event": ev, "source": it["source"], "url": it["url"],
                     "published": it.get("published", ""), "peers": peers})

    return {"items": items[:limit], "read_through": read, "sources": by_src}


if __name__ == "__main__":
    # demo: a real-style headline -> extraction -> peer read-through
    KB = {
        "AMGN": [{"a": "Olpasiran", "tgt": "Lp(a)", "mod": "siRNA", "ind": "Cardiometabolic", "ph": "Phase 3"}],
        "NVS": [{"a": "Pelacarsen", "tgt": "Lp(a)", "mod": "ASO", "ind": "Cardiometabolic", "ph": "Phase 3"}],
        "LLY": [{"a": "Lepodisiran", "tgt": "Lp(a)", "mod": "siRNA", "ind": "Cardiometabolic", "ph": "Phase 2"}],
        "MRNA": [{"a": "mRNA-1010", "tgt": "Spike", "mod": "mRNA", "ind": "Infectious", "ph": "Phase 3"}],
    }
    headline = "Amgen's olpasiran met primary endpoint in Phase 3 Lp(a) cardiovascular trial"
    ev = extract_event("AMGN", headline)
    print("extracted:", ev)
    print("read-through:")
    for r in read_through(ev, KB):
        print(f"  {r['ticker']:5} {r['asset']:14} overlap={r['overlap']} "
              f"{r['direction']:5} {r['why']}")
