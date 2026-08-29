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
  date/time x-axis. Each RSI line ends in a bubble sized by **market size**
  — trailing average dollar volume (`volume × close`, averaged over the
  trailing window) — **relative to the other items in that same section,
  that run** — never on a fixed/absolute scale, and never mixed across
  sections:
  - Top card: each run, the 7 assets' trailing 20-day average dollar
    volumes are min-max normalized against just those 7
    (`add_asset_rsi_and_relative_bubbles()`).
  - Futures watchlist: normalized separately across just the ~35 futures
    instruments, from their trailing hourly dollar volume
    (`compute_relative_bubble_radii()`).

  In both cases the single biggest-volume item that run gets the biggest
  bubble and the single smallest gets the smallest, so each section always
  shows a full range of bubble sizes instead of clustering at one end.
  DX-Y.NYB (the dollar index) has no real trading volume of its own — it's
  a spot/cash index, not a traded security — so it's automatically tied
  with whichever instrument in its section has the largest *measured*
  volume, rather than being penalized as the smallest (see "Notes" below
  for the earlier |% change|-based convention this replaced, and why).

  Dollar volume is `volume × close × contract multiplier` — the multiplier
  matters a lot for futures: e.g. ZN=F (10-Year T-Note futures) trades
  around 111 with a $1,000/point contract, while ES=F trades around 5600
  with a $50/point contract, so `volume × close` alone would make one of
  the world's most liquid futures contracts (backing the ~$27T Treasury
  market) look like a fraction of the S&P 500 futures market's size, purely
  because of how it happens to be quoted. `FUTURES_CONTRACT_MULTIPLIER` in
  `money_flow.py` corrects for this per symbol.
- **Equilibrium — RSI Reversion**, embedded directly at the bottom of
  `index.html` (the "Equilibrium view ↓" link at the top jumps straight to
  it — no separate page to open): DXY, the 10Y note (BONDS), ES=F (SPY),
  NQ=F (NASDAQ), gold, and WTI crude, each plotted along an RSI potential
  well — the same tickers the main snapshot already pulls. The same content
  is also still generated as its own standalone `equilibrium.html`, if you
  want a page to link to directly instead of scrolling.

  There are now **four stacked panels**, each with its own slider, covering
  both time intervals and both bubble-sizing conventions:

  1. **Hourly — legacy sizing (|% change|)**
  2. **Daily — legacy sizing (|% change|)**
  3. **Hourly — market size ($ volume)**
  4. **Daily — market size ($ volume)**

  The legacy panels keep the *original* convention (bubble = inverse of
  |% change over the prior 3 candles| — the quietest mover gets the biggest
  bubble); the market-size panels use the same trailing-average-dollar-volume
  convention now used everywhere else in this report. Both are kept side by
  side rather than one replacing the other, since they answer different
  questions ("what's moved the least lately" vs. "what's actually the
  biggest market") and can diverge sharply -- e.g. a heavily-traded but
  currently quiet instrument gets a big bubble on both, while a heavily
  *moving* but small/thin instrument gets a big bubble only on the legacy
  panel. All four are built by the same shared core
  (`_build_equilibrium_frames()` in `money_flow.py`, with a `sizing`
  parameter of `"legacy"` or `"volume"`), called by `build_equilibrium_history()`
  for hourly and `build_equilibrium_history_daily()` for daily. Hourly
  panels scrub from 20 hours ago to the current hour; daily panels scrub
  from 20 trading days ago to today.

  There is **no simulation anywhere** on any panel — every slider position
  replays an actual past RSI(14) reading computed from real closes of that
  interval, not invented motion. The only client-side JS is a lookup that
  moves each bubble to the position/size for whichever candle the slider
  points at; a CSS transition on the SVG elements is what makes that read
  as motion rather than a jump cut. Every asset's bubble on every panel is
  sized relative to the other five **at that same candle, on that same
  panel**; DXY (no real volume of its own) is tied with whichever of the
  six has the largest measured volume on the market-size panels. All four
  panels are sized independently of each other (see "Notes" below) — a
  bubble on one panel is never on the same scale as a bubble on another. If
  an asset doesn't have enough history yet for a panel's full window, that
  panel's slider range shrinks to however many real candles are actually
  available rather than padding with fake ones; if an asset is missing that
  interval's history entirely, that panel shows an "unavailable, will
  populate next run" message instead of breaking the rest of the page (the
  other three panels keep working normally).

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
- Bubble sizing is **market size**, not price movement, everywhere except
  the two legacy Equilibrium panels described below. Earlier versions of
  this report sized every bubble as the inverse of |% change| (quietest
  mover = biggest bubble), on the reasoning that big markets tend to move
  less -- but that conflates "quiet right now" with "large," which isn't
  reliably true (a small, illiquid instrument can be just as quiet). Bubble
  size on the top card, the futures board, and the two market-size
  Equilibrium panels is trailing **average dollar volume**
  (`volume × close × contract multiplier`, averaged over a trailing window)
  — a direct measure of how much money is actually changing hands in that
  instrument, independent of how much its price is moving. RSI positioning
  (on the trendline and on the Equilibrium wells) is untouched by this
  change; only bubble *size* uses volume instead of |% change| on those
  panels. See `avg_dollar_volume()` and
  `compute_relative_bubble_radii_from_dollar_volume()` in `money_flow.py`.
  The old |% change|-based path (`compute_relative_bubble_radii_from_pcts()`,
  `bubble_radius_from_pct()`) is kept in the code and is still actively used
  by the two legacy Equilibrium panels (see below) — it's no longer the
  default for the top card or futures board, but it isn't just a rollback
  path anymore either.
- Futures (and the ES=F/NQ=F/ZN=F/GC=F/CL=F assets on the top card) are
  quoted at wildly different point levels for reasons that have nothing to
  do with market size -- e.g. ZN=F (10-Year T-Note futures) trades around
  111 while ES=F trades around 5600 -- so `volume × close` alone would
  understate a contract's true notional size whenever it happens to be
  quoted at a low point level. `FUTURES_CONTRACT_MULTIPLIER` (with
  `contract_multiplier_for()`) in `money_flow.py` corrects for this per
  symbol before the dollar-volume comparison happens, using each contract's
  standard exchange-defined dollar-per-point value. The Equity
  Index/Treasuries/Metals/Energy entries are standard, essentially-fixed CME/
  ICE contract specs; the Agriculture/Livestock/Softs entries are best-effort
  (Yahoo's cents-vs-dollars quoting convention for those isn't always
  obvious, and a couple of these contracts have been resized by the exchange
  in the past, e.g. CME's 2023 lumber contract redesign) -- worth
  spot-checking against a real run.
- There are now **six independent bubble-sizing scopes**, each its own
  min-max normalization with its own set of instruments, sharing the same
  generalized core, `compute_relative_bubble_radii_from_values()` in
  `money_flow.py`:
  - Top Cross-asset card: the 7 core assets' trailing 20-day average dollar
    volume, via `add_asset_rsi_and_relative_bubbles()`.
  - Futures watchlist: the ~35 futures instruments' trailing average hourly
    dollar volume over the fetched window, via
    `compute_relative_bubble_radii()`.
  - Equilibrium — Hourly, legacy sizing: its own 6 assets' inverse
    |% change over the prior 3 candles|, independently per hour.
  - Equilibrium — Daily, legacy sizing: the same 6 assets' inverse
    |% change over the prior 3 candles|, independently per day.
  - Equilibrium — Hourly, market-size sizing: the same 6 assets' trailing
    20-hour average dollar volume, independently per hour.
  - Equilibrium — Daily, market-size sizing: the same 6 assets' trailing
    20-day average dollar volume, independently per day.

  All four Equilibrium panels are built by the same shared core,
  `_build_equilibrium_frames()`, called via `build_equilibrium_history()`
  (hourly) and `build_equilibrium_history_daily()` (daily), each with a
  `sizing` argument of `"legacy"` or `"volume"` that picks which of the two
  metrics drives that panel's bubble size — both metrics are always computed
  per candle regardless of which one is active, so switching a panel's
  `sizing` back and forth doesn't need any new data.

  None of these six are on a shared scale with each other -- a bubble on the
  top card can't be compared in size to a bubble on the futures board or any
  Equilibrium panel, and none of the four Equilibrium panels are on a shared
  scale with any other -- only to the other bubbles in its own
  section/panel, at that same candle, that run.
- **DX-Y.NYB has no real trading volume** — it's the ICE spot/cash dollar
  index, not itself a traded security, so Yahoo reports zero volume for it
  on every bar. Rather than let that collapse its bubble to the smallest
  size in its section (implying the dollar/FX market is small, which is the
  opposite of true), `_fill_unmeasured_size_with_section_max()` treats any
  instrument with zero/missing volume as tied with whichever instrument in
  the same section has the largest *measured* volume that run. This applies
  generically to any instrument that turns out to have unusable volume
  data, not just DXY.
- If you'd rather size bubbles by real notional market size instead of
  traded volume for a specific instrument -- e.g. a hardcoded reference like
  BIS's ~$7.5T/day global FX turnover estimate for DXY, or total Treasury
  debt outstanding for ZN=F -- that's a fixed weight you'd look up
  periodically and substitute directly into the relevant `..._by_key`/
  `..._by_ticker` dict before normalizing, rather than something to fetch
  fresh each run; true open interest (total outstanding futures contracts)
  would need a paid data feed (CME DataMine, Barchart, Nasdaq Data Link),
  since it isn't in yfinance's free data.
- The 20-hour and 20-trading-day windows are constants
  (`EQUILIBRIUM_HISTORY_HOURS` / `EQUILIBRIUM_HISTORY_DAYS` in
  `money_flow.py`) — change either if you want a longer or shorter lookback
  on that panel. The daily panel's underlying daily bars come from the same
  `fetch_daily()` call already used for the 3-day/30-day window metrics
  (`ohlc_list_from_hist()` reshapes that into the same OHLC format the
  hourly panel uses) -- no extra network call per run.
- `yfinance` volume data is generally reliable at the daily interval but can
  be sparse or zero for some futures symbols at the hourly interval
  (Yahoo's intraday futures volume reporting is known to be inconsistent) —
  every bubble-sizing call site already degrades gracefully via
  `_fill_unmeasured_size_with_section_max()` if this happens for a given
  instrument on a given run.
- This is an informational tool, not financial advice.
