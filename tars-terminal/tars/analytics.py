"""Analytics engine for TARS TERMINAL.

Pure, testable functions over OHLCV arrays (numpy). No network here — the
provider layer supplies price/volume series; these compute the module outputs:
  * RS   : relative-strength line, Mansfield RS, RS Rating percentile
  * TA   : SMA/EMA, RSI, MACD, ATR, Bollinger, Weinstein stage, key levels
  * FLOW : RVOL, OBV, CMF, up/down volume ratio, accumulation grade, composite

Conventions: arrays are 1-D numpy float arrays, oldest first. Daily bars unless
noted. Functions return the full series (same length, NaN-padded at the front)
so the frontend can plot them; scalar summaries are returned separately.
"""

from __future__ import annotations
import numpy as np


# ----------------------------- helpers -----------------------------
def _sma(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    if len(x) >= n:
        c = np.cumsum(np.insert(x, 0, 0.0))
        out[n - 1:] = (c[n:] - c[:-n]) / n
    return out


def _ema(x: np.ndarray, n: int) -> np.ndarray:
    out = np.full_like(x, np.nan, dtype=float)
    if len(x) == 0:
        return out
    k = 2.0 / (n + 1.0)
    # seed with SMA of first n
    if len(x) < n:
        return out
    seed = x[:n].mean()
    out[n - 1] = seed
    for i in range(n, len(x)):
        out[i] = x[i] * k + out[i - 1] * (1 - k)
    return out


def _wilder(x: np.ndarray, n: int) -> np.ndarray:
    """Wilder's smoothing (used by RSI/ATR)."""
    out = np.full_like(x, np.nan, dtype=float)
    if len(x) <= n:
        return out
    out[n] = x[1:n + 1].mean()
    for i in range(n + 1, len(x)):
        out[i] = (out[i - 1] * (n - 1) + x[i]) / n
    return out


# ----------------------------- RS module -----------------------------
def rs_line(close: np.ndarray, bench: np.ndarray) -> np.ndarray:
    """Price/benchmark ratio, indexed to 100 at the first valid point."""
    close, bench = np.asarray(close, float), np.asarray(bench, float)
    ratio = close / bench
    base = ratio[np.isfinite(ratio) & (ratio > 0)][0]
    return ratio / base * 100.0


def mansfield_rs(close: np.ndarray, bench: np.ndarray, window: int = 52) -> np.ndarray:
    """Mansfield RS: % deviation of the RS ratio from its own moving average.
    Cross above 0 = start of relative outperformance. Use weekly bars + 52,
    or daily bars + ~252 for a daily proxy."""
    rs = close / bench
    ma = _sma(rs, window)
    return (rs / ma - 1.0) * 100.0


def weighted_trailing_return(close: np.ndarray) -> float:
    """IBD-style blended return using quarter lookbacks 63/126/189/252 bars,
    weights 0.4/0.2/0.2/0.2. Returns a raw score; percentile-rank across the
    universe to get the 1-99 RS Rating."""
    n = len(close)
    def ret(days):
        return close[-1] / close[-1 - days] - 1.0 if n > days else np.nan
    parts, weights = [ret(63), ret(126), ret(189), ret(252)], [0.4, 0.2, 0.2, 0.2]
    vals = [(w, p) for w, p in zip(weights, parts) if np.isfinite(p)]
    if not vals:
        return np.nan
    wsum = sum(w for w, _ in vals)
    return sum(w * p for w, p in vals) / wsum


def rs_rating(scores: dict[str, float]) -> dict[str, int]:
    """Percentile-rank a {ticker: weighted_return} map into 1-99 ratings."""
    items = [(t, s) for t, s in scores.items() if np.isfinite(s)]
    if not items:
        return {}
    items.sort(key=lambda kv: kv[1])
    n = len(items)
    out = {}
    for i, (t, _) in enumerate(items):
        out[t] = int(round(1 + 98 * (i / (n - 1)))) if n > 1 else 50
    return out


def rs_line_new_high(rs: np.ndarray, lookback: int = 252) -> bool:
    """True if the RS line is at a new high over the lookback — a leadership tell."""
    tail = rs[-lookback:]
    tail = tail[np.isfinite(tail)]
    return len(tail) > 0 and tail[-1] >= tail.max() - 1e-9


# ----------------------------- technicals -----------------------------
def rsi(close: np.ndarray, n: int = 14) -> np.ndarray:
    d = np.diff(close, prepend=close[0])
    gain = _wilder(np.where(d > 0, d, 0.0), n)
    loss = _wilder(np.where(d < 0, -d, 0.0), n)
    rs = np.divide(gain, loss, out=np.full_like(gain, np.nan), where=loss > 0)
    out = 100 - 100 / (1 + rs)
    out[loss == 0] = 100.0
    return out


def macd(close: np.ndarray, fast=12, slow=26, signal=9):
    line = _ema(close, fast) - _ema(close, slow)
    sig = _ema(line[~np.isnan(line)], signal)
    sig_full = np.full_like(close, np.nan, dtype=float)
    valid = np.where(~np.isnan(line))[0]
    if len(valid) >= signal:
        sig_full[valid[0]:][:len(sig)] = sig
    return line, sig_full, line - sig_full


def atr(high, low, close, n: int = 14) -> np.ndarray:
    pc = np.roll(close, 1); pc[0] = close[0]
    tr = np.maximum.reduce([high - low, np.abs(high - pc), np.abs(low - pc)])
    return _wilder(tr, n)


def bollinger(close: np.ndarray, n: int = 20, k: float = 2.0):
    mid = _sma(close, n)
    sd = np.full_like(close, np.nan, dtype=float)
    for i in range(n - 1, len(close)):
        sd[i] = close[i - n + 1:i + 1].std(ddof=0)
    return mid - k * sd, mid, mid + k * sd


def weinstein_stage(close: np.ndarray, weekly: bool = False) -> str:
    """Stage 1 base / 2 advancing / 3 top / 4 declining, via 30-week MA
    (150 daily) slope + price position. Coarse but decision-useful."""
    ma_n = 30 if weekly else 150
    ma = _sma(close, ma_n)
    if np.isnan(ma[-1]) or len(close) < ma_n + 10:
        return "unknown"
    slope = ma[-1] - ma[-11]  # ~10-bar slope
    above = close[-1] > ma[-1]
    rising = slope > 0
    if above and rising:
        return "2 (advancing)"
    if not above and not rising:
        return "4 (declining)"
    if above and not rising:
        return "3 (top)"
    return "1 (basing)"


def key_levels(high, low, close, lookback: int = 252):
    hi = float(np.nanmax(high[-lookback:]))
    lo = float(np.nanmin(low[-lookback:]))
    last = float(close[-1])
    return {
        "hi_52w": hi, "lo_52w": lo,
        "pct_from_hi": round((last / hi - 1) * 100, 1),
        "pct_from_lo": round((last / lo - 1) * 100, 1),
    }


# ----------------------------- supply/demand -----------------------------
def rvol(volume: np.ndarray, n: int = 20) -> float:
    base = _sma(volume, n)[-1]
    return float(volume[-1] / base) if base and np.isfinite(base) else np.nan


def obv(close: np.ndarray, volume: np.ndarray) -> np.ndarray:
    sign = np.sign(np.diff(close, prepend=close[0]))
    return np.cumsum(sign * volume)


def cmf(high, low, close, volume, n: int = 21) -> np.ndarray:
    rng = (high - low)
    mfm = np.divide((close - low) - (high - close), rng,
                    out=np.zeros_like(close, float), where=rng > 0)
    mfv = mfm * volume
    num = _sma(mfv, n) * n
    den = _sma(volume, n) * n
    return np.divide(num, den, out=np.full_like(close, np.nan), where=den > 0)


def up_down_volume_ratio(close: np.ndarray, volume: np.ndarray, n: int = 50) -> float:
    d = np.diff(close, prepend=close[0])[-n:]
    v = volume[-n:]
    up = v[d > 0].sum(); dn = v[d < 0].sum()
    return float(up / dn) if dn > 0 else np.inf


def accumulation_grade(udv: float) -> str:
    """A (heavy accumulation) .. E (heavy distribution), IBD-flavored."""
    if not np.isfinite(udv):
        return "C"
    return "A" if udv >= 1.5 else "B" if udv >= 1.15 else "C" if udv >= 0.85 \
        else "D" if udv >= 0.6 else "E"


def _z(x: float, mu: float, sd: float) -> float:
    return 0.0 if sd == 0 else (x - mu) / sd


def flow_composite(close, high, low, volume,
                   inst_chg_pct: float = 0.0, si_chg_pct: float = 0.0,
                   insider_net: float = 0.0) -> dict:
    """Blend price-derived flow with fundamental supply signals into -100..100.
    inst_chg_pct: QoQ change in institutional shares held (13F).
    si_chg_pct  : change in short interest %float (negative = covering = bullish).
    insider_net : net insider $ (Form 4), positive = buying.
    """
    _rvol = rvol(volume)
    _cmf = cmf(high, low, close, volume)[-1]
    _udv = up_down_volume_ratio(close, volume)
    # map each to a bounded contribution
    c_rvol = np.tanh((_rvol - 1) * 1.2) * 25            # unusual volume
    c_cmf = np.tanh(_cmf * 5) * 25 if np.isfinite(_cmf) else 0   # money flow
    c_udv = np.tanh((_udv - 1)) * 20                    # accumulation
    c_inst = np.tanh(inst_chg_pct / 5) * 15             # 13F change
    c_si = np.tanh(-si_chg_pct / 5) * 10                # short covering
    c_ins = np.tanh(insider_net / 1e6) * 5              # insider buying
    score = float(np.clip(c_rvol + c_cmf + c_udv + c_inst + c_si + c_ins, -100, 100))
    tags = []
    if _rvol >= 1.8: tags.append("거래량 급증")
    if np.isfinite(_cmf) and _cmf > 0.1: tags.append("자금 유입")
    if _udv >= 1.5: tags.append("기관 매집형")
    if si_chg_pct < -1: tags.append("숏 커버링")
    if insider_net > 0: tags.append("내부자 매수")
    return {
        "score": round(score, 1),
        "rvol": round(_rvol, 2) if np.isfinite(_rvol) else None,
        "cmf": round(float(_cmf), 3) if np.isfinite(_cmf) else None,
        "up_down_vol": round(_udv, 2) if np.isfinite(_udv) else None,
        "accumulation": accumulation_grade(_udv),
        "tags": tags,
    }
