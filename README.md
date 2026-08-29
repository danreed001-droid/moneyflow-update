# Money Flow Snapshot (updated)

Cross-asset snapshot (S&P 500/ES futures, US 10Y yield, DXY, gold, Bitcoin) with
direction + magnitude tags, a full ~35-symbol futures board, and an
"Equilibrium" RSI-reversion view — all run hourly via GitHub Actions and
committed back into this repo as static HTML.

This is an updated fork of the original `moneyflow` repo. What's new here:

- **Hourly RSI trendline + end bubble**, laid out side by side with the price
  chart, for every instrument in the Futures watchlist (equity index,
  treasuries, metals, energy, agriculture, livestock, softs — ~35 symbols).
  Both charts share the same date/time x-axis. Each RSI line ends in a
  bubble sized **relative to the rest of the board that run**: each hour, the
  ~35 instruments' absolute 3-hour % changes are min-max normalized, so the
  single quietest instrument always gets the biggest bubble and the single
  most volatile always gets the smallest — the board always shows a full
  range of bubble sizes instead of clustering at one end.
- **Equilibrium — RSI Reversion**, embedded directly at the bottom of
  `index.html` (the "Equilibrium view ↓" link at the top jumps straight to
  it — no separate page to open): DXY, the 10Y note (BONDS), ES=F (SPY),
  NQ=F (NASDAQ), gold, and WTI crude, each plotted along an RSI potential
  well — the same tickers the main snapshot already pulls. The same content
  is also still generated as its own standalone `equilibrium.html`, if you
  want a page to link to directly instead of scrolling.

  A slider lets you scrub from 20 hours ago up to the current hour. There is
  **no simulation anywhere** — every slider position replays an actual past
  RSI(14) reading computed from real hourly closes (`build_equilibrium_history()`
  in `money_flow.py`), not invented motion. The only client-side JS is a
  lookup that moves each bubble to the position/size for whichever hour the
  slider points at; a CSS transition on the SVG elements is what makes that
  read as motion rather than a jump cut. Each asset's bubble is sized
  relative to the other five **at that same hour** — inverse of |% change
  over the prior 3 hourly candles| — so the quietest of the six that hour
  gets the biggest bubble and the most volatile gets the smallest, same
  convention as the futures watchlist bubbles. If an asset doesn't have
  enough hourly history yet for the full 21-hour window, the slider's range
  shrinks to however many real hours are actually available rather than
  padding with fake ones.

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
  which instruments have gone quiet relative to the rest of the board, not
  which ones are moving the most. See `compute_relative_bubble_radii()` in
  `money_flow.py`; flip `frac_quiet`/`frac_volatile` there if you'd rather
  size bubbles by the size of the move instead. `bubble_radius_from_pct()` is
  the non-relative fallback used only when fewer than two instruments have
  usable 3-hour data to normalize against.
- The Equilibrium page's bubble sizing is normalized across just its own 6
  assets, and independently per hour (`build_equilibrium_history()`),
  separately from the futures board's ~35-instrument normalization — none of
  these are on a shared scale with each other.
- The 20-hour window is a constant (`EQUILIBRIUM_HISTORY_HOURS` in
  `money_flow.py`) — change it if you want a longer or shorter lookback.
- This is an informational tool, not financial advice.
