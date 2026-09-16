"""TARS TERMINAL — US big pharma / biotech research terminal.

Same mechanism as the reference site:
  login gate  ->  session cookie + CSRF  ->  ?next= redirect  ->  protected terminal

Run:  uvicorn tars.app:app --reload   (from the project's parent dir)
"""

from __future__ import annotations
import os
import re
from urllib.parse import urlparse

from fastapi import FastAPI, Request, Response, Depends, HTTPException
from fastapi.responses import JSONResponse, HTMLResponse, RedirectResponse, FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, field_validator

from . import auth, store, universe
from .providers import build_registry, ProviderError
from .catalysts import catalyst_timeline
from .daily_engine import extract_event, read_through, daily_feed
from .pipeline_kb import PIPELINE_KB

HERE = os.path.dirname(__file__)
STATIC = os.path.join(HERE, "static")

app = FastAPI(title="TARS TERMINAL", docs_url=None, redoc_url=None, openapi_url=None)
PROVIDERS = build_registry()
store.init_db()  # idempotent; also covered by the startup hook below

# Origins allowed to POST. In prod set ALLOWED_ORIGINS=https://your.domain
ALLOWED_ORIGINS = set(
    o.strip() for o in os.getenv("ALLOWED_ORIGINS", "").split(",") if o.strip()
)
_USERNAME_RE = re.compile(r"^[a-zA-Z0-9_]{3,24}$")


@app.on_event("startup")
def _startup():
    store.init_db()


# ----------------------- security headers -----------------------
@app.middleware("http")
async def security_headers(request: Request, call_next):
    resp = await call_next(request)
    resp.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "frame-ancestors 'self'; base-uri 'none'; form-action 'self'"
    )
    resp.headers["X-Content-Type-Options"] = "nosniff"
    resp.headers["X-Frame-Options"] = "SAMEORIGIN"
    resp.headers["Cross-Origin-Resource-Policy"] = "same-origin"
    resp.headers.setdefault("Cache-Control", "no-store")
    return resp


# ----------------------- helpers -----------------------
def current_session(request: Request):
    return auth.read_session(request.cookies.get(auth.SESSION_COOKIE))


def require_member(request: Request) -> str:
    sess = current_session(request)
    if not sess or not store.get_user(sess["username"]):
        raise HTTPException(status_code=401, detail="member_auth_required")
    return sess["username"]


def enforce_write_guard(request: Request):
    """Same-origin + CSRF for any state-changing request."""
    origin = request.headers.get("origin") or request.headers.get("referer")
    if origin:
        host = urlparse(origin).netloc
        allowed_hosts = {urlparse(o).netloc for o in ALLOWED_ORIGINS}
        allowed_hosts.add(request.url.netloc)
        if host not in allowed_hosts:
            raise HTTPException(status_code=403, detail="invalid_origin")
    sess = current_session(request)
    csrf = request.headers.get("x-csrf-token")
    if not auth.csrf_ok(sess, csrf):
        raise HTTPException(status_code=403, detail="csrf_failed")
    return sess["username"]


def _set_session_cookie(resp: Response, cookie_value: str):
    resp.set_cookie(
        auth.SESSION_COOKIE, cookie_value,
        max_age=auth.SESSION_MAX_AGE, httponly=True, samesite="lax",
        secure=os.getenv("SESSION_SECURE", "0") == "1", path="/",
    )


# ----------------------- gate + static pages -----------------------
@app.get("/login", response_class=HTMLResponse)
async def login_page():
    return FileResponse(os.path.join(STATIC, "login.html"))


@app.get("/")
@app.get("/beta")
async def terminal_or_gate(request: Request):
    """Serve the terminal to members; otherwise bounce to the login gate."""
    sess = current_session(request)
    if sess and store.get_user(sess["username"]):
        return FileResponse(os.path.join(STATIC, "terminal.html"))
    next_target = "/beta" if request.url.path == "/beta" else request.url.path
    return RedirectResponse(url=f"/login?next={next_target}", status_code=303)


app.mount("/static", StaticFiles(directory=STATIC), name="static")


# ----------------------- personal auth API -----------------------
class Credentials(BaseModel):
    username: str
    password: str

    @field_validator("username")
    @classmethod
    def _u(cls, v):
        if not _USERNAME_RE.match(v or ""):
            raise ValueError("invalid_username")
        return v

    @field_validator("password")
    @classmethod
    def _p(cls, v):
        if not (4 <= len(v or "") <= 128):
            raise ValueError("invalid_password")
        return v


@app.get("/api/personal/session")
async def session_info(request: Request):
    sess = current_session(request)
    if sess and store.get_user(sess["username"]):
        return {"authenticated": True, "username": sess["username"], "csrf": sess["csrf"]}
    return {"authenticated": False, "username": None, "csrf": None}


@app.post("/api/personal/register")
async def register(request: Request, creds: Credentials):
    # register/login are same-origin only (Origin check, no CSRF yet — no session)
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc not in (
        {request.url.netloc} | {urlparse(o).netloc for o in ALLOWED_ORIGINS}
    ):
        raise HTTPException(status_code=403, detail="invalid_origin")
    if not store.create_user(creds.username, auth.hash_password(creds.password)):
        raise HTTPException(status_code=409, detail="username_taken")
    cookie, _ = auth.issue_session(creds.username)
    resp = JSONResponse({"ok": True, "username": creds.username})
    _set_session_cookie(resp, cookie)
    return resp


@app.post("/api/personal/login")
async def login(request: Request, creds: Credentials):
    origin = request.headers.get("origin")
    if origin and urlparse(origin).netloc not in (
        {request.url.netloc} | {urlparse(o).netloc for o in ALLOWED_ORIGINS}
    ):
        raise HTTPException(status_code=403, detail="invalid_origin")
    user = store.get_user(creds.username)
    if not user or not auth.verify_password(creds.password, user["pw_hash"]):
        # generic message — don't reveal whether the username exists
        raise HTTPException(status_code=401, detail="아이디 또는 비밀번호가 올바르지 않습니다.")
    cookie, _ = auth.issue_session(creds.username)
    resp = JSONResponse({"ok": True, "username": creds.username})
    _set_session_cookie(resp, cookie)
    return resp


@app.post("/api/personal/logout")
async def logout(request: Request):
    resp = JSONResponse({"ok": True})
    resp.delete_cookie(auth.SESSION_COOKIE, path="/")
    return resp


# ----------------------- protected terminal API -----------------------
async def _safe(coro):
    try:
        return await coro
    except KeyError:
        raise HTTPException(status_code=404, detail="not_in_universe")
    except ProviderError as e:
        raise HTTPException(status_code=502, detail=f"provider_error: {e}")


@app.get("/api/beta")
async def beta_ping(user: str = Depends(require_member)):
    return {"ok": True, "user": user, "universe_size": len(universe.UNIVERSE)}


@app.get("/api/companies")
async def companies(q: str = "", limit: int = 300, user: str = Depends(require_member)):
    return {"tiers": universe.TIERS, "results": universe.search(q, limit=limit),
            "total": len(universe.UNIVERSE)}


@app.get("/api/companies/{ticker}")
async def company_detail(ticker: str, user: str = Depends(require_member)):
    if not universe.is_allowed(ticker):
        raise HTTPException(status_code=404, detail="not_in_universe")
    profile = await _safe(PROVIDERS["profile"].profile(ticker))
    quote = await _safe(PROVIDERS["quote"].quote(ticker))
    financials = await _safe(PROVIDERS["financials"].financials(ticker))
    pipeline = await _safe(PROVIDERS["pipeline"].pipeline(ticker))
    news = await _safe(PROVIDERS["news"].news(ticker))
    note = store.get_note(user, ticker)
    return {"profile": profile, "quote": quote, "financials": financials,
            "pipeline": pipeline, "news": news, "note": note}


@app.get("/api/catalysts/{ticker}")
async def catalysts(ticker: str, user: str = Depends(require_member)):
    if not universe.is_allowed(ticker):
        raise HTTPException(status_code=404, detail="not_in_universe")
    meta = universe.get(ticker)
    sponsor = meta["name"].split(",")[0].split(" Inc")[0].strip()
    events = await catalyst_timeline(sponsor, meta.get("cik", ""))
    return {"ticker": ticker.upper(), "catalysts": events,
            "note": "임상 리드아웃은 CT.gov 추정, 8-K는 SEC 확정. PDUFA/AdComm은 유료 캘린더 슬롯."}


@app.get("/api/pipeline/{ticker}")
async def pipeline_kb(ticker: str, user: str = Depends(require_member)):
    if not universe.is_allowed(ticker):
        raise HTTPException(status_code=404, detail="not_in_universe")
    return {"ticker": ticker.upper(),
            "programs": PIPELINE_KB.get(ticker.upper(), []),
            "source": "seed (AdisInsight 연동 예정)"}


class ReadThroughBody(BaseModel):
    ticker: str
    headline: str


@app.post("/api/readthrough")
async def readthrough(body: ReadThroughBody, request: Request):
    """Extract a class event from a headline and map universe peers."""
    require_member(request)  # read-only compute, but members-only
    if not universe.is_allowed(body.ticker):
        raise HTTPException(status_code=400, detail="not_in_universe")
    event = extract_event(body.ticker, body.headline)
    if not event:
        return {"event": None, "peers": [], "note": "온톨로지에서 타깃/모달리티를 찾지 못했습니다."}
    peers = read_through(event, PIPELINE_KB)
    return {"event": event, "peers": peers}


_feed_cache = {"ts": 0.0, "data": None}


@app.get("/api/feed")
async def feed(user: str = Depends(require_member)):
    """Today's aggregated free-source feed + peer read-through. Cached 10 min."""
    import time as _t
    if _feed_cache["data"] and _t.time() - _feed_cache["ts"] < 600:
        return _feed_cache["data"]
    data = await daily_feed(PIPELINE_KB)
    _feed_cache.update(ts=_t.time(), data=data)
    return data


@app.get("/api/quotes")
async def quotes(tickers: str = "", user: str = Depends(require_member)):
    out = []
    for tk in [t for t in tickers.upper().split(",") if universe.is_allowed(t)]:
        try:
            out.append(await PROVIDERS["quote"].quote(tk))
        except (KeyError, ProviderError):
            continue
    return {"quotes": out}


# ---- watchlist ----
class TickerBody(BaseModel):
    ticker: str


@app.get("/api/watchlist")
async def get_watchlist(user: str = Depends(require_member)):
    tickers = store.list_watchlist(user)
    quotes = []
    for tk in tickers:
        try:
            quotes.append(await PROVIDERS["quote"].quote(tk))
        except (KeyError, ProviderError):
            quotes.append({"ticker": tk, "error": True})
    return {"tickers": tickers, "quotes": quotes}


@app.post("/api/watchlist")
async def add_to_watchlist(body: TickerBody, request: Request):
    user = enforce_write_guard(request)
    if not universe.is_allowed(body.ticker):
        raise HTTPException(status_code=400, detail="not_in_universe")
    store.add_watch(user, body.ticker)
    return {"ok": True, "tickers": store.list_watchlist(user)}


@app.delete("/api/watchlist/{ticker}")
async def remove_from_watchlist(ticker: str, request: Request):
    user = enforce_write_guard(request)
    store.remove_watch(user, ticker)
    return {"ok": True, "tickers": store.list_watchlist(user)}


# ---- notes ----
class NoteBody(BaseModel):
    body: str

    @field_validator("body")
    @classmethod
    def _b(cls, v):
        if len(v or "") > 20_000:
            raise ValueError("note_too_long")
        return v


@app.get("/api/notes")
async def all_notes(user: str = Depends(require_member)):
    return {"notes": store.list_notes(user)}


@app.get("/api/notes/{ticker}")
async def get_note(ticker: str, user: str = Depends(require_member)):
    if not universe.is_allowed(ticker):
        raise HTTPException(status_code=404, detail="not_in_universe")
    return {"note": store.get_note(user, ticker)}


@app.put("/api/notes/{ticker}")
async def put_note(ticker: str, body: NoteBody, request: Request):
    user = enforce_write_guard(request)
    if not universe.is_allowed(ticker):
        raise HTTPException(status_code=400, detail="not_in_universe")
    store.upsert_note(user, ticker, body.body)
    return {"ok": True, "note": store.get_note(user, ticker)}
