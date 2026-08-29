# Money Flow Snapshot (updated)

Cross-asset snapshot (S&P 500/ES futures, US 10Y yield, DXY, gold, Bitcoin) with
direction + magnitude tags, a full ~35-symbol futures board, and an
"Equilibrium" RSI-reversion view — all run hourly via GitHub Actions and
committed back into this repo as static HTML.

This is an updated fork of the original `moneyflow` repo. What's new here:

- **Hourly RSI trendline + end bubble**, laid out side by side with the price
  chart, on BOTH the top Cross-asset money flow card (the 7 core assets --
  ES=F, NQ=F, ZN=F, DXY, GC=F, CL=F, BTC-USD) and every instrument in the
  Futures watchlist (equity index, treasuries, metals, energy, agriculture,
  livestock, softs — ~35 symbols). Both charts on a row share the same
  date/time x-axis. Each RSI line ends in a bubble sized **relative to the
  other items in that same section, that run** — never on a fixed/absolute
  scale, and never mixed across sections:
  - Top card: each hour, the 7 assets' absolute 3-hour % changes are
    min-max normalized against just those 7 (`add_asset_rsi_and_relative_bubbles()`).
  - Futures watchlist: normalized separately across just the ~35 futures
    instruments (`compute_relative_bubble_radii()`).

  In both cases the single quietest item that run gets the biggest bubble
  and the single most volatile gets the smallest, so each section always
  shows a full range of bubble sizes instead of clustering at one end. See
  "Notes" below for the shared sizing logic these both call.
- **Equilibrium — RSI Reversion**, embedded directly at the bottom of
  `index.html` (the "Equilibrium view ↓" link at the top jumps straight to
  it — no separate page to open): DXY, the 10Y note (BONDS), ES=F (SPY),
  NQ=F (NASDAQ), gold, and WTI crude, each plotted along an RSI potential
  well — the same tickers the main snapshot already pulls. The same content
  is also still generated as its own standalone `equilibrium.html`, if you
  want a page to link to directly instead of scrolling.

  There are now **two stacked panels**, each with its own slider, one below
  the other: an **Hourly** panel (unchanged from before) and a **Daily**
  panel underneath it using the exact same setup on daily candles instead of
  hourly ones. Hourly scrubs from 20 hours ago to the current hour; Daily
  scrubs from 20 trading days ago to today. Both are built by the same
  shared core (`_build_equilibrium_frames()` in `money_flow.py`, called once
  per interval by `build_equilibrium_history()` for hourly and
  `build_equilibrium_history_daily()` for daily).

  There is **no simulation anywhere** on either panel — every slider
  position replays an actual past RSI(14) reading computed from real closes
  of that interval, not invented motion. The only client-side JS is a
  lookup that moves each bubble to the position/size for whichever candle
  the slider points at; a CSS transition on the SVG elements is what makes
  that read as motion rather than a jump cut. On each panel, every asset's
  bubble is sized relative to the other five **at that same candle** —
  inverse of |% change over the prior 3 candles of that panel's interval| —
  so the quietest of the six that hour/day gets the biggest bubble and the
  most volatile gets the smallest, same convention as the futures watchlist
  and top-card bubbles. The Hourly and Daily panels are sized independently
  of each other (see "Notes" below) — a bubble on one panel is never on the
  same scale as a bubble on the other. If an asset doesn't have enough
  history yet for a panel's full window, that panel's slider range shrinks
  to however many real candles are actually available rather than padding
  with fake ones; if an asset is missing that interval's history entirely,
  the panel shows an "unavailable, will populate next run" message instead
  of breaking the rest of the page (the other panel keeps working normally).

## Setup (5 minutes)

1. This folder is already the repo root — just push it:
   ```bash
   cd moneyflow-update
   git remote add origin https://github.com/danreed001-droid/moneyflow-update.git
   git branch -M main
   git add -A
   git commit -m "Initial commit"
   git push -u origin main
   ```

2. (Optional but recommended) Get push notifications for free via
   [ntfy.sh](https://ntfy.sh) — no signup required:
   - Pick a topic name only you would guess, e.g. `bob-money-flow-8f3k2`.
   - Install the ntfy app (iOS/Android) or open `https://ntfy.sh/<your-topic>` in
     a browser and subscribe.
   - In your GitHub repo: **Settings -> Secrets and variables -> Actions -> New
     repository secret**, name it `NTFY_TOPIC`, value = your topic name.
   - Without this secret, the workflow still runs and prints the report to the
     Actions log / job summary — you just won't get a push notification.

3. The workflow (`.github/workflows/money-flow.yml`) is scheduled hourly. You
   can also trigger it manually any time from the repo's **Actions** tab ->
   "Money Flow Snapshot" -> **Run workflow**. The first run writes
   `index.html`, `latest.txt`, and `equilibrium.html` — until then those
   files don't exist yet in this repo.

4. (Optional) Enable GitHub Pages (Settings -> Pages -> Deploy from branch ->
   main -> / (root)) to view `index.html` / `equilibrium.html` at a public
   URL instead of opening the raw files.

## Notes

- Cron times are UTC and don't auto-shift for US Daylight Saving Time.
- `yfinance` pulls from Yahoo's public data; it's free and reliable enough for
  this kind of snapshot, but it is still an unofficial API, so an occasional
  failed run is possible. `workflow_dispatch` lets you re-run manually if one
  fails.
- The RSI bubble sizing is relative and inverted on purpose — it highlights
  which instruments have gone quiet relative to their peers, not which ones
  are moving the most. All four sections below call the same shared core,
  `compute_relative_bubble_radii_from_pcts()` in `money_flow.py`, each with
  its own set of instruments and its own independent min-max normalization:
  - Top Cross-asset card: the 7 core assets, via
    `add_asset_rsi_and_relative_bubbles()`.
  - Futures watchlist: the ~35 futures instruments, via
    `compute_relative_bubble_radii()`.
  - Equilibrium — Hourly panel: its own 6 assets, independently per hour,
    via `build_equilibrium_history()`.
  - Equilibrium — Daily panel: the same 6 assets on daily closes,
    independently per day, via `build_equilibrium_history_daily()`.

  None of these four are on a shared scale with each other -- a bubble on
  the top card can't be compared in size to a bubble on the futures board or
  either Equilibrium panel, and the Hourly and Daily Equilibrium panels
  aren't on a shared scale with each other either -- only to the other
  bubbles in its own section/panel that run. `bubble_radius_from_pct()` is
  the non-relative fallback used only when fewer than two items in a given
  section have usable 3-candle data to normalize against.
- The 20-hour and 20-trading-day windows are constants
  (`EQUILIBRIUM_HISTORY_HOURS` / `EQUILIBRIUM_HISTORY_DAYS` in
  `money_flow.py`) — change either if you want a longer or shorter lookback
  on that panel. The daily panel's underlying daily bars come from the same
  `fetch_daily()` call already used for the 3-day/30-day window metrics
  (`ohlc_list_from_hist()` reshapes that into the same OHLC format the
  hourly panel uses) -- no extra network call per run.
- This is an informational tool, not financial advice.
