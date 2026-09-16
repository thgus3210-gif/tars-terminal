# TARS TERMINAL — US Pharma & Biotech research terminal

A member-gated personal research terminal focused **only** on US-listed big
pharma / biotech. Same mechanism as the reference site you analyzed:

```
login gate  ──►  session cookie + CSRF  ──►  ?next= redirect  ──►  protected terminal
```

The whole thing runs with **zero API keys** out of the box (sample data), and
you flip to real-time data by setting two env vars.

---

## Run

```bash
pip install -r requirements.txt
cp .env.example .env          # edit SESSION_SECRET etc.
# from the directory ABOVE this folder (so `tars` is an importable package):
uvicorn tars.app:app --host 0.0.0.0 --port 8000
```

Open `http://localhost:8000/beta` → you're bounced to `/login?next=/beta` →
register → you land in the terminal.

To expose it the same way the reference did:
`cloudflared tunnel --url http://localhost:8000`

---

## Layout

| File | Role |
|---|---|
| `app.py` | FastAPI app: gate, session/CSRF, `next` redirect, protected API, security headers |
| `auth.py` | PBKDF2 password hashing, signed session cookie, CSRF (stdlib crypto only) |
| `store.py` | SQLite: users, watchlist, per-company notes — all scoped per account |
| `universe.py` | **The content boundary** — the curated US pharma/biotech ticker set |
| `providers/base.py` | Provider adapter interface + registry (the real-time seam) |
| `providers/sample.py` | Keyless deterministic placeholder data |
| `providers/fmp.py` | Financial Modeling Prep adapter (quotes/financials/news) |
| `providers/clinicaltrials.py` | ClinicalTrials.gov v2 adapter (pipeline), keyless |
| `static/` | Login gate + terminal SPA (vanilla JS, no build step) |

---

## The one thing that keeps it "pharma/biotech only"

Everything funnels through `universe.py`. Search, watchlist-add, quote,
company detail, and every provider call are filtered against `UNIVERSE`.
An off-universe ticker (e.g. `AAPL`) returns `404 not_in_universe` and can't
be added to a watchlist (`400`). To change coverage, edit that one dict —
nothing else needs to know.

Each entry carries the SEC **CIK**, so you can pull filings/financials from
SEC EDGAR (`https://data.sec.gov/api/xbrl/companyconcept/CIK{cik}/...`)
without any vendor key if you'd rather not pay for FMP.

---

## Real-time data integration (design)

The terminal never calls a vendor directly — it calls a `DataProvider`. The
registry (`build_registry()`) picks the live adapter per **capability** from
env, so you mix sources freely:

```
QUOTE_PROVIDER=fmp   FMP_API_KEY=...        # live quotes / financials / news
PIPELINE_PROVIDER=clinicaltrials            # live trial pipeline, no key
```

Capabilities and suggested sources:

| Capability | Keyless option | Paid / richer option |
|---|---|---|
| `quote` (price, mkt cap) | — | FMP, Finnhub, Polygon, Tiingo, Alpha Vantage |
| `financials` | SEC EDGAR XBRL (by CIK) | FMP, Finnhub |
| `pipeline` | **ClinicalTrials.gov v2** (implemented) | Springer AdisInsight, Citeline Pharmaprojects, Evaluate |
| `news` | — | FMP stock news, Finnhub, Benzinga |
| catalysts (PDUFA/AdComm) | FDA calendars (manual) | BioPharmaCatalyst, Evaluate |

To add a vendor: copy `providers/fmp.py`, change the URLs and the field
mapping so it returns the documented shapes (see the docstrings in
`providers/base.py`), then register it in `build_registry()`. Two rules every
adapter must follow:

1. **Filter to universe first** — never spend a request on an off-universe
   ticker (`is_allowed()` / raise `KeyError`).
2. **Cache with a TTL** — quotes ~10–15s, profile/financials ~12h. A busy
   watchlist otherwise multiplies your vendor bill by the number of rows.

On upstream failure an adapter raises `ProviderError`; the router maps it to
`502` and the watchlist degrades to a per-row `{error:true}` instead of taking
the page down.

> **Pipeline note:** ClinicalTrials.gov gives you *one row per trial*. For a
> clean *one row per drug asset* pipeline (the analyst view), a commercial
> source like AdisInsight is the upgrade — same `pipeline()` contract, you just
> swap the fetch and de-dupe by asset.

---

## Security posture (carried over from the reference, plus fixes)

- Signed **HttpOnly, SameSite=Lax** session cookie; `SESSION_SECURE=1` adds
  `Secure` for HTTPS.
- **CSRF** token bound into the session, required (`X-CSRF-Token`) on every
  mutating request, checked with constant-time compare.
- **Origin/Referer allow-list** on all writes → cross-site POST = `403
  invalid_origin`. Set `ALLOWED_ORIGINS` to your real domain in prod.
- Strict **CSP** (`script-src 'self'`, `base-uri 'none'`, `form-action
  'self'`), `X-Content-Type-Options`, `X-Frame-Options`, `no-store`.
- Passwords hashed with **PBKDF2-SHA256** (240k rounds, per-user salt).
- Login returns a **generic error** — never reveals whether a username exists.
- **Hardened `next` redirect**: the login page only accepts an allow-list of
  in-app paths, closing the open-redirect gap the reference's `next` handling
  left ajar.

### Before you put this in front of real users
- Set a persistent `SESSION_SECRET` (else sessions drop on restart).
- Add rate limiting on `/api/personal/login` and `/register` (e.g. slowapi).
- Put it behind HTTPS and set `SESSION_SECURE=1` + `ALLOWED_ORIGINS`.
- This is a research aid, **not** investment advice; vendor data may be delayed
  — surface that (the UI already flags stale/sample quotes).
