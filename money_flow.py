#!/usr/bin/env python3
"""
Cross-asset "money flow" snapshot: SPY/ES futures, US 10Y yield, DXY, Gold, Bitcoin.

Meant to run on GitHub Actions (or any machine with normal internet access) --
NOT inside a locked-down sandbox with a network allowlist.

Writes two files to the repo each run:
    latest.txt   - plain-text report (unchanged format from before)
    index.html   - self-contained visual snapshot (3H / 3D / 30D bars per
                   asset + a plain-English flow summary), so the repo always
                   has an up-to-date visual you can open directly or serve
                   via GitHub Pages -- no external tooling required to view it.

Env vars (all optional):
    NTFY_TOPIC   - if set, posts the report to https://ntfy.sh/<topic> as a push notification.
                   Subscribe to the same topic in the ntfy app (iOS/Android) or at ntfy.sh/<topic>.
"""

import os
import sys
import html
import json
import urllib.request
from collections import Counter
from datetime import datetime, timezone

try:
    import yfinance as yf
except ImportError:
    sys.exit("Missing dependency. Run: pip install yfinance")

ASSETS = [
    ("ES=F", "S&P 500 futures (ES=F)", "S&P 500 futures"),
    ("NQ=F", "Nasdaq 100 futures (NQ=F)", "Nasdaq 100 futures"),
    ("ZN=F", "10-Year T-Note futures (ZN=F)", "10-Year T-Note futures"),
    ("DX-Y.NYB", "US Dollar Index (DXY)", "US Dollar Index"),
    ("GC=F", "Gold futures (GC=F)", "Gold futures"),
    ("CL=F", "WTI Crude Oil futures (CL=F)", "Crude Oil futures"),
    ("BTC-USD", "Bitcoin (BTC-USD)", "Bitcoin"),
]

# "since previous close" ladder -- used for the headline statement.
THRESHOLDS = {
    "ES=F":     [(0.1, "Flat"), (0.3, "Mild"), (0.8, "Medium"), (float("inf"), "Heavy")],
    "NQ=F":     [(0.15, "Flat"), (0.4, "Mild"), (1.0, "Medium"), (float("inf"), "Heavy")],
    "DX-Y.NYB": [(0.1, "Flat"), (0.2, "Mild"), (0.5, "Medium"), (float("inf"), "Heavy")],
    "GC=F":     [(0.2, "Flat"), (0.5, "Mild"), (1.5, "Medium"), (float("inf"), "Heavy")],
    "CL=F":     [(0.3, "Flat"), (1.0, "Mild"), (2.5, "Medium"), (float("inf"), "Heavy")],
    "BTC-USD":  [(0.5, "Flat"), (1.5, "Mild"), (3.0, "Medium"), (float("inf"), "Heavy")],
    "ZN=F":     [(0.1, "Flat"), (0.25, "Mild"), (0.6, "Medium"), (float("inf"), "Heavy")],
}

# ~3h ladder (15m bars, 12 back) -- tighter than the "since previous close" one.
THRESHOLDS_3H = {
    "ES=F":     [(0.05, "Flat"), (0.15, "Mild"), (0.4, "Medium"), (float("inf"), "Heavy")],
    "NQ=F":     [(0.08, "Flat"), (0.2, "Mild"), (0.5, "Medium"), (float("inf"), "Heavy")],
    "DX-Y.NYB": [(0.05, "Flat"), (0.12, "Mild"), (0.3, "Medium"), (float("inf"), "Heavy")],
    "GC=F":     [(0.1, "Flat"), (0.3, "Mild"), (0.8, "Medium"), (float("inf"), "Heavy")],
    "CL=F":     [(0.15, "Flat"), (0.4, "Mild"), (1.0, "Medium"), (float("inf"), "Heavy")],
    "BTC-USD":  [(0.3, "Flat"), (0.8, "Mild"), (1.8, "Medium"), (float("inf"), "Heavy")],
    "ZN=F":     [(0.05, "Flat"), (0.12, "Mild"), (0.3, "Medium"), (float("inf"), "Heavy")],
}

# 3-day ladder -- roughly 2-3x the 3h ladder above.
THRESHOLDS_3D = {
    "ES=F":     [(0.3, "Flat"), (0.8, "Mild"), (2.0, "Medium"), (float("inf"), "Heavy")],
    "NQ=F":     [(0.4, "Flat"), (1.0, "Mild"), (2.5, "Medium"), (float("inf"), "Heavy")],
    "DX-Y.NYB": [(0.2, "Flat"), (0.5, "Mild"), (1.2, "Medium"), (float("inf"), "Heavy")],
    "GC=F":     [(0.4, "Flat"), (1.0, "Mild"), (2.5, "Medium"), (float("inf"), "Heavy")],
    "CL=F":     [(0.6, "Flat"), (1.5, "Mild"), (3.5, "Medium"), (float("inf"), "Heavy")],
    "BTC-USD":  [(1.0, "Flat"), (3.0, "Mild"), (6.0, "Medium"), (float("inf"), "Heavy")],
    "ZN=F":     [(0.2, "Flat"), (0.5, "Mild"), (1.0, "Medium"), (float("inf"), "Heavy")],
}

# 30-day ladder -- much larger cumulative moves expected.
THRESHOLDS_30D = {
    "ES=F":     [(1.0, "Flat"), (3.0, "Mild"), (7.0, "Medium"), (float("inf"), "Heavy")],
    "NQ=F":     [(1.5, "Flat"), (4.0, "Mild"), (9.0, "Medium"), (float("inf"), "Heavy")],
    "DX-Y.NYB": [(0.7, "Flat"), (2.0, "Mild"), (4.5, "Medium"), (float("inf"), "Heavy")],
    "GC=F":     [(1.5, "Flat"), (4.0, "Mild"), (9.0, "Medium"), (float("inf"), "Heavy")],
    "CL=F":     [(2.0, "Flat"), (6.0, "Mild"), (12.0, "Medium"), (float("inf"), "Heavy")],
    "BTC-USD":  [(4.0, "Flat"), (10.0, "Mild"), (20.0, "Medium"), (float("inf"), "Heavy")],
    "ZN=F":     [(0.7, "Flat"), (1.5, "Mild"), (3.0, "Medium"), (float("inf"), "Heavy")],
}

# (flow target name, word when money flows IN, word when money flows OUT).
# Every asset here -- including ZN=F -- is a priced instrument, so price up
# always means money flowing IN and price down always means money flowing
# OUT; no direction inversion needed (that was only true for the old ^TNX
# yield entry, which this replaced).
FLOW_WORDS = {
    "ES=F":     ("equities", "into", "out of"),
    "NQ=F":     ("tech/Nasdaq equities", "into", "out of"),
    "DX-Y.NYB": ("the dollar", "into", "out of"),
    "GC=F":     ("gold", "into", "out of"),
    "CL=F":     ("crude oil", "into", "out of"),
    "BTC-USD":  ("BTC", "into", "out of"),
    "ZN=F":     ("Treasury notes", "into", "out of"),
}

TF_ORDER = ["3h", "3d", "30d"]
TF_LABELS_SHORT = {"3h": "3 hours", "3d": "3 days", "30d": "30 days"}
TF_COL_LABELS = {"3h": "3H", "3d": "3D", "30d": "30D"}
MAG_TO_WIDTH = {"Flat": 0, "Mild": 34, "Medium": 62, "Heavy": 90}


def magnitude(abs_move, ladder):
    for cutoff, label in ladder:
        if abs_move < cutoff:
            return label
    return ladder[-1][1]


def fetch_intraday(ticker, interval="15m", period="1d"):
    try:
        hist = yf.Ticker(ticker).history(period=period, interval=interval)
        return hist if len(hist) else None
    except Exception as e:
        print(f"  [warn] intraday fetch failed for {ticker}: {e}", file=sys.stderr)
        return None


def fetch_daily(ticker, period="90d"):
    """Daily bars, far enough back to safely index 3 and 30 sessions ago for
    every asset in ASSETS -- including BTC, which trades every calendar day."""
    try:
        hist = yf.Ticker(ticker).history(period=period, interval="1d")
        return hist if len(hist) else None
    except Exception as e:
        print(f"  [warn] daily fetch failed for {ticker}: {e}", file=sys.stderr)
        return None


HOURLY_CANDLE_HOURS = 300


def fetch_hourly_ohlc(ticker, hours=HOURLY_CANDLE_HOURS, period="90d"):
    """1h-interval OHLC bars for `ticker` (oldest -> newest), or None if
    unavailable. If `hours` is an int, returns only the last `hours` bars
    (period="90d" comfortably covers 300 hourly bars even for assets that
    only trade ~6.5h/day on weekdays, since 90 calendar days is
    ~64 trading days * 6.5h =~ 416h of coverage). If `hours` is None, returns
    every hourly bar Yahoo has within `period` with no additional cap -- used
    for "last N calendar days" windows where the bar count legitimately
    varies by instrument (a 24h/day future vs. a 6.5h/day equity session)."""
    try:
        hist = yf.Ticker(ticker).history(period=period, interval="60m")
        if hist is None or hist.empty:
            return None
        hist = hist.dropna(subset=["Open", "High", "Low", "Close"])
        if hist.empty:
            return None
        tail = hist if hours is None else hist.tail(hours)
        out = []
        for r in tail.itertuples():
            ts = r.Index
            try:
                ts = ts.tz_convert("UTC") if ts.tzinfo is not None else ts.tz_localize("UTC")
            except Exception:
                pass
            out.append({
                "open": float(r.Open), "high": float(r.High), "low": float(r.Low), "close": float(r.Close),
                "ts": ts,
            })
        return out
    except Exception as e:
        print(f"  [warn] hourly OHLC fetch failed for {ticker}: {e}", file=sys.stderr)
        return None


# --------------------------------------------------------------------------
# Futures watchlist -- full board snapshot + hourly bar chart per symbol
# --------------------------------------------------------------------------

# (ticker, display name, category) -- the full futures board Yahoo Finance
# lists under Markets -> Commodities/Futures (finance.yahoo.com/markets/commodities/),
# not just the index/treasury/metals subset visible in a single watchlist screenshot.
FUTURES = [
    # -- Equity index --
    ("ES=F", "E-Mini S&P 500", "Equity Index"),
    ("YM=F", "Mini Dow Jones", "Equity Index"),
    ("NQ=F", "Nasdaq 100", "Equity Index"),
    ("RTY=F", "E-mini Russell 2000", "Equity Index"),
    # -- Treasuries --
    ("ZB=F", "US Treasury Bond", "Treasuries"),
    ("ZN=F", "10-Year T-Note", "Treasuries"),
    ("ZF=F", "5-Year T-Note", "Treasuries"),
    ("ZT=F", "2-Year T-Note", "Treasuries"),
    # -- Metals --
    ("GC=F", "Gold", "Metals"),
    ("MGC=F", "Micro Gold", "Metals"),
    ("SI=F", "Silver", "Metals"),
    ("SIL=F", "Micro Silver", "Metals"),
    ("PL=F", "Platinum", "Metals"),
    ("PA=F", "Palladium", "Metals"),
    ("HG=F", "Copper", "Metals"),
    # -- Energy --
    ("CL=F", "Crude Oil", "Energy"),
    ("HO=F", "Heating Oil", "Energy"),
    ("NG=F", "Natural Gas", "Energy"),
    ("RB=F", "RBOB Gasoline", "Energy"),
    ("BZ=F", "Brent Crude Oil", "Energy"),
    ("B0=F", "Mont Belvieu Propane", "Energy"),
    # -- Grains / agriculture --
    ("ZC=F", "Corn", "Agriculture"),
    ("ZO=F", "Oats", "Agriculture"),
    ("KE=F", "KC HRW Wheat", "Agriculture"),
    ("ZR=F", "Rough Rice", "Agriculture"),
    ("ZM=F", "Soybean Meal", "Agriculture"),
    ("ZL=F", "Soybean Oil", "Agriculture"),
    ("ZS=F", "Soybean", "Agriculture"),
    # -- Livestock --
    ("GF=F", "Feeder Cattle", "Livestock"),
    ("HE=F", "Lean Hogs", "Livestock"),
    ("LE=F", "Live Cattle", "Livestock"),
    # -- Softs --
    ("CC=F", "Cocoa", "Softs"),
    ("KC=F", "Coffee", "Softs"),
    ("CT=F", "Cotton", "Softs"),
    ("LBS=F", "Lumber", "Softs"),
    ("OJ=F", "Orange Juice", "Softs"),
    ("SB=F", "Sugar", "Softs"),
]

FUTURES_CATEGORY_ORDER = ["Equity Index", "Treasuries", "Metals", "Energy", "Agriculture", "Livestock", "Softs"]

# Calendar-day lookback for the futures watchlist candlestick charts. Actual
# hourly bar count per symbol varies with its trading calendar -- CME futures
# trade ~23h/day, 5 days/week (roughly 450-500 hourly bars in 30 days), while
# an underlying that only has RTH data would show fewer.
FUTURES_WINDOW_DAYS = 30

# Generic magnitude ladder for the 3h flow blurb -- one ladder across every
# futures symbol (unlike the per-asset-tuned ladders above) since we're
# summarizing ~35 instruments at once, not tracking a handful precisely.
FUTURES_3H_LADDER = [(0.1, "Flat"), (0.3, "Mild"), (0.8, "Medium"), (float("inf"), "Heavy")]

SPARK_BLOCKS = "▁▂▃▄▅▆▇█"  # ▁..█

# --------------------------------------------------------------------------
# Hourly RSI trendline + end bubble (Futures watchlist) and the Equilibrium
# page's live seed values -- both derived from the same Wilder RSI series.
# --------------------------------------------------------------------------

RSI_PERIOD = 14

# End-of-line bubble sizing: radius is the INVERSE of the last-3-hourly-candle
# % price change, so a quiet/consolidating instrument gets a bigger bubble and
# a big recent mover gets a small one. radius = clamp(K / (abs(pct) + EPS)).
RSI_BUBBLE_MIN_R = 3.0
RSI_BUBBLE_MAX_R = 14.0
RSI_BUBBLE_K = 3.0
RSI_BUBBLE_EPS = 0.05

# (ticker, display name) for the Equilibrium -- RSI Reversion page, in the
# exact order its ASSETS array expects. This is the same 6 non-crypto tickers
# already pulled for the main cross-asset snapshot above (ASSETS), just
# relabeled to match the page's short names.
EQUILIBRIUM_TICKERS = [
    ("DX-Y.NYB", "DXY"),
    ("ZN=F", "BONDS"),
    ("ES=F", "SPY"),
    ("NQ=F", "NASDAQ"),
    ("GC=F", "GOLD"),
    ("CL=F", "WTI CRUDE"),
]


def rsi_series(closes, period=RSI_PERIOD):
    """Wilder's RSI computed over a list of closes (oldest -> newest).
    Returns a list the same length as `closes`: None for every index before
    the first full `period`-bar window, then the RSI value (0-100) from that
    point on. Needs at least period+1 closes to produce any real values."""
    n = len(closes)
    out = [None] * n
    if n < period + 1:
        return out
    gains = [0.0] * n
    losses = [0.0] * n
    for i in range(1, n):
        delta = closes[i] - closes[i - 1]
        gains[i] = max(delta, 0.0)
        losses[i] = max(-delta, 0.0)
    avg_gain = sum(gains[1:period + 1]) / period
    avg_loss = sum(losses[1:period + 1]) / period

    def rsi_from(avg_g, avg_l):
        if avg_l == 0:
            return 100.0 if avg_g > 0 else 50.0
        rs = avg_g / avg_l
        return 100.0 - (100.0 / (1.0 + rs))

    out[period] = rsi_from(avg_gain, avg_loss)
    for i in range(period + 1, n):
        avg_gain = (avg_gain * (period - 1) + gains[i]) / period
        avg_loss = (avg_loss * (period - 1) + losses[i]) / period
        out[i] = rsi_from(avg_gain, avg_loss)
    return out


def bubble_radius_from_pct(pct):
    """Absolute/independent sizing: smaller |pct| (quiet) -> bigger bubble.
    Two tickers with the same |pct| always get the same radius, regardless
    of what the rest of the board is doing this run. Kept as a per-ticker
    fallback for compute_relative_bubble_radii() below when there isn't
    enough of a board to normalize against."""
    if pct is None:
        return RSI_BUBBLE_MIN_R
    r = RSI_BUBBLE_K / (abs(pct) + RSI_BUBBLE_EPS)
    return max(RSI_BUBBLE_MIN_R, min(RSI_BUBBLE_MAX_R, r))


def compute_relative_bubble_radii_from_pcts(abs_pct_by_key):
    """Shared core: given {key: abs(3h % change)}, min-max normalize across
    every key and invert it, so the single quietest key this run always gets
    RSI_BUBBLE_MAX_R and the single most volatile always gets
    RSI_BUBBLE_MIN_R, with everyone else spread linearly in between. This
    guarantees the set always shows a full range of bubble sizes instead of
    clustering at the clamps (which the fixed per-key formula could do on an
    especially quiet or especially volatile day). Falls back to the
    independent per-key formula when there are fewer than 2 keys to
    normalize against."""
    if len(abs_pct_by_key) < 2:
        return {k: bubble_radius_from_pct(v) for k, v in abs_pct_by_key.items()}

    lo, hi = min(abs_pct_by_key.values()), max(abs_pct_by_key.values())
    span = hi - lo
    radii = {}
    for key, pct in abs_pct_by_key.items():
        frac_volatile = 0.5 if span == 0 else (pct - lo) / span  # 0=quietest, 1=most volatile
        frac_quiet = 1.0 - frac_volatile
        radii[key] = RSI_BUBBLE_MIN_R + frac_quiet * (RSI_BUBBLE_MAX_R - RSI_BUBBLE_MIN_R)
    return radii


def compute_relative_bubble_radii(futures):
    """Size each futures instrument's end-bubble relative to the rest of the
    futures board this run (see compute_relative_bubble_radii_from_pcts).
    Returns {ticker: radius}; tickers without a usable 3h reading are left
    out (caller should default those to RSI_BUBBLE_MIN_R)."""
    pct_by_ticker = {
        f["ticker"]: abs(f["flow_3h"]["pct"])
        for f in futures
        if not f.get("unavailable") and f.get("flow_3h")
    }
    return compute_relative_bubble_radii_from_pcts(pct_by_ticker)


# Continuous red -> gray -> green gradient across x in [-1, 1], matching the
# Equilibrium page's color language (red = oversold/left, green =
# overbought/right).
_EQ_STOP_NEG = (255, 92, 92)
_EQ_STOP_MID = (156, 163, 175)
_EQ_STOP_POS = (62, 207, 142)


def equilibrium_color_for_x(x):
    if x <= 0:
        a, b, t = _EQ_STOP_NEG, _EQ_STOP_MID, x + 1
    else:
        a, b, t = _EQ_STOP_MID, _EQ_STOP_POS, x
    r = round(a[0] + (b[0] - a[0]) * t)
    g = round(a[1] + (b[1] - a[1]) * t)
    bl = round(a[2] + (b[2] - a[2]) * t)
    return f"rgb({r},{g},{bl})"


def rsi_zone_color(rsi):
    if rsi is None:
        return "var(--text-muted)"
    if rsi >= 70:
        return "var(--div-out)"
    if rsi <= 30:
        return "var(--div-in)"
    return "var(--text-secondary)"


def render_rsi_trend_svg(rsi_values, bubble_radius, ohlc=None, width=680, height=70, n_ticks=6):
    """Inline SVG line chart of an hourly RSI series (oldest -> newest),
    0-100 on the y-axis with dashed guides at 30/50/70, plus a circle at the
    line's last point sized by `bubble_radius`.

    `ohlc` (optional) is the same-length, same-order list of hourly bars the
    closes/rsi_values were derived from (each carrying a "ts" timestamp) --
    when given, a date/time axis is drawn under the line, labeled the same
    way render_candlestick_svg labels its x-axis, so the two charts read
    together."""
    AXIS_H = 22 if ohlc else 0
    pad_top, pad_bottom = 6.0, 6.0
    draw_h = height - pad_top - pad_bottom
    total_height = height + AXIS_H
    valid = [(i, v) for i, v in enumerate(rsi_values) if v is not None]
    if len(valid) < 2:
        return (
            f'<svg viewBox="0 0 {width} {total_height}" role="img" '
            f'aria-label="RSI trend unavailable"></svg>'
        )
    first_idx = valid[0][0]
    last_idx = valid[-1][0]
    span_i = max(1, last_idx - first_idx)

    def xy(i, v):
        x = (i - first_idx) / span_i * width
        y = pad_top + (1 - v / 100.0) * draw_h
        return x, y

    def y_of(v):
        return pad_top + (1 - v / 100.0) * draw_h

    pts = [xy(i, v) for i, v in valid]
    path = "M " + " L ".join(f"{x:.2f},{y:.2f}" for x, y in pts)
    last_x, last_y = pts[-1]
    last_rsi = valid[-1][1]
    color = rsi_zone_color(last_rsi)

    guides = []
    for level, dash in ((70, "3,3"), (50, "1,4"), (30, "3,3")):
        gy = y_of(level)
        guides.append(
            f'<line x1="0" y1="{gy:.2f}" x2="{width}" y2="{gy:.2f}" '
            f'stroke="var(--gridline)" stroke-width="1" stroke-dasharray="{dash}"/>'
        )
        guides.append(
            f'<text x="2" y="{gy - 2:.2f}" font-size="8" '
            f'font-family="IBM Plex Mono, monospace" fill="var(--text-muted)">{level}</text>'
        )

    parts = guides
    parts.append(f'<path d="{path}" fill="none" stroke="{color}" stroke-width="1.6"/>')
    parts.append(
        f'<circle cx="{last_x:.2f}" cy="{last_y:.2f}" r="{bubble_radius:.2f}" '
        f'fill="{color}" fill-opacity="0.28" stroke="{color}" stroke-width="1.4"/>'
    )
    label_x = max(0.0, min(width - 26, last_x - 13))
    parts.append(
        f'<text x="{label_x:.2f}" y="{max(10.0, last_y - bubble_radius - 5):.2f}" '
        f'font-size="9.5" font-family="IBM Plex Mono, monospace" text-anchor="middle" '
        f'fill="{color}">{last_rsi:.0f}</text>'
    )

    if ohlc:
        # x-axis: same tick-picking/labeling approach as render_candlestick_svg,
        # but positions map through the RSI series' own (i - first_idx)/span_i
        # scale rather than per-bar centers, since this is a continuous line
        # rather than discrete bars.
        n = last_idx - first_idx + 1
        parts.append(
            f'<line x1="0" y1="{height:.2f}" x2="{width}" y2="{height:.2f}" '
            f'stroke="var(--gridline)" stroke-width="1"/>'
        )
        if n <= 1:
            idxs = [first_idx]
        else:
            steps = max(1, n_ticks - 1)
            idxs = sorted(set(first_idx + round(k * (n - 1) / steps) for k in range(n_ticks)))
        last_date = None
        for pos, idx in enumerate(idxs):
            if idx >= len(ohlc):
                continue
            ts = ohlc[idx].get("ts")
            if ts is None:
                continue
            x_center = (idx - first_idx) / span_i * width
            anchor = "middle"
            if pos == 0:
                anchor = "start"
            elif pos == len(idxs) - 1:
                anchor = "end"
            date_str = ts.strftime("%m/%d")
            time_str = ts.strftime("%H:%M")
            label = f"{date_str} {time_str}" if date_str != last_date else time_str
            last_date = date_str
            parts.append(
                f'<line x1="{x_center:.2f}" y1="{height:.2f}" x2="{x_center:.2f}" y2="{height + 4:.2f}" '
                f'stroke="var(--gridline)" stroke-width="1"/>'
            )
            parts.append(
                f'<text x="{x_center:.2f}" y="{height + 14:.2f}" text-anchor="{anchor}" '
                f'font-size="8.5" font-family="IBM Plex Mono, monospace" '
                f'fill="var(--text-muted)">{html.escape(label)}</text>'
            )

    aria_suffix = " with date/time axis" if ohlc else ""
    return (
        f'<svg viewBox="0 0 {width} {total_height}" preserveAspectRatio="none" role="img" '
        f'aria-label="Hourly RSI trend, last value {last_rsi:.0f}, bubble radius sized '
        f'relative to the rest of the board\'s 3-hour % change{aria_suffix}">{"".join(parts)}</svg>'
    )


def compute_futures_3h_flow(closes):
    """Given a list of hourly closes (oldest -> newest), return the ~3-hour
    price-flow info {pct, mag, flow}, or None if there aren't at least 4
    hourly bars to compare against. Futures are priced instruments (not
    yields), so up == money flowing in, same convention as ES=F/GC=F above."""
    if len(closes) < 4:
        return None
    last, then = closes[-1], closes[-4]
    if not then:
        return None
    change = last - then
    pct = change / then * 100
    mag = magnitude(abs(pct), FUTURES_3H_LADDER)
    flow = "flat" if mag == "Flat" else ("in" if change > 0 else "out")
    return {"pct": pct, "mag": mag, "flow": flow}


def build_futures(days=FUTURES_WINDOW_DAYS):
    """Returns a list of dicts, one per FUTURES entry, each carrying the full
    hourly OHLC history over the last `days` calendar days, the price/change
    across that window, and a 3h money-flow read used for the blurb.

    Bubble radii are assigned in a second pass (see
    compute_relative_bubble_radii) so each instrument's end-bubble is sized
    RELATIVE TO THE REST OF THE BOARD this run, not from a fixed formula --
    this run's single quietest instrument always gets the biggest bubble and
    the single most volatile always gets the smallest."""
    out = []
    for ticker, name, category in FUTURES:
        ohlc = fetch_hourly_ohlc(ticker, hours=None, period=f"{days}d")
        if ohlc is None or len(ohlc) < 2:
            out.append({"ticker": ticker, "name": name, "category": category, "unavailable": True})
            continue
        closes_list = [c["close"] for c in ohlc]
        last = closes_list[-1]
        first = closes_list[0]
        change = last - first
        pct = (change / first * 100) if first else 0.0
        flow_3h = compute_futures_3h_flow(closes_list)
        out.append({
            "ticker": ticker,
            "name": name,
            "category": category,
            "unavailable": False,
            "last": last,
            "change": change,
            "pct": pct,
            "closes": closes_list,
            "ohlc": ohlc,
            "hours_covered": len(closes_list),
            "last_ts": ohlc[-1].get("ts"),
            "flow_3h": flow_3h,
            "rsi_series": rsi_series(closes_list),
        })

    bubble_radii = compute_relative_bubble_radii(out)
    for f in out:
        if not f.get("unavailable"):
            f["bubble_r"] = bubble_radii.get(f["ticker"], RSI_BUBBLE_MIN_R)
    return out


def futures_freshness(futures):
    """Most recent hourly-bar timestamp across every available futures
    symbol, or None if nothing came back with a usable timestamp. Surfaced
    on the Futures watchlist card so staleness (e.g. a stuck/failed hourly
    workflow run) is visible on the page itself instead of only in git
    history."""
    stamps = [f["last_ts"] for f in futures if not f.get("unavailable") and f.get("last_ts") is not None]
    return max(stamps) if stamps else None


def build_futures_blurb(futures):
    """Plain-English summary of where money is flowing across the futures
    board over the last ~3 hours, aggregated by category (Equity Index,
    Treasuries, Metals, Energy, Agriculture, Livestock, Softs) since listing
    all ~35 symbols individually would be unreadable."""
    cat_flows = {}
    movers = []
    for f in futures:
        if f.get("unavailable"):
            continue
        fl = f.get("flow_3h")
        if not fl:
            continue
        cat_flows.setdefault(f["category"], []).append(fl["flow"])
        movers.append(f)

    if not cat_flows:
        return "No 3-hour flow data available this run."

    cat_summary = {}
    for cat, flows in cat_flows.items():
        counts = Counter(flows)
        top_flow, top_n = counts.most_common(1)[0]
        tied = sum(1 for v in counts.values() if v == top_n) > 1
        cat_summary[cat] = "mixed" if tied else top_flow

    ordered_cats = [c for c in FUTURES_CATEGORY_ORDER if c in cat_summary]
    in_cats = [c for c in ordered_cats if cat_summary[c] == "in"]
    out_cats = [c for c in ordered_cats if cat_summary[c] == "out"]
    flat_cats = [c for c in ordered_cats if cat_summary[c] == "flat"]
    mixed_cats = [c for c in ordered_cats if cat_summary[c] == "mixed"]

    parts = []
    if in_cats:
        parts.append(f"flowing into {', '.join(in_cats)}")
    if out_cats:
        parts.append(f"flowing out of {', '.join(out_cats)}")
    if flat_cats:
        parts.append(f"roughly flat in {', '.join(flat_cats)}")
    if mixed_cats:
        parts.append(f"mixed (no consistent direction) in {', '.join(mixed_cats)}")

    sentence = "Over the last 3 hours, money across the futures board is " + "; ".join(parts) + "."

    if movers:
        biggest = max(movers, key=lambda f: abs(f["flow_3h"]["pct"]))
        sentence += (
            f" Biggest 3h mover: {biggest['name']} ({biggest['ticker']}) "
            f"{biggest['flow_3h']['pct']:+.2f}%, {biggest['flow_3h']['mag']}."
        )
    return sentence


def text_sparkline(values):
    """Compress a series of closes into an 8-level unicode block sparkline,
    for the plain-text report where an SVG bar chart isn't possible."""
    if not values:
        return ""
    lo, hi = min(values), max(values)
    span = hi - lo
    n = len(SPARK_BLOCKS) - 1
    if span == 0:
        return SPARK_BLOCKS[0] * len(values)
    return "".join(SPARK_BLOCKS[min(n, int((v - lo) / span * n))] for v in values)


def render_futures_text(futures, days=FUTURES_WINDOW_DAYS):
    """Plain-text lines for the Futures watchlist section of latest.txt."""
    lines = [f"Futures watchlist (hourly OHLC, last {days} days -- bar count varies by symbol's trading calendar):"]
    current_cat = None
    for f in futures:
        if f["category"] != current_cat:
            current_cat = f["category"]
            lines.append(f"  -- {current_cat} --")
        if f["unavailable"]:
            lines.append(f"  {f['ticker']:<7} {f['name']:<20} DATA UNAVAILABLE")
            continue
        spark = text_sparkline(f["closes"])
        lines.append(
            f"  {f['ticker']:<7} {f['name']:<20} {f['last']:,.3f} "
            f"({f['change']:+,.3f}, {f['pct']:+.2f}%)  [{f['hours_covered']}h]  {spark}"
        )
    lines.append("")
    lines.append(build_futures_blurb(futures))
    return lines


def flow_direction(ticker, raw_direction):
    """Map a raw up/down/flat price direction to in/out/flat money-flow
    language. Every current asset is a priced instrument (price up == money
    flowing in), so this is a straight passthrough -- kept as a function
    since a future yield-based asset would need a direction inversion here."""
    if raw_direction == "flat":
        return "flat"
    return "in" if raw_direction == "up" else "out"


def compute_window_metric(ticker, c_now, c_then, pct_ladder):
    """Return a dict {val_str, mag, direction, flow} for one timeframe, or
    None if c_now/c_then aren't usable."""
    if c_now is None or c_then is None or not c_then:
        return None
    pct = (c_now - c_then) / c_then * 100
    mag = magnitude(abs(pct), pct_ladder)
    direction = "flat" if mag == "Flat" else ("up" if pct > 0 else "down")
    return {
        "val_str": f"{pct:+.2f}%",
        "mag": mag,
        "direction": direction,
        "flow": flow_direction(ticker, direction),
    }


def build_report():
    """Returns (report_text, assets) where `assets` is a list of structured
    dicts consumed by render_html()."""
    lines = []
    flow_in, flow_out, flow_flat = [], [], []
    assets = []
    now = datetime.now(timezone.utc)

    for ticker, label, short_name in ASSETS:
        t = yf.Ticker(ticker)
        last_price = prev_close = None
        try:
            fi = t.fast_info
            last_price = fi["last_price"]
            prev_close = fi["previous_close"]
        except Exception:
            pass

        hist = fetch_intraday(ticker, interval="15m", period="1d")
        if last_price is None or prev_close is None:
            if hist is None or len(hist) < 2:
                lines.append(f"{label}: DATA UNAVAILABLE")
                assets.append({
                    "ticker": ticker, "label": label, "short_name": short_name,
                    "unavailable": True,
                })
                continue
            last_price = hist["Close"].iloc[-1]
            prev_close = hist["Close"].iloc[0]

        hourly_ohlc = fetch_hourly_ohlc(ticker)

        change = last_price - prev_close
        pct = (change / prev_close) * 100 if prev_close else 0.0

        # --- per-window structured metrics (3h / 3d / 30d) ---
        windows = {}
        if hist is not None and len(hist) >= 4:
            closes = hist["Close"]
            three_hr_ago = closes.iloc[max(0, len(closes) - 12)]
            windows["3h"] = compute_window_metric(
                ticker, closes.iloc[-1], three_hr_ago, THRESHOLDS_3H.get(ticker),
            )

        daily_hist = fetch_daily(ticker)
        if daily_hist is not None:
            closes_d = daily_hist["Close"]
            if len(closes_d) > 3:
                windows["3d"] = compute_window_metric(
                    ticker, closes_d.iloc[-1], closes_d.iloc[-4], THRESHOLDS_3D.get(ticker),
                )
            if len(closes_d) > 30:
                windows["30d"] = compute_window_metric(
                    ticker, closes_d.iloc[-1], closes_d.iloc[-31], THRESHOLDS_30D.get(ticker),
                )

        extra_tags = ""
        for tf in TF_ORDER:
            m = windows.get(tf)
            if m:
                extra_tags += f" [{tf}: {m['val_str']}, {m['mag']}, {m['direction']}]"

        mag = magnitude(abs(pct), THRESHOLDS[ticker])
        target, into_word, outof_word = FLOW_WORDS[ticker]
        if mag == "Flat":
            statement = "little change / roughly flat"
            since_prev_flow = "flat"
        elif change > 0:
            statement = f"money flowing {into_word} {target} -- {mag}"
            since_prev_flow = "in"
        else:
            statement = f"money flowing {outof_word} {target} -- {mag}"
            since_prev_flow = "out"
        lines.append(f"{label}: {last_price:,.2f} ({change:+,.2f}, {pct:+.2f}%) -- {statement}{extra_tags}")
        bucket = flow_flat if mag == "Flat" else (flow_in if change > 0 else flow_out)
        bucket.append(f"{target} ({mag.lower()})")
        value_str = f"{last_price:,.2f}"
        delta_str = f"{'▲' if change >= 0 else '▼'} {abs(change):,.2f} · {pct:+.2f}%"

        assets.append({
            "ticker": ticker,
            "label": label,
            "short_name": short_name,
            "unavailable": False,
            "value_str": value_str,
            "delta_str": delta_str,
            "since_prev": {"pct": pct, "mag": mag, "flow": since_prev_flow, "statement": statement},
            "windows": windows,
            "hourly_ohlc": hourly_ohlc,
        })

    report = []
    report.append("Cross-asset money flow snapshot")
    report.extend(lines)
    report.append("")
    report.append(f"In: {', '.join(flow_in) if flow_in else 'none'}.")
    report.append(f"Out: {', '.join(flow_out) if flow_out else 'none'}.")
    if flow_flat:
        report.append(f"Flat: {', '.join(flow_flat)}.")
    report.append(f"As of: {now.strftime('%Y-%m-%d %H:%M UTC')} (yfinance/Yahoo real-time feed).")
    report.append("Automated informational snapshot, not financial advice.")
    return "\n".join(report), assets, now


# --------------------------------------------------------------------------
# HTML rendering
# --------------------------------------------------------------------------

def join_windows(tfs):
    names = [TF_LABELS_SHORT[tf] for tf in tfs]
    if len(names) == 1:
        return f"the last {names[0]}"
    if len(names) == 2:
        return f"the last {names[0]} and {names[1]}"
    return "the last " + ", ".join(names[:-1]) + f" and {names[-1]}"


def describe_flow_across_windows(flows):
    """flows: {"3h": "in"/"out"/"flat"/None, "3d": ..., "30d": ...} ->
    a plain-English sentence contrasting the windows, e.g.
    'Flat over the last 3 hours, but flowing in over the last 3 days and 30 days.'"""
    available = [(tf, flows[tf]) for tf in TF_ORDER if flows.get(tf) is not None]
    missing = [tf for tf in TF_ORDER if flows.get(tf) is None]
    if not available:
        return "No timeframe data available this run."

    groups = []
    for tf, val in available:
        if groups and groups[-1][0] == val:
            groups[-1][1].append(tf)
        else:
            groups.append([val, [tf]])

    def phrase(val):
        return {"in": "flowing in", "out": "flowing out", "flat": "flat"}[val]

    if len(groups) == 1:
        val, tfs = groups[0]
        if val == "flat":
            sentence = f"Flat across {join_windows(tfs)} — no real signal"
        else:
            sentence = f"{phrase(val).capitalize()} consistently across {join_windows(tfs)}"
    else:
        parts = []
        for i, (val, tfs) in enumerate(groups):
            clause = f"{phrase(val)} over {join_windows(tfs)}"
            if i == 0:
                clause = clause[0].upper() + clause[1:]
            parts.append(clause)
        sentence = (f"{parts[0]}, but {parts[1]}" if len(parts) == 2
                    else "; ".join(parts[:-1]) + f", and {parts[-1]}")

    if missing:
        sentence += f" ({' and '.join(TF_LABELS_SHORT[tf] for tf in missing)} data unavailable)"

    return sentence + "."


def build_overall_summary(assets):
    mixed, consistent_in, consistent_out, no_signal = [], [], [], []
    for a in assets:
        if a.get("unavailable"):
            continue
        available = [v["flow"] for v in a["windows"].values() if v]
        distinct = set(available)
        if len(distinct) <= 1:
            only = next(iter(distinct)) if distinct else None
            if only == "in":
                consistent_in.append(a["short_name"])
            elif only == "out":
                consistent_out.append(a["short_name"])
            elif only == "flat":
                no_signal.append(a["short_name"])
        else:
            mixed.append(a["short_name"])

    parts = []
    if mixed:
        verb = "show" if len(mixed) > 1 else "shows"
        parts.append(f"{', '.join(mixed)} {verb} a different flow direction between the short- and long-term windows this run")
    if consistent_in:
        verb = "are" if len(consistent_in) > 1 else "is"
        parts.append(f"{', '.join(consistent_in)} {verb} flowing in consistently across every window available")
    if consistent_out:
        verb = "are" if len(consistent_out) > 1 else "is"
        parts.append(f"{', '.join(consistent_out)} {verb} flowing out consistently across every window available")
    if no_signal:
        verb = "show" if len(no_signal) > 1 else "shows"
        parts.append(f"{', '.join(no_signal)} {verb} no real signal in any window")

    if not parts:
        return "No cross-timeframe data available this run."
    return "; ".join(parts) + "."


def biggest_mover(assets):
    """Largest abs since-prev-close % across every available asset. Returns
    the asset dict, or None on a tie/no data."""
    candidates = [a for a in assets if not a.get("unavailable")]
    if not candidates:
        return None
    candidates.sort(key=lambda a: abs(a["since_prev"]["pct"]), reverse=True)
    if len(candidates) > 1 and abs(candidates[0]["since_prev"]["pct"]) == abs(candidates[1]["since_prev"]["pct"]):
        return None
    return candidates[0]


def render_bar(direction_flow, mag):
    """Return the HTML for one mini 3-way bar-track (out | baseline | in)."""
    width = MAG_TO_WIDTH.get(mag, 0)
    out_w = width if direction_flow == "out" else 0
    in_w = width if direction_flow == "in" else 0
    dot = '<div class="tf-flat-dot"></div>' if direction_flow == "flat" else ""
    return (
        '<div class="tf-track">'
        f'<div class="tf-half tf-half-out"><div class="tf-fill out" style="width:{out_w}%"></div></div>'
        f'<div class="tf-baseline">{dot}</div>'
        f'<div class="tf-half tf-half-in"><div class="tf-fill in" style="width:{in_w}%"></div></div>'
        '</div>'
    )


def render_candlestick_svg(ohlc, width=680, height=110, show_x_axis=False, n_ticks=6):
    """Inline SVG hourly candlestick chart from a list of {open,high,low,close}
    dicts (oldest -> newest, as returned by fetch_hourly_ohlc). Each bar is
    colored by that bar's own close vs. open (up == div-in, down == div-out),
    matching the in/out color language used elsewhere on the row. The SVG has
    no fixed pixel size baked in beyond its viewBox -- it's stretched to the
    row's full width by CSS (see .candle-chart svg).

    If `show_x_axis` is True, draws a thin axis under the candles with date/
    time tick labels pulled from each bar's "ts" field (added by
    fetch_hourly_ohlc), spaced out to ~n_ticks evenly across the window. The
    returned SVG's viewBox grows by AXIS_H to fit the extra row -- callers
    that turn this on must also give the wrapping element that much more
    height (see .candle-chart.with-axis svg in CSS)."""
    AXIS_H = 22
    n = len(ohlc)
    total_height = height + (AXIS_H if show_x_axis else 0)
    if n == 0:
        return f'<svg viewBox="0 0 {width} {total_height}"></svg>'
    highs = [c["high"] for c in ohlc]
    lows = [c["low"] for c in ohlc]
    lo, hi = min(lows), max(highs)
    span = (hi - lo) or 1.0
    pad = 4.0
    draw_h = height - 2 * pad

    def y(val):
        frac = (val - lo) / span
        return pad + (1 - frac) * draw_h

    gap = 1.0
    bar_w = max(0.5, (width - gap * (n - 1)) / n)
    body_w = max(0.4, bar_w * 0.7)
    wick_w = max(0.4, bar_w * 0.18)

    def x_center_of(i):
        return i * (bar_w + gap) + bar_w / 2

    parts = []
    for i, c in enumerate(ohlc):
        x_center = x_center_of(i)
        y_high, y_low = y(c["high"]), y(c["low"])
        y_open, y_close = y(c["open"]), y(c["close"])
        up = c["close"] >= c["open"]
        color = "var(--div-in)" if up else "var(--div-out)"
        body_top = min(y_open, y_close)
        body_h = max(abs(y_close - y_open), 0.8)
        parts.append(
            f'<line x1="{x_center:.2f}" y1="{y_high:.2f}" x2="{x_center:.2f}" y2="{y_low:.2f}" '
            f'stroke="{color}" stroke-width="{wick_w:.2f}"/>'
        )
        parts.append(
            f'<rect x="{x_center - body_w / 2:.2f}" y="{body_top:.2f}" width="{body_w:.2f}" '
            f'height="{body_h:.2f}" fill="{color}"/>'
        )

    if show_x_axis:
        parts.append(
            f'<line x1="0" y1="{height:.2f}" x2="{width}" y2="{height:.2f}" '
            f'stroke="var(--gridline)" stroke-width="1"/>'
        )
        if n == 1:
            idxs = [0]
        else:
            steps = max(1, n_ticks - 1)
            idxs = sorted(set(round(k * (n - 1) / steps) for k in range(n_ticks)))
        last_date = None
        for pos, idx in enumerate(idxs):
            ts = ohlc[idx].get("ts")
            if ts is None:
                continue
            x_center = x_center_of(idx)
            anchor = "middle"
            if idx <= bar_w:
                anchor = "start"
            elif idx >= n - 1 - (bar_w / (bar_w + gap)):
                anchor = "end"
            date_str = ts.strftime("%m/%d")
            time_str = ts.strftime("%H:%M")
            # Only repeat the date when it changes, to keep labels compact.
            label = f"{date_str} {time_str}" if date_str != last_date else time_str
            last_date = date_str
            parts.append(
                f'<line x1="{x_center:.2f}" y1="{height:.2f}" x2="{x_center:.2f}" y2="{height + 4:.2f}" '
                f'stroke="var(--gridline)" stroke-width="1"/>'
            )
            parts.append(
                f'<text x="{x_center:.2f}" y="{height + 14:.2f}" text-anchor="{anchor}" '
                f'font-size="8.5" font-family="system-ui, sans-serif" '
                f'fill="var(--text-muted)">{html.escape(label)}</text>'
            )

    aria_suffix = " with date/time axis" if show_x_axis else ""
    return (
        f'<svg viewBox="0 0 {width} {total_height}" preserveAspectRatio="none" '
        f'role="img" aria-label="Hourly candlestick chart, last {n} hours{aria_suffix}">{"".join(parts)}</svg>'
    )


def render_row(asset, badge=False):
    esc = html.escape
    name = esc(asset["short_name"])
    ticker = esc(asset["ticker"])
    badge_html = '<span class="badge">★ Biggest mover</span>' if badge else ""

    flows_for_sentence = {}
    for tf in TF_ORDER:
        m = asset["windows"].get(tf)
        flows_for_sentence[tf] = m["flow"] if m else None

    hourly = asset.get("hourly_ohlc")
    if hourly:
        candle_svg = render_candlestick_svg(hourly, show_x_axis=True)
        candle_html = (
            f'<div class="candle-chart with-axis">{candle_svg}</div>'
            f'<div class="candle-caption">Hourly candles · last {len(hourly)}h · UTC</div>'
        )
    else:
        candle_html = '<div class="candle-chart candle-na">Hourly chart unavailable</div>'

    sentence = esc(describe_flow_across_windows(flows_for_sentence))
    dot_class = "flat"  # neutral dot; the sentence itself carries the direction detail

    tip = f'{name} {esc(asset["value_str"])}, {esc(asset["delta_str"])} since previous close. {sentence}'

    return f'''      <div class="row" data-tip="{tip}">
        <div class="row-top">
          <div class="asset-id">
            <span class="asset-name">{name}</span>
            <span class="asset-ticker">{ticker}</span>
            {badge_html}
          </div>
          <div class="asset-price">
            <span class="price-value">{esc(asset["value_str"])}</span>
            <span class="price-delta">{esc(asset["delta_str"])}</span>
          </div>
        </div>
        {candle_html}
        <div class="row-bottom">
          <span class="flow-tag"><span class="dot {dot_class}"></span>{sentence}</span>
        </div>
      </div>
'''


def render_table_row(asset):
    esc = html.escape
    cells = [esc(asset["short_name"]), esc(asset["value_str"])]
    sp = asset["since_prev"]
    cells.append(f'{sp["pct"]:+.2f}% ({sp["mag"]})')
    for tf in TF_ORDER:
        m = asset["windows"].get(tf)
        cells.append(f'{esc(m["val_str"])} ({esc(m["mag"])})' if m else "n/a")
    tds = "".join(f'<td class="num">{c}</td>' for c in cells[1:])
    return f'<tr><td>{cells[0]}</td>{tds}</tr>'


def render_futures_bars_svg(closes, width=150, height=32):
    """Small bar chart (one bar per hourly close) as an inline SVG string.
    Bar height is min/max-normalized within the window; each bar is colored
    by whether that hour's close is up or down vs. the previous hour."""
    n = len(closes)
    if n == 0:
        return f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}"></svg>'
    lo, hi = min(closes), max(closes)
    span = (hi - lo) or 1.0
    gap = 1.0
    bar_w = max(0.6, (width - gap * (n - 1)) / n)
    rects = []
    for i, c in enumerate(closes):
        frac = (c - lo) / span
        bar_h = max(1.5, frac * (height - 2))
        x = i * (bar_w + gap)
        y = height - bar_h
        prev = closes[i - 1] if i > 0 else c
        color = "var(--div-in)" if c >= prev else "var(--div-out)"
        rects.append(f'<rect x="{x:.2f}" y="{y:.2f}" width="{bar_w:.2f}" height="{bar_h:.2f}" fill="{color}"/>')
    return (
        f'<svg width="{width}" height="{height}" viewBox="0 0 {width} {height}" '
        f'preserveAspectRatio="none" role="img" aria-label="Hourly bar chart">{"".join(rects)}</svg>'
    )


def render_futures_row(f):
    esc = html.escape
    if f["unavailable"]:
        return (
            f'      <div class="fut-row">'
            f'<div class="fut-top"><div class="fut-id"><span class="fut-ticker">{esc(f["ticker"])}</span>'
            f'<span class="fut-name">{esc(f["name"])}</span></div>'
            f'<div class="fut-na">data unavailable</div></div></div>\n'
        )
    delta_class = "in" if f["change"] >= 0 else "out"
    arrow = "▲" if f["change"] >= 0 else "▼"
    # Narrower width than the old full-row chart since price and RSI now sit
    # side by side in two columns -- preserveAspectRatio="none" + CSS
    # width:100% stretches either one to fill its column regardless.
    chart_svg = render_candlestick_svg(f["ohlc"], width=330, height=60, show_x_axis=True)
    rsi_vals = f.get("rsi_series") or []
    last_rsi = next((v for v in reversed(rsi_vals) if v is not None), None)
    if last_rsi is not None:
        rsi_svg = render_rsi_trend_svg(rsi_vals, f.get("bubble_r", RSI_BUBBLE_MIN_R), ohlc=f["ohlc"], width=330)
        flow_3h = f.get("flow_3h")
        pct3h_str = f'{flow_3h["pct"]:+.2f}%' if flow_3h else "n/a"
        rsi_caption = (
            f'RSI({RSI_PERIOD}) hourly · now {last_rsi:.0f} · '
            f'bubble sized vs. rest of board (bigger = quieter 3h: {pct3h_str})'
        )
        rsi_col = (
            '<div class="fut-chart-col">'
            f'<div class="fut-rsi-chart">{rsi_svg}</div>'
            f'<div class="fut-chart-caption">{esc(rsi_caption)}</div>'
            '</div>'
        )
    else:
        rsi_col = (
            '<div class="fut-chart-col">'
            '<div class="fut-rsi-chart fut-na-inline">RSI unavailable (not enough hourly bars)</div>'
            '</div>'
        )
    price_col = (
        '<div class="fut-chart-col">'
        f'<div class="fut-chart with-axis">{chart_svg}</div>'
        f'<div class="fut-chart-caption">Hourly candles · last {f["hours_covered"]}h ({FUTURES_WINDOW_DAYS}d)</div>'
        '</div>'
    )
    return f'''      <div class="fut-row">
        <div class="fut-top">
          <div class="fut-id">
            <span class="fut-ticker">{esc(f["ticker"])}</span>
            <span class="fut-name">{esc(f["name"])}</span>
          </div>
          <div class="fut-price">
            <span class="fut-last">{f["last"]:,.3f}</span>
            <span class="fut-delta {delta_class}">{arrow} {f["change"]:+,.3f} ({f["pct"]:+.2f}%)</span>
          </div>
        </div>
        <div class="fut-charts">
{price_col}
{rsi_col}
        </div>
      </div>
'''


def render_futures_card(futures, days=FUTURES_WINDOW_DAYS):
    esc = html.escape
    body = []
    current_cat = None
    for f in futures:
        if f["category"] != current_cat:
            current_cat = f["category"]
            body.append(f'      <div class="fut-category">{esc(current_cat)}</div>\n')
        body.append(render_futures_row(f))
    rows_html = "".join(body)
    blurb = esc(build_futures_blurb(futures))

    freshest = futures_freshness(futures)
    if freshest is not None:
        age_min = (datetime.now(timezone.utc) - freshest).total_seconds() / 60
        stale_note = ""
        if age_min > 90:
            hrs = age_min / 60
            stale_note = f' <span class="fut-stale">— {hrs:.1f}h behind, most recent run may have failed to fetch/commit</span>'
        freshness_html = (
            f'<div class="timestamp">Most recent hourly bar: {esc(freshest.strftime("%Y-%m-%d %H:%M UTC"))}'
            f' ({age_min:.0f} min ago){stale_note}</div>'
        )
    else:
        freshness_html = '<div class="timestamp">Most recent hourly bar: unavailable this run</div>'

    return f'''  <div class="card card-wide">
    <div class="card-head">
      <div>
        <h1>Futures watchlist</h1>
        <p class="subtitle">Full board snapshot — hourly candlesticks over the last {days} days per symbol (bar count varies by trading calendar), across equity index, treasuries, metals, energy, agriculture, livestock and softs. Price chart (left) and hourly RSI(14) trend (right) sit side by side for each symbol. Each RSI line ends in a bubble sized relative to the rest of the board's last-3-hour % change — the quietest instrument this run gets the biggest bubble, the most volatile gets the smallest.</p>
      </div>
    </div>
    {freshness_html}
    <div class="fut-rows">
{rows_html}    </div>
    <div class="blurb"><strong>Futures flow (last 3h):</strong> {blurb}</div>
  </div>
'''


CSS = """
  :root { color-scheme: light; }
  .viz-root {
    --surface-1: #fcfcfb; --page-plane: #f9f9f7; --text-primary: #0b0b0b;
    --text-secondary: #52514e; --text-muted: #898781; --gridline: #e1e0d9;
    --baseline: #c3c2b7; --border: rgba(11,11,11,0.10);
    --div-in: #2a78d6; --div-in-track: #cde2fb; --div-out: #e34948;
    --div-out-track: #f8d9d9; --div-neutral: #f0efec; --status-good: #0ca30c;
  }
  @media (prefers-color-scheme: dark) {
    :root:where(:not([data-theme="light"])) .viz-root {
      color-scheme: dark; --surface-1: #1a1a19; --page-plane: #0d0d0d;
      --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
      --gridline: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
      --div-in: #3987e5; --div-in-track: #184f95; --div-out: #e66767;
      --div-out-track: #6b2323; --div-neutral: #383835; --status-good: #0ca30c;
    }
  }
  :root[data-theme="dark"] .viz-root {
    color-scheme: dark; --surface-1: #1a1a19; --page-plane: #0d0d0d;
    --text-primary: #ffffff; --text-secondary: #c3c2b7; --text-muted: #898781;
    --gridline: #2c2c2a; --baseline: #383835; --border: rgba(255,255,255,0.10);
    --div-in: #3987e5; --div-in-track: #184f95; --div-out: #e66767;
    --div-out-track: #6b2323; --div-neutral: #383835; --status-good: #0ca30c;
  }
  * { box-sizing: border-box; }
  html, body { margin: 0; padding: 0; background: var(--page-plane); font-family: system-ui, -apple-system, "Segoe UI", sans-serif; }
  .viz-root { background: var(--page-plane); min-height: 100vh; padding: 28px 16px 48px; display: flex; justify-content: center; }
  .card { width: 100%; max-width: 760px; background: var(--surface-1); border: 1px solid var(--border); border-radius: 16px; padding: 28px 26px 22px; }
  .card-head { display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; margin-bottom: 4px; }
  h1 { margin: 0; font-size: 19px; font-weight: 650; color: var(--text-primary); letter-spacing: -0.01em; }
  .subtitle { margin: 6px 0 0; font-size: 13px; color: var(--text-secondary); line-height: 1.5; max-width: 46ch; }
  .theme-toggle { flex: none; border: 1px solid var(--border); background: transparent; color: var(--text-secondary); border-radius: 8px; padding: 6px 10px; font-size: 12px; cursor: pointer; font-family: inherit; }
  .theme-toggle:hover { color: var(--text-primary); border-color: var(--text-muted); }
  .timestamp { margin-top: 14px; font-size: 12px; color: var(--text-muted); }
  .legend { display: flex; align-items: center; gap: 18px; margin: 20px 0 6px; font-size: 12px; color: var(--text-secondary); flex-wrap: wrap; }
  .legend-item { display: flex; align-items: center; gap: 6px; }
  .dot { width: 9px; height: 9px; border-radius: 50%; flex: none; }
  .dot.out { background: var(--div-out); } .dot.in { background: var(--div-in); } .dot.flat { background: var(--baseline); }
  .rows { margin-top: 8px; }
  .row { padding: 16px 0; border-top: 1px solid var(--gridline); position: relative; }
  .row:first-child { border-top: none; }
  .row-top { display: flex; justify-content: space-between; align-items: baseline; gap: 12px; margin-bottom: 12px; }
  .asset-id { display: flex; align-items: baseline; gap: 7px; min-width: 0; flex-wrap: wrap; }
  .asset-name { font-size: 14px; font-weight: 600; color: var(--text-primary); }
  .asset-ticker { font-size: 11px; color: var(--text-muted); }
  .badge { margin-left: 6px; font-size: 10.5px; font-weight: 600; color: var(--status-good); border: 1px solid currentColor; border-radius: 999px; padding: 1px 7px 2px; white-space: nowrap; }
  .asset-price { text-align: right; flex: none; }
  .price-value { font-size: 15px; font-weight: 600; color: var(--text-primary); }
  .price-delta { display: block; font-size: 11.5px; color: var(--text-secondary); margin-top: 1px; }
  .row-bottom { display: flex; justify-content: space-between; align-items: center; gap: 10px; margin-top: 10px; font-size: 12px; }
  .flow-tag { display: flex; align-items: center; gap: 6px; color: var(--text-secondary); }
  .flow-tag .dot { width: 7px; height: 7px; flex: none; margin-top: 2px; }
  .row[data-tip]:hover::after { content: attr(data-tip); position: absolute; left: 0; right: 0; bottom: -6px; transform: translateY(100%); background: var(--text-primary); color: var(--surface-1); font-size: 11.5px; line-height: 1.5; padding: 8px 10px; border-radius: 8px; z-index: 5; box-shadow: 0 6px 18px rgba(0,0,0,0.18); }
  .note { margin-top: 18px; padding-top: 14px; border-top: 1px solid var(--gridline); font-size: 11.5px; color: var(--text-muted); line-height: 1.6; }
  .blurb { margin-top: 14px; padding: 14px 16px; background: var(--div-neutral); border-radius: 10px; font-size: 12.5px; color: var(--text-secondary); line-height: 1.6; }
  .blurb strong { color: var(--text-primary); }
  details.table-toggle { margin-top: 10px; }
  details.table-toggle summary { cursor: pointer; font-size: 12px; color: var(--text-secondary); user-select: none; }
  table.data-table { width: 100%; border-collapse: collapse; margin-top: 10px; font-size: 11.5px; }
  table.data-table th, table.data-table td { text-align: left; padding: 6px 7px; border-bottom: 1px solid var(--gridline); color: var(--text-secondary); font-variant-numeric: tabular-nums; }
  table.data-table th { color: var(--text-muted); font-weight: 600; font-size: 10.5px; text-transform: uppercase; letter-spacing: 0.03em; }
  table.data-table td.num { color: var(--text-primary); }
  .timeframe-bars { display: flex; gap: 12px; margin-top: 4px; }
  .tf-col { flex: 1; min-width: 0; }
  .tf-label { font-size: 9.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; margin-bottom: 5px; text-align: center; }
  .tf-track { position: relative; display: flex; align-items: center; height: 14px; }
  .tf-half { width: 50%; height: 12px; display: flex; align-items: center; position: relative; }
  .tf-half-out { justify-content: flex-end; padding-right: 1px; } .tf-half-in { justify-content: flex-start; padding-left: 1px; }
  .tf-fill { height: 12px; min-width: 0; }
  .tf-fill.out { background: var(--div-out); border-radius: 3px 0 0 3px; }
  .tf-fill.in { background: var(--div-in); border-radius: 0 3px 3px 0; }
  .tf-baseline { position: absolute; left: 50%; top: 0; bottom: 0; width: 1px; background: var(--baseline); transform: translateX(-0.5px); }
  .tf-flat-dot { position: absolute; left: 50%; top: 50%; width: 6px; height: 6px; border-radius: 50%; background: var(--baseline); transform: translate(-50%, -50%); }
  .tf-caption { font-size: 10px; color: var(--text-secondary); margin-top: 5px; text-align: center; }
  .tf-na { font-size: 10px; color: var(--text-muted); font-style: italic; text-align: center; margin-top: 5px; }
  .candle-chart { margin-top: 4px; width: 100%; line-height: 0; }
  .candle-chart svg { display: block; width: 100%; height: 110px; }
  .candle-chart.with-axis svg { height: 132px; }
  .candle-caption { font-size: 10px; color: var(--text-muted); margin-top: 4px; text-align: right; }
  .candle-chart.candle-na { line-height: normal; font-size: 11px; color: var(--text-muted); font-style: italic; text-align: center; padding: 40px 0; height: 110px; box-sizing: border-box; }
  .stack { width: 100%; max-width: 1120px; display: flex; flex-direction: column; gap: 20px; align-items: center; }
  .fut-rows { margin-top: 8px; }
  .fut-category { font-size: 10.5px; font-weight: 700; color: var(--text-muted); text-transform: uppercase; letter-spacing: 0.06em; margin: 18px 0 2px; }
  .fut-category:first-child { margin-top: 4px; }
  .fut-row { display: flex; flex-direction: column; align-items: stretch; gap: 4px; padding: 12px 0; border-top: 1px solid var(--gridline); }
  .fut-row:first-child { border-top: none; }
  .fut-top { display: flex; align-items: center; justify-content: space-between; gap: 14px; }
  .fut-id { display: flex; flex-direction: column; gap: 2px; min-width: 0; flex: 1; }
  .fut-ticker { font-size: 13px; font-weight: 600; color: var(--text-primary); }
  .fut-name { font-size: 10.5px; color: var(--text-muted); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
  .fut-price { text-align: right; flex: none; display: flex; flex-direction: column; gap: 2px; }
  .fut-last { font-size: 13px; font-weight: 600; color: var(--text-primary); font-variant-numeric: tabular-nums; }
  .fut-delta { font-size: 11px; font-variant-numeric: tabular-nums; }
  .fut-delta.in { color: var(--div-in); } .fut-delta.out { color: var(--div-out); }
  .fut-chart { width: 100%; line-height: 0; margin-top: 2px; }
  .fut-chart svg { display: block; width: 100%; height: 60px; }
  .fut-chart.with-axis svg { height: 82px; }
  .fut-chart-caption { font-size: 9.5px; color: var(--text-muted); text-align: right; margin-bottom: 2px; }
  .fut-na { flex: none; font-size: 11px; color: var(--text-muted); font-style: italic; }
  .fut-stale { color: var(--div-out); font-weight: 600; }
  .fut-charts { display: flex; gap: 18px; align-items: flex-start; margin-top: 4px; }
  .fut-chart-col { flex: 1 1 0; min-width: 0; }
  .fut-rsi-chart { width: 100%; line-height: 0; margin-top: 2px; }
  .fut-rsi-chart svg { display: block; width: 100%; height: 92px; }
  .fut-rsi-chart.fut-na-inline { line-height: normal; font-size: 10.5px; color: var(--text-muted); font-style: italic; text-align: center; padding: 10px 0; height: 92px; box-sizing: border-box; }
  .card.card-wide { max-width: 1120px; }
  @media (max-width: 720px) {
    .fut-charts { flex-direction: column; }
  }
"""

SCRIPT = """
  const btn = document.getElementById('themeToggle');
  const root = document.documentElement;
  function syncLabel() {
    const explicit = root.getAttribute('data-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const isDark = explicit ? explicit === 'dark' : prefersDark;
    btn.textContent = isDark ? 'Light mode' : 'Dark mode';
  }
  btn.addEventListener('click', () => {
    const current = root.getAttribute('data-theme');
    const prefersDark = window.matchMedia('(prefers-color-scheme: dark)').matches;
    const currentlyDark = current ? current === 'dark' : prefersDark;
    root.setAttribute('data-theme', currentlyDark ? 'light' : 'dark');
    syncLabel();
  });
  syncLabel();
"""


def render_html(assets, now, futures=None):
    esc = html.escape
    as_of = now.strftime("%Y-%m-%d %H:%M UTC")
    available_assets = [a for a in assets if not a.get("unavailable")]
    mover = biggest_mover(available_assets)

    rows_html = "".join(
        render_row(a, badge=(mover is not None and a is mover))
        for a in available_assets
    )
    table_rows = "".join(render_table_row(a) for a in available_assets)
    summary = esc(build_overall_summary(available_assets))

    missing_30d = [a["short_name"] for a in available_assets if "30d" not in a["windows"]]
    note_extra = ""
    if missing_30d:
        note_extra = f" 30-day data was unavailable this run for: {esc(', '.join(missing_30d))}."

    futures_card = render_futures_card(futures) if futures else ""

    # Equilibrium view is embedded directly below the futures card on this
    # same page (see #equilibrium below) rather than living only on its own
    # equilibrium.html -- EQUILIBRIUM_CSS is scoped entirely under #app so
    # concatenating it here can't collide with the report's own CSS above.
    eq_app_html = render_equilibrium_app(assets, now, embedded=True)
    equilibrium_section = (
        '<div id="equilibrium" style="width:100%; max-width:1120px; '
        'border-radius:16px; overflow:hidden;">'
        f'{eq_app_html}</div>'
    )

    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Cross-Asset Money Flow — As of {esc(as_of)}</title>
<style>{CSS}
{EQUILIBRIUM_CSS}</style>
</head>
<body>
<div class="viz-root">
<div class="stack">
  <div class="card">
    <div class="card-head">
      <div>
        <h1>Cross-asset money flow</h1>
        <p class="subtitle">Where money is moving right now across equities, bonds, the dollar, gold and bitcoin — over the last 3 hours, 3 days, and 30 days.</p>
      </div>
      <div style="display:flex; gap:8px; align-items:flex-start;">
        <a class="theme-toggle" href="#equilibrium" style="text-decoration:none; display:inline-block;">Equilibrium view &darr;</a>
        <button class="theme-toggle" id="themeToggle" type="button">Dark mode</button>
      </div>
    </div>
    <div class="timestamp">As of {esc(as_of)} · yfinance / Yahoo real-time feed</div>
    <div class="legend">
      <div class="legend-item"><span class="dot out"></span>Money flowing out</div>
      <div class="legend-item"><span class="dot flat"></span>Flat</div>
      <div class="legend-item"><span class="dot in"></span>Money flowing in</div>
    </div>
    <div class="rows">
{rows_html}    </div>

    <div class="blurb"><strong>Across all three windows:</strong> {summary}</div>

    <details class="table-toggle">
      <summary>Show data table</summary>
      <table class="data-table">
        <thead><tr><th>Asset</th><th>Value</th><th>Since prev close</th><th>3H</th><th>3D</th><th>30D</th></tr></thead>
        <tbody>
{table_rows}
        </tbody>
      </table>
    </details>
    <p class="note">Automated informational snapshot from the moneyflow GitHub Actions feed — not financial advice.{note_extra}</p>
  </div>
{futures_card}{equilibrium_section}</div>
</div>
<script>{SCRIPT}</script>
</body>
</html>
"""


EQUILIBRIUM_HISTORY_HOURS = 20  # slider range: 0 (that many hours ago) .. current hour


def _eq_dom_id(ticker):
    """Sanitize a ticker into a safe HTML id / JS lookup key, e.g. 'ZN=F' -> 'ZNF'."""
    return "".join(ch for ch in ticker if ch.isalnum()) or "x"


def build_equilibrium_history(assets, hours=EQUILIBRIUM_HISTORY_HOURS):
    """Given the `assets` list from build_report() (each with an
    "hourly_ohlc" list, oldest -> newest), build a real, hour-by-hour replay
    for the 6 EQUILIBRIUM_TICKERS covering the last `hours` hours plus the
    current hour (hours+1 frames total) -- NO simulation, no invented
    motion: every frame is an actual past RSI(14) reading computed from real
    hourly closes, exactly like the current-hour case, just further back.

    Each frame gets its own bubble sizing, relative to the other 5 tickers
    AT THAT HOUR (not relative to the current hour), so scrubbing the slider
    shows how the board's relative quiet/volatile ranking itself evolved.

    Returns {"frames": [...]} ordered oldest -> newest (frames[-1] is the
    current hour), or None if any of the 6 tickers doesn't have enough
    hourly history to compute at least 2 real frames (RSI needs
    RSI_PERIOD+1 bars, the 3h-change bubble needs 3 more on top of that)."""
    by_ticker = {a["ticker"]: a for a in assets if not a.get("unavailable")}
    per_ticker_records = {}
    for ticker, _display_name in EQUILIBRIUM_TICKERS:
        a = by_ticker.get(ticker)
        hourly = a.get("hourly_ohlc") if a else None
        if not hourly or len(hourly) < RSI_PERIOD + 1 + 3:
            return None
        closes = [c["close"] for c in hourly]
        rsi_vals = rsi_series(closes)
        records = []  # oldest -> newest; only hours where both RSI and a 3h-change are defined
        for idx in range(3, len(closes)):
            if rsi_vals[idx] is None:
                continue
            base = closes[idx - 3]
            pct3h = ((closes[idx] - base) / base * 100) if base else None
            records.append({"ts": hourly[idx].get("ts"), "rsi": rsi_vals[idx], "pct3h": pct3h})
        if len(records) < 2:
            return None
        per_ticker_records[ticker] = records

    frame_count = min(min(len(v) for v in per_ticker_records.values()), hours + 1)
    frames = []
    for offset in range(frame_count):
        pos_from_end = frame_count - 1 - offset  # 0 = current hour, larger = further back
        frame_pcts = {}
        raw_rows = {}
        for ticker, _display_name in EQUILIBRIUM_TICKERS:
            rec = per_ticker_records[ticker][-(pos_from_end + 1)]
            raw_rows[ticker] = rec
            if rec["pct3h"] is not None:
                frame_pcts[ticker] = abs(rec["pct3h"])
        radii = compute_relative_bubble_radii_from_pcts(frame_pcts)

        frame_assets = []
        ts_candidates = []
        for ticker, display_name in EQUILIBRIUM_TICKERS:
            rec = raw_rows[ticker]
            x = max(-1.0, min(1.0, (rec["rsi"] - 50.0) / 50.0))
            frame_assets.append({
                "id": _eq_dom_id(ticker),
                "ticker": ticker,
                "name": display_name,
                "rsi": round(rec["rsi"], 1),
                "x": round(x, 4),
                "pct3h": None if rec["pct3h"] is None else round(rec["pct3h"], 3),
                "bubble_r": round(radii.get(ticker, RSI_BUBBLE_MIN_R), 3),
                "color": equilibrium_color_for_x(x),
            })
            if rec["ts"] is not None:
                ts_candidates.append(rec["ts"])
        frame_ts = max(ts_candidates) if ts_candidates else None
        frames.append({
            "ts": frame_ts.strftime("%Y-%m-%d %H:%M UTC") if frame_ts else None,
            "assets": frame_assets,
        })
    return {"frames": frames}


def _eq_well_y(x_norm, height, base_frac=0.28, amp_frac=0.42):
    """Same potential-well shape used both server-side (initial paint) and
    client-side (JS port in EQUILIBRIUM_SLIDER_SCRIPT): lowest (largest y
    offset) at the center (x=0), rising toward the edges (x=+-1)."""
    depth = 1 - x_norm * x_norm
    return height * base_frac + depth * height * amp_frac


EQUILIBRIUM_SVG_WIDTH = 900
EQUILIBRIUM_SVG_HEIGHT = 380


def render_equilibrium_svg(frame_assets, width=EQUILIBRIUM_SVG_WIDTH, height=EQUILIBRIUM_SVG_HEIGHT):
    """SVG scene for one frame (a real hourly snapshot -- see
    build_equilibrium_history), with each bubble/label/RSI-text tagged by a
    stable per-ticker id so the slider's JS can reposition them for other
    frames without re-rendering the whole SVG (only the well curve and axis
    labels are truly static; everything else is script-updatable)."""
    cx = width / 2
    scale_x = width * 0.44
    top_margin = height * 0.30
    baseline_y = top_margin + _eq_well_y(0, height)

    def px_of(x):
        return cx + x * scale_x

    def py_of(x, r):
        return top_margin + _eq_well_y(x, height) - 10 - r

    curve_pts = []
    n = 160
    for i in range(n + 1):
        xn = -1 + 2 * i / n
        curve_pts.append((px_of(xn), top_margin + _eq_well_y(xn, height)))
    path = "M " + " L ".join(f"{x:.1f},{y:.1f}" for x, y in curve_pts)
    fill_path = path + f" L {px_of(1):.1f},{height:.1f} L {px_of(-1):.1f},{height:.1f} Z"

    parts = [
        f'<path d="{fill_path}" fill="rgba(58,74,92,0.10)"/>',
        f'<path d="{path}" fill="none" stroke="rgba(58,74,92,0.9)" stroke-width="2"/>',
        f'<line x1="{cx:.1f}" y1="{baseline_y + 10:.1f}" x2="{cx:.1f}" y2="{top_margin - 24:.1f}" '
        f'stroke="rgba(79,216,232,0.35)" stroke-width="1" stroke-dasharray="3,5"/>',
        f'<text x="{px_of(-1):.1f}" y="{top_margin - 30:.1f}" font-size="10" '
        f'font-family="IBM Plex Mono, monospace" fill="#6B7280">RSI 0</text>',
        f'<text x="{cx:.1f}" y="{top_margin - 30:.1f}" text-anchor="middle" font-size="10" '
        f'font-family="IBM Plex Mono, monospace" fill="#6B7280">RSI 50 · equilibrium</text>',
        f'<text x="{px_of(1):.1f}" y="{top_margin - 30:.1f}" text-anchor="end" font-size="10" '
        f'font-family="IBM Plex Mono, monospace" fill="#6B7280">RSI 100</text>',
    ]

    for a in frame_assets:
        x, r, color, dom_id = a["x"], a["bubble_r"], a["color"], a["id"]
        px, py = px_of(x), py_of(x, r)
        parts.append(
            f'<circle id="b-{dom_id}" cx="{px:.1f}" cy="{py:.1f}" r="{r:.2f}" fill="{color}" '
            f'fill-opacity="0.30" stroke="{color}" stroke-width="1.6" class="eq-bubble"/>'
        )
        parts.append(
            f'<text id="l-{dom_id}" x="{px:.1f}" y="{py - r - 8:.1f}" text-anchor="middle" font-size="11" '
            f'font-weight="600" font-family="IBM Plex Mono, monospace" fill="{color}" class="eq-label">{html.escape(a["name"])}</text>'
        )
        parts.append(
            f'<text id="r-{dom_id}" x="{px:.1f}" y="{py + r + 14:.1f}" text-anchor="middle" font-size="10" '
            f'font-family="IBM Plex Mono, monospace" fill="rgba(232,230,222,0.55)" class="eq-rsi">{a["rsi"]:.0f}</text>'
        )

    return (
        f'<svg viewBox="0 0 {width} {height}" preserveAspectRatio="xMidYMid meet" role="img" '
        f'aria-label="Equilibrium RSI, scrub the slider to replay the last {EQUILIBRIUM_HISTORY_HOURS} hours">'
        f'{"".join(parts)}</svg>'
    )


EQUILIBRIUM_CSS = """
  #app{
    --bg:#0B0E14; --well:#3A4A5C; --neutral:#9CA3AF; --cyan:#4FD8E8;
    --red:#FF5C5C; --green:#3ECF8E; --ink:#E8E6DE; --dim:#6B7280;
    --panel:#111621; --line:#1E2633;
    display:flex; flex-direction:column; background:var(--bg); color:var(--ink);
    font-family:'Space Grotesk',sans-serif;
  }
  #app, #app *{box-sizing:border-box; margin:0; padding:0;}
  #app .mono{font-family:'IBM Plex Mono',monospace;}
  #app header{ padding:20px 28px 14px; display:flex; align-items:baseline;
    justify-content:space-between; border-bottom:1px solid var(--line); flex-shrink:0; flex-wrap:wrap; gap:8px;}
  #app .eyebrow{ font-family:'IBM Plex Mono',monospace; font-size:11px; letter-spacing:.18em;
    color:var(--cyan); text-transform:uppercase; }
  #app h1{font-size:22px; font-weight:600; letter-spacing:-0.01em; margin-top:2px;}
  #app .status{font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--dim); text-align:right; line-height:1.6;}
  #app .status b{color:var(--cyan); font-weight:500;}
  #app main{flex:1; display:flex; min-height:0; flex-wrap:wrap;}
  #app #stage-wrap{flex:1 1 560px; position:relative; min-width:0; padding:16px; display:flex; flex-direction:column; gap:10px;}
  #app #stage-wrap svg{display:block; width:100%; height:auto;}
  #app #stage-wrap svg .eq-bubble{ transition: cx 0.35s ease, cy 0.35s ease, r 0.35s ease, fill 0.35s ease, stroke 0.35s ease; }
  #app #stage-wrap svg .eq-label,
  #app #stage-wrap svg .eq-rsi{ transition: x 0.35s ease, y 0.35s ease, fill 0.35s ease; }
  #app #hud{ display:flex; justify-content:space-between; padding:0 8px;
    font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--dim); }
  #app .side-label{display:flex; flex-direction:column; gap:2px;}
  #app .side-label .n{font-size:22px; font-weight:600;}
  #app .side-label.left{text-align:left; color:var(--red);}
  #app .side-label.right{text-align:right; color:var(--green);}
  #app .side-label.left .n{color:var(--red);}
  #app .side-label.right .n{color:var(--green);}
  #app #scrubber{ padding:4px 12px 0; display:flex; flex-direction:column; gap:6px; }
  #app #scrubber .scrub-row{ display:flex; align-items:center; gap:12px; }
  #app #scrubber input[type=range]{ flex:1; -webkit-appearance:none; height:3px; background:var(--line); border-radius:2px; outline:none; }
  #app #scrubber input[type=range]::-webkit-slider-thumb{ -webkit-appearance:none; width:14px; height:14px; border-radius:50%; background:var(--cyan); cursor:pointer; border:2px solid var(--bg); }
  #app #scrubber input[type=range]::-moz-range-thumb{ width:14px; height:14px; border-radius:50%; background:var(--cyan); cursor:pointer; border:2px solid var(--bg); }
  #app #scrubLabel{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--cyan); white-space:nowrap; min-width:9ch; text-align:right; }
  #app #scrubTs{ font-family:'IBM Plex Mono',monospace; font-size:10.5px; color:var(--dim); text-align:center; }
  #app aside{ width:280px; flex-shrink:0; background:var(--panel); border-left:1px solid var(--line);
    padding:24px 22px; display:flex; flex-direction:column; gap:16px; }
  #app #legend{display:flex; flex-direction:column; gap:6px;}
  #app .leg-row{display:flex; justify-content:space-between; align-items:center;
    font-family:'IBM Plex Mono',monospace; font-size:12px; padding:4px 0; border-bottom:1px solid var(--line);}
  #app .leg-row .dot{width:8px; height:8px; border-radius:50%; display:inline-block; margin-right:8px;}
  #app .leg-row .rsi{font-weight:600;}
  #app .leg-row .pct{color:var(--dim); font-size:10.5px; margin-left:8px;}
  #app .note{font-size:11.5px; color:var(--dim); line-height:1.6; padding-top:6px; border-top:1px solid var(--line);}
  #app .note b{color:var(--ink);}
  #app .back-link{ font-family:'IBM Plex Mono',monospace; font-size:11px; color:var(--dim);
    text-decoration:none; border:1px solid var(--line); border-radius:6px; padding:6px 10px; }
  #app .back-link:hover{ color:var(--cyan); border-color:var(--cyan); }
  @media (max-width: 760px){ #app aside{ width:100%; border-left:none; border-top:1px solid var(--line);} }
"""


def _equilibrium_slider_script(frames, dom_ids):
    """JS that replays real precomputed hourly frames as the slider moves --
    no physics, no randomness, no invented values: every position it can
    show is one of the `frames` computed by build_equilibrium_history. CSS
    transitions (see EQUILIBRIUM_CSS's .eq-bubble/.eq-label/.eq-rsi rules)
    are what make moving the slider feel animated instead of a hard cut."""
    frames_json = json.dumps(frames)
    ids_json = json.dumps(dom_ids)
    return f"""
  const EQ_FRAMES = {frames_json};
  const EQ_IDS = {ids_json};
  const EQ_W = {EQUILIBRIUM_SVG_WIDTH}, EQ_H = {EQUILIBRIUM_SVG_HEIGHT};
  const EQ_CX = EQ_W / 2, EQ_SCALE_X = EQ_W * 0.44, EQ_TOP = EQ_H * 0.30;
  function eqWellY(xn){{ const depth = 1 - xn*xn; return EQ_H*0.28 + depth*EQ_H*0.42; }}
  function eqPxOf(x){{ return EQ_CX + x*EQ_SCALE_X; }}
  function eqPyOf(x, r){{ return EQ_TOP + eqWellY(x) - 10 - r; }}

  const slider = document.getElementById('hourSlider');
  const scrubLabel = document.getElementById('scrubLabel');
  const scrubTs = document.getElementById('scrubTs');
  const leftCountEl = document.getElementById('leftCount');
  const rightCountEl = document.getElementById('rightCount');
  const legendEl = document.getElementById('legend');

  function renderFrame(frameIdx){{
    const frame = EQ_FRAMES[frameIdx];
    let left = 0, right = 0;
    frame.assets.forEach(a => {{
      const px = eqPxOf(a.x), py = eqPyOf(a.x, a.bubble_r);
      const bubble = document.getElementById('b-' + a.id);
      const label = document.getElementById('l-' + a.id);
      const rsiText = document.getElementById('r-' + a.id);
      if (bubble) {{
        bubble.setAttribute('cx', px); bubble.setAttribute('cy', py); bubble.setAttribute('r', a.bubble_r);
        bubble.setAttribute('fill', a.color); bubble.setAttribute('stroke', a.color);
      }}
      if (label) {{ label.setAttribute('x', px); label.setAttribute('y', py - a.bubble_r - 8); label.setAttribute('fill', a.color); }}
      if (rsiText) {{ rsiText.setAttribute('x', px); rsiText.setAttribute('y', py + a.bubble_r + 14); rsiText.textContent = Math.round(a.rsi); }}
      if (a.x < -0.02) left++; else if (a.x > 0.02) right++;
    }});
    leftCountEl.textContent = left;
    rightCountEl.textContent = right;
    scrubTs.textContent = frame.ts ? ('Showing: ' + frame.ts) : 'Showing: n/a';
    const hoursAgo = EQ_FRAMES.length - 1 - frameIdx;
    scrubLabel.textContent = hoursAgo === 0 ? 'Current hour' : (hoursAgo + 'h ago');
    const rows = frame.assets.slice().sort((a, b) => b.rsi - a.rsi).map(a => {{
      const pctStr = (a.pct3h === null || a.pct3h === undefined) ? 'n/a' : (a.pct3h >= 0 ? '+' : '') + a.pct3h.toFixed(2) + '% 3h';
      return '<div class="leg-row"><span><span class="dot" style="background:' + a.color + '"></span>' + a.name +
        '</span><span><span class="rsi" style="color:' + a.color + '">' + Math.round(a.rsi) +
        '</span><span class="pct">' + pctStr + '</span></span></div>';
    }});
    legendEl.innerHTML = rows.join('');
  }}

  slider.addEventListener('input', () => renderFrame(+slider.value));
  renderFrame(+slider.value);
"""


def render_equilibrium_app(assets, now, embedded=False):
    """Build the `<div id="app">...</div>` markup for the Equilibrium -- RSI
    Reversion view: a real-data hour-by-hour replay (slider from
    EQUILIBRIUM_HISTORY_HOURS hours ago to the current hour), each of the 6
    core assets plotted at that hour's real RSI, end bubble sized relative
    to the other 5 AT THAT HOUR. No simulated/invented motion anywhere --
    every slider position shows an actual past reading; client-side JS only
    looks up the frame for the slider's position and moves elements to
    match (a CSS transition makes that read as motion, not a jump cut).

    `embedded=True` drops the "back to report" link (pointless when this is
    already part of the same page) and gives the panel a fixed height that
    fits inside a scrolling page instead of claiming the full viewport.
    Returns just the markup -- EQUILIBRIUM_CSS (scoped entirely under
    `#app`, safe to concatenate into any page's <style>) is a separate
    constant so callers embedding this include it in their own <style> tag
    exactly once."""
    as_of = now.strftime("%Y-%m-%d %H:%M UTC")
    history = build_equilibrium_history(assets)
    min_height = "560px" if embedded else "100vh"
    nav_html = "" if embedded else '<a class="back-link" href="index.html">&larr; Back to report</a>'

    if history is None:
        body = f"""
    <div style="padding:60px 28px; color:var(--dim); font-family:'IBM Plex Mono',monospace; font-size:13px;">
      Live RSI history wasn't fully available for all 6 assets this run ({html.escape(as_of)}).
      This page will populate on the next hourly run once every asset has enough hourly bars.
    </div>"""
    else:
        frames = history["frames"]
        current = frames[-1]
        max_hours_back = len(frames) - 1
        dom_ids = [a["id"] for a in current["assets"]]
        svg = render_equilibrium_svg(current["assets"])

        def _eq_legend_row(a):
            pct_str = "n/a" if a["pct3h"] is None else f'{a["pct3h"]:+.2f}% 3h'
            return (
                f'<div class="leg-row"><span><span class="dot" style="background:{a["color"]}"></span>'
                f'{html.escape(a["name"])}</span>'
                f'<span><span class="rsi" style="color:{a["color"]}">{a["rsi"]:.0f}</span>'
                f'<span class="pct">{pct_str}</span></span></div>'
            )

        legend_html = "".join(
            _eq_legend_row(a) for a in sorted(current["assets"], key=lambda a: a["rsi"], reverse=True)
        )
        left_count = sum(1 for a in current["assets"] if a["x"] < -0.02)
        right_count = sum(1 for a in current["assets"] if a["x"] > 0.02)
        script = _equilibrium_slider_script(frames, dom_ids)

        body = f"""
    <div id="stage-wrap">
      {svg}
      <div id="hud">
        <div class="side-label left">OVERSOLD (RSI &lt; 50)<div class="n" id="leftCount">{left_count}</div></div>
        <div class="side-label right">OVERBOUGHT (RSI &gt; 50)<div class="n" id="rightCount">{right_count}</div></div>
      </div>
      <div id="scrubber">
        <div class="scrub-row">
          <input type="range" id="hourSlider" min="0" max="{max_hours_back}" value="{max_hours_back}">
          <span id="scrubLabel">Current hour</span>
        </div>
        <div id="scrubTs">Showing: {html.escape(current["ts"] or "n/a")}</div>
      </div>
    </div>
    <aside>
      <div id="legend">{legend_html}</div>
      <div class="note">
        Six assets — <b>DXY, Bonds, SPY, NASDAQ, GOLD, WTI Crude</b> — plotted
        by real hourly <b>RSI(14)</b>. Drag the slider to replay the last
        {max_hours_back} hours, hour by hour — every position is an actual
        past reading pulled from real hourly closes, not invented or
        simulated motion. RSI 50 is equilibrium; the well steepens toward 0
        and 100. <b>Green</b> = overbought side. <b>Red</b> = oversold side.
        <br><br>
        Each bubble's size is the inverse of that asset's |% change over the
        prior 3 hourly candles|, <b>relative to the other five at that same
        hour</b> — the quietest of the six that hour gets the biggest
        bubble, the most volatile gets the smallest.
      </div>
    </aside>
<script>{script}</script>"""

    return f"""<div id="app" style="min-height:{min_height};">
  <header>
    <div>
      <div class="eyebrow">RSI Reversion</div>
      <h1>Equilibrium</h1>
    </div>
    <div class="status mono">
      N = 6 assets · generated {html.escape(as_of)}<br>
      {nav_html}
    </div>
  </header>
  <main>{body}
  </main>
</div>"""


def generate_equilibrium_html(assets, now):
    """Standalone Equilibrium page (own doctype/head/body) -- same content
    as the block embedded at the bottom of the main report by render_html(),
    just as its own full document for direct linking / GitHub Pages."""
    app_html = render_equilibrium_app(assets, now, embedded=False)
    return f"""<!doctype html>
<html lang="en">
<head>
<meta charset="UTF-8">
<title>Equilibrium — RSI Reversion</title>
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:wght@400;500;600&family=Space+Grotesk:wght@400;500;600;700&display=swap" rel="stylesheet">
<style>{EQUILIBRIUM_CSS}
  body{{ margin:0; background:#0B0E14; }}
</style>
</head>
<body>
{app_html}
</body>
</html>
"""


def send_ntfy(text, topic):
    url = f"https://ntfy.sh/{topic}"
    req = urllib.request.Request(url, data=text.encode("utf-8"), method="POST",
                                  headers={"Title": "Money Flow Snapshot"})
    try:
        with urllib.request.urlopen(req, timeout=10) as resp:
            print(f"ntfy: posted, status {resp.status}")
    except Exception as e:
        print(f"ntfy: FAILED to post: {e}", file=sys.stderr)


def main():
    report, assets, now = build_report()
    futures = build_futures()
    full_report = report + "\n\n" + "\n".join(render_futures_text(futures))
    print(full_report)

    summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
    if summary_path:
        with open(summary_path, "a") as f:
            f.write("## Money Flow Snapshot\n\n```\n" + full_report + "\n```\n")

    # Plain-text report (cross-asset section unchanged, futures watchlist
    # appended below it), read by e.g. a Claude scheduled task that fetches
    # the public raw URL without needing GitHub API/auth.
    with open("latest.txt", "w") as f:
        f.write(full_report + "\n")

    # Self-contained HTML visual, always up to date in the repo. Name it
    # index.html so it also works out of the box if you enable GitHub Pages
    # (Settings -> Pages -> Deploy from branch -> main -> / (root)).
    with open("index.html", "w") as f:
        f.write(render_html(assets, now, futures))

    # Equilibrium -- RSI Reversion: same 6 core assets, seeded each run from
    # their live current hourly RSI(14).
    with open("equilibrium.html", "w") as f:
        f.write(generate_equilibrium_html(assets, now))

    topic = os.environ.get("NTFY_TOPIC")
    if topic:
        send_ntfy(full_report, topic)
    else:
        print("[info] NTFY_TOPIC not set -- skipping push notification.")


if __name__ == "__main__":
    main()
