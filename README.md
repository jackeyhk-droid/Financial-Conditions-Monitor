# 金融狀況 / 風險體制監測 · Financial Conditions & Risk-Regime Monitor

A FRED-backed dashboard that reads the **rates + credit + real-yield + vol + liquidity**
complex as a leading **risk-regime** monitor. Mirrors the Macro Monitor pipeline:
**GitHub Action (cron) → FRED (+ Yahoo Finance) → `data.json` → Vercel**, single
self-contained HTML, Bloomberg-dark, bilingual TC/EN, SHA-256 gate.

> **What it is for:** identifying the regime, flagging tail risk, confirming/disconfirming
> equity momentum, and leading recession risk. **Not** a market-timing oracle — the lead
> times are long and variable, and credit can decouple from equities in a melt-up.

---

## Files

| File | Purpose |
|---|---|
| `index.html` | The dashboard. Loads `./data.json` at runtime; falls back to an embedded seed if absent. |
| `fetch_fred.py` | Pulls ~28 FRED series + MOVE/S&P (yfinance), computes spreads / z-scores / regime / composite, writes `data.json`. |
| `data.json` | Seed data (committed so the dashboard renders immediately). Overwritten by the Action. |
| `.github/workflows/update-fred-data.yml` | Weekday cron that refreshes `data.json`. |

---

## Setup

### 1. FRED API key (reuse your existing secret)
The script prefers the official FRED API when `FRED_API_KEY` is set, and **honors
`observation_start`** → full history back to **2018**. In the repo: **Settings → Secrets and
variables → Actions → New repository secret**, name `FRED_API_KEY`. (Same secret your Macro
Monitor uses — reuse it.)

> **Seed note:** the committed `data.json` was generated **keyless** via the public
> `fredgraph.csv` endpoint, which caps the ICE BofA credit (OAS) series to ~3 years. Once the
> Action runs **with the key**, all series — including credit — backfill to 2018. No code
> change needed.

### 2. Data sources
- **FRED** — yields, spreads, real yields, breakevens, VIX, NFCI (+sub-indices), STLFSI4, the
  plumbing series (ON RRP `RRPONTSYD`, `SOFR`, `EFFR`), the **10Y decomposition** (`THREEFY10`
  fitted yield + `THREEFYTP10` ACM term premium → expected-rate-path), the **broad dollar index**
  (`DTWEXBGS`), and the **NBER recession indicator** (`USREC`, used to draw recession shading).
- **Yahoo Finance (yfinance)** — **MOVE** (`^MOVE`, rate vol; not on FRED) and **S&P 500**
  (`^GSPC`, full history + real-time; FRED's `SP500` is copyright-capped to ~10yr and delayed).
  Both are resilient: if Yahoo is unreachable in CI, MOVE is simply dropped (gauge weights
  renormalize) and S&P falls back to FRED `SP500`.

### 3. Run locally (optional)
```bash
pip install pandas requests numpy yfinance
python fetch_fred.py                       # keyless (3yr credit history)
FRED_API_KEY=xxxxxxxx python fetch_fred.py # full history
```

### 4. Deploy on Vercel
Import the repo as a **static** project (no build step; output = repo root). The dashboard
fetches `./data.json` from the same origin, so every Action commit auto-deploys fresh data.
Suggested project name: `financial-conditions-monitor` or `risk-regime-monitor`.

### 5. Squarespace embed
Full-page takeover via **page-level Code Injection** (not an iframe code-block). Inject the
built HTML as a `.txt` — same method as the Macro Monitor.

### 6. Access gate
SHA-256 password gate (hash embedded; password unchanged from the house standard). Uses
`sessionStorage`. `crypto.subtle` requires a **secure context** — works on Vercel (HTTPS) and
the Squarespace page; not from a raw `file://` open.

---

## Tabs & signals

- **總覽 Overview** — Composite risk gauge (0–100) + component z-bars; **Curve × Credit regime
  matrix** (3-month momentum, 26-week trail, **±0.25σ deadband**); full signal table; methodology.
- **殖利率曲線 Yield Curve** — 2s10s / 3M10Y, raw yields (3M–30Y), 5s30s + 2s5s10s butterfly,
  dis-inversion tracker.
- **信用利差 Credit** — IG / BBB / HY OAS, HY-vs-CCC, CCC−BB dispersion, credit-equity divergence
  (S&P 500 vs inverted HY OAS).
- **實質殖利率·波動 Real & Vol** — 10Y/5Y TIPS real yields, breakevens, **Vol Complex (VIX + MOVE)**,
  10Y real-yield 1M momentum, and **10Y yield decomposition** (expected rate path + term premium).
- **金融狀況 Financial Conditions** — Chicago Fed NFCI + sub-indices, St. Louis Fed stress,
  **plumbing (ON RRP take-up, SOFR−EFFR repo stress)**, **broad USD index**, composite gauge history.

All time-series charts are linked via `echarts.connect()` **and a global time filter** — zooming
any chart (on any tab) sets the window for every chart, including tabs you haven't opened yet, so
replaying a historical episode stays in sync across the whole dashboard. Charts auto-resize via a
`ResizeObserver` when their tab becomes visible.

### Visual & alerting
- **Rolling correlation matrix (Overview)** — 30-day rolling correlation of daily changes across
  SPX / HY OAS / 10Y Real / MOVE / USD, as a heatmap + interpretation + a 52-week SPX×HY sparkline.
  Quantifies credit-equity divergence and flags duration-sensitive regimes (strong SPX×10Y-Real
  negative correlation).
- **Alert banners** below the header translate non-linear breakage conditions into text: MOVE/VIX
  weekly surge, dis-inversion + positive 3M momentum, composite ≥ 70 (or ≥ 58), CCC-BB dispersion
  extreme, term-premium spike, strong-dollar tightening, ON RRP exhausted, SOFR-EFFR repo stress.
  Edit thresholds in `computeAlerts()` in `index.html`.
- **NBER recession shading** (from `USREC`) is drawn on every time chart; zoom out to anchor
  current levels against historical crises.
- **Regime worm** — the regime matrix has an ECharts timeline; press ▶ to replay the last 26
  weeks and read the *acceleration* of momentum, not just the current point.
- **Heatmapped %ile column** in the signal table (orientation-aware: green = benign, red = stress)
  for fast investment-committee scanning.
- Animated gradient title (respects `prefers-reduced-motion`).

### Composite gauge construction
Each component is z-scored (full window), oriented so **(+) = tighter / risk-off**, weighted,
and mapped to 0–100 via `gauge = 50 + 16.67 × z` (clamped):

| Component | Weight |
|---|---|
| HY OAS level | 18% |
| HY OAS 1M momentum | 18% |
| NFCI (tightness) | 14% |
| VIX (equity vol) | 12% |
| MOVE (rate vol) | 12% |
| Curve 3M10Y (inverted = stress) | 9% |
| 10Y real-yield 1M momentum | 9% |
| CCC−BB dispersion | 8% |

VIX and MOVE each carry 12% — VIX is equity tail risk, MOVE is funding-cost tail risk, and
long-duration tech is acutely sensitive to the *speed* of rate moves. Weights renormalize over
whatever series are available. To re-weight or add series, edit the `SERIES`/`YF_SERIES` dicts
and the `add_comp(...)` block in `fetch_fred.py`.

### Regime quadrants + deadband (Curve × Credit, 3M momentum)
- **Steepening + credit tightening →** Reflation / early-cycle 復甦
- **Flattening + credit tightening →** Goldilocks / mid-cycle 金髮女孩
- **Flattening + credit widening →** Late-cycle / stress building 循環末段
- **Steepening + credit widening →** Risk-off / recession dynamics 避險 *(most dangerous)*
- **Either axis within ±0.25σ of its 63-day-change distribution →** Transition 過渡期 — avoids
  whipsawing between adjacent quadrants when moves are tiny. The buffer is drawn as a neutral
  cross at the matrix centre.

---

## Notes
- **IRS / swap spreads were intentionally skipped** — FRED's free swap series (DSWP*) were
  discontinued, so they can't be automated keyless.
- **Needs market data (Bloomberg/Markit), not free on FRED:** true SOFR-OIS / FRA-OIS,
  CDX IG/HY vs OAS liquidity-basis decomposition, and cross-currency basis swaps. `SOFR − EFFR`
  (bps) is included as the closest free repo-stress proxy; the broad USD index is the free
  global-liquidity proxy.
- **Trailing-null tolerance:** ICE BofA OAS series post to FRED ~1 business day late. All
  momentum/z-score math runs on the dropna'd series, so a trailing `null` never corrupts the
  current read.
- Research tool only; not investment advice.

## Architecture roadmap (single-file vs React)
This dashboard is deliberately a **single self-contained `index.html`** because the deploy path is
Squarespace page-level Code Injection (one file, no bundler). That keeps deployment trivial but the
file grows as charts are added. If the dashboard family expands (AI supply-chain, capex maps, sector
ETF boards, etc.), the maintainable path is a **React/JSX build**: a `<ChartCard/>` per indicator, a
`<AlertBanner/>` component, a `useFredData()` hook for fetch/clean, and Zustand/Context for the
global time window (which is hand-rolled here as `gWin`). `echarts-for-react` + `ResizeObserver`
would replace the manual `echarts.init`/`resize` plumbing. Trade-off: a React build needs a bundler
step and a different Vercel config, and the Squarespace embed would consume the built bundle rather
than a single hand-editable file — worth it past ~4–5 dashboards, overkill for one.
