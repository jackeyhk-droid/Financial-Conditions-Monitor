#!/usr/bin/env python3
"""
FRED data fetcher + analytics for the
金融狀況 / 風險體制監測 · Financial Conditions & Risk-Regime Monitor.

Mirrors the Macro Monitor pipeline:
  - Uses the official FRED API if FRED_API_KEY is set (reuse your existing secret).
  - Falls back to the keyless fredgraph.csv endpoint otherwise (runs anywhere, incl. seeding).
Outputs data.json, consumed at runtime by index.html (fetch('./data.json')).

Run locally to seed:   python fetch_fred.py
In CI (GitHub Action):  FRED_API_KEY=*** python fetch_fred.py
"""
import os, io, json, sys, math, time, datetime as dt
import requests
import pandas as pd
import numpy as np

START   = "2018-01-01"
API_KEY = os.environ.get("FRED_API_KEY", "").strip()
OUT     = os.environ.get("OUT_PATH", "data.json")

# series_id -> (short label EN, label TC)
SERIES = {
    # ---- yield curve (levels, %) ----
    "DGS3MO": ("3M UST",  "3個月公債"),
    "DGS2":   ("2Y UST",  "2年公債"),
    "DGS5":   ("5Y UST",  "5年公債"),
    "DGS10":  ("10Y UST", "10年公債"),
    "DGS30":  ("30Y UST", "30年公債"),
    "T10Y2Y": ("10Y-2Y",  "10年減2年利差"),
    "T10Y3M": ("10Y-3M",  "10年減3個月利差"),
    # ---- credit (OAS, %) ----
    "BAMLC0A0CM":   ("IG OAS",  "投資級利差"),
    "BAMLC0A4CBBB": ("BBB OAS", "BBB利差"),
    "BAMLH0A0HYM2": ("HY OAS",  "高收益利差"),
    "BAMLH0A1HYBB": ("BB OAS",  "BB利差"),
    "BAMLH0A3HYC":  ("CCC OAS", "CCC利差"),
    # ---- real yields / inflation (%) ----
    "DFII5":  ("5Y Real",  "5年實質殖利率"),
    "DFII10": ("10Y Real", "10年實質殖利率"),
    "T5YIE":  ("5Y BEI",   "5年隱含通膨"),
    "T10YIE": ("10Y BEI",  "10年隱含通膨"),
    # ---- 10Y decomposition (ACM 3-factor) & global USD ----
    "THREEFY10":   ("10Y Fitted",       "10年擬合殖利率"),
    "THREEFYTP10": ("10Y Term Premium", "10年期限溢酬"),
    "DTWEXBGS":    ("Broad USD",         "廣義美元指數"),
    # ---- vol & financial conditions ----
    "VIXCLS":       ("VIX",          "VIX波動率"),
    "NFCI":         ("NFCI",         "全國金融狀況指數"),
    "NFCICREDIT":   ("NFCI Credit",  "NFCI信用分項"),
    "NFCILEVERAGE": ("NFCI Leverage","NFCI槓桿分項"),
    "NFCIRISK":     ("NFCI Risk",    "NFCI風險分項"),
    "STLFSI4":      ("StL Stress",   "聖路易聯儲壓力指數"),
    # ---- plumbing / liquidity ----
    "RRPONTSYD":    ("ON RRP ($B)",  "隔夜逆回購餘額"),   # Fed ON RRP take-up, $B, daily
    "SOFR":         ("SOFR",         "SOFR擔保隔夜利率"),
    "EFFR":         ("EFFR",         "有效聯邦資金利率"),
    "WRESBAL":      ("Reserves",     "準備金餘額"),         # reserve balances, weekly ($mn)
}

# yfinance-sourced series (no FRED equivalent / better coverage). ticker -> (key, en, tc)
YF_SERIES = {
    "^MOVE": ("MOVE",  "MOVE (rate vol)", "MOVE利率波動率"),
    "^GSPC": ("SP500", "S&P 500",         "標普500"),       # full history + real-time; FRED SP500 = fallback
}

# ------------------------------------------------------------------ fetch
def fetch_api(sid):
    url = "https://api.stlouisfed.org/fred/series/observations"
    p = {"series_id": sid, "api_key": API_KEY, "file_type": "json",
         "observation_start": START}
    r = requests.get(url, params=p, timeout=40); r.raise_for_status()
    obs = r.json().get("observations", [])
    idx, val = [], []
    for o in obs:
        idx.append(o["date"])
        v = o["value"]
        val.append(np.nan if v in (".", "", None) else float(v))
    return pd.Series(val, index=pd.to_datetime(idx), name=sid)

def fetch_csv(sid):
    url = f"https://fred.stlouisfed.org/graph/fredgraph.csv?id={sid}&cosd={START}"
    r = requests.get(url, timeout=40); r.raise_for_status()
    df = pd.read_csv(io.StringIO(r.text))
    df.columns = ["date", "value"]
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    return pd.Series(df["value"].values, index=pd.to_datetime(df["date"]), name=sid)

def fetch(sid, retries=3):
    for attempt in range(retries):
        try:
            s = fetch_api(sid) if API_KEY else fetch_csv(sid)
            if s.dropna().empty:
                print(f"  ! {sid}: empty", file=sys.stderr); return None
            return s
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.5 * (attempt + 1))   # back off on transient 403/timeout
                continue
            print(f"  ! {sid}: {e}", file=sys.stderr); return None

def fetch_yf(ticker):
    """yfinance close series; resilient (Yahoo can rate-limit cloud IPs)."""
    try:
        import yfinance as yf, warnings; warnings.filterwarnings("ignore")
        df = yf.download(ticker, start=START, progress=False, auto_adjust=False)
        if df is None or len(df) == 0: return None
        lvl0 = df.columns.get_level_values(0) if hasattr(df.columns, "get_level_values") else df.columns
        col = "Adj Close" if "Adj Close" in lvl0 else "Close"
        s = df[col]
        if isinstance(s, pd.DataFrame): s = s.iloc[:, 0]
        s = s.dropna(); s.index = pd.to_datetime(s.index).tz_localize(None)
        return s if len(s) else None
    except Exception as e:
        print(f"  ! {ticker}: {e}", file=sys.stderr); return None

print(f"Fetching {len(SERIES)} FRED series via "
      f"{'API key' if API_KEY else 'keyless fredgraph.csv'} ...")
raw = {}
for sid in SERIES:
    s = fetch(sid)
    if s is not None:
        raw[sid] = s
        d = s.dropna()
        print(f"  ok {sid:<13} {len(d):>5} pts  last {d.index[-1].date()} = {d.iloc[-1]:.3f}")
    if not API_KEY:
        time.sleep(0.3)   # avoid rate-limiting the public fredgraph endpoint

# yfinance series (MOVE, S&P 500). SP500 falls back to FRED if Yahoo unavailable.
print("Fetching yfinance series (MOVE, S&P 500) ...")
YF_LABELS = {}
for ticker, (key, en, tc) in YF_SERIES.items():
    YF_LABELS[key] = (en, tc)
    s = fetch_yf(ticker)
    if s is None and key == "SP500":
        print(f"  · {ticker} unavailable → FRED SP500 fallback", file=sys.stderr)
        s = fetch("SP500")
    if s is not None:
        raw[key] = s
        d = s.dropna()
        print(f"  ok {key:<13} {len(d):>5} pts  last {d.index[-1].date()} = {d.iloc[-1]:.3f}  ({ticker})")
    else:
        print(f"  ! {key}: unavailable", file=sys.stderr)

# NBER recession indicator (monthly 0/1) → contiguous [start,end] intervals for chart shading
recessions = []
usrec = fetch("USREC")
if usrec is not None:
    u = usrec.dropna(); inrec = u >= 0.5; start = None
    for date, v in inrec.items():
        if v and start is None: start = date
        elif (not v) and start is not None:
            recessions.append([start.strftime("%Y-%m-%d"), date.strftime("%Y-%m-%d")]); start = None
    if start is not None:
        recessions.append([start.strftime("%Y-%m-%d"), u.index[-1].strftime("%Y-%m-%d")])
print(f"NBER recession intervals in window: {recessions}")

# ------------------------------------------------------------------ align
all_idx = pd.bdate_range(START, dt.date.today())
frame = pd.DataFrame(index=all_idx)
for sid, s in raw.items():
    frame[sid] = s[~s.index.duplicated(keep="last")].reindex(all_idx)
ff = frame.ffill()   # forward-filled view for analytics

def have(*ids): return all(i in frame.columns for i in ids)

# derived: spreads computed from levels
if have("DGS5","DGS30"):
    frame["S5S30"] = frame["DGS30"] - frame["DGS5"]; ff["S5S30"] = ff["DGS30"] - ff["DGS5"]
if have("DGS2","DGS5","DGS10"):
    frame["BFLY"] = 2*frame["DGS5"] - frame["DGS2"] - frame["DGS10"]
    ff["BFLY"]    = 2*ff["DGS5"]    - ff["DGS2"]    - ff["DGS10"]
if have("BAMLH0A3HYC","BAMLH0A1HYBB"):
    frame["DISP"] = frame["BAMLH0A3HYC"] - frame["BAMLH0A1HYBB"]
    ff["DISP"]    = ff["BAMLH0A3HYC"]    - ff["BAMLH0A1HYBB"]
if have("SOFR","EFFR"):
    # repo-stress proxy: SOFR rich/cheap to the admin rate, in basis points
    frame["SOFREFFR"] = (frame["SOFR"] - frame["EFFR"]) * 100
    ff["SOFREFFR"]    = (ff["SOFR"]    - ff["EFFR"])    * 100
if have("THREEFY10","THREEFYTP10"):
    # ACM decomposition: fitted 10Y = expected avg short-rate path + term premium
    frame["EXPRATE"] = frame["THREEFY10"] - frame["THREEFYTP10"]
    ff["EXPRATE"]    = ff["THREEFY10"]    - ff["THREEFYTP10"]

# ------------------------------------------------------------------ stats helpers
def last(s):
    s = s.dropna(); return float(s.iloc[-1]) if len(s) else None
def chg(s, n):
    s2 = s.dropna()
    return float(s2.iloc[-1] - s2.iloc[-1-n]) if len(s2) > n else None
def zscore_last(s):
    x = s.dropna()
    if len(x) < 60: return None
    mu, sd = x.mean(), x.std()
    return float((x.iloc[-1]-mu)/sd) if sd>0 else None
def zseries(s):
    mu, sd = s.mean(), s.std()
    return (s-mu)/sd if sd and sd>0 else s*0
def pct_rank(s):
    x = s.dropna()
    if len(x) < 60: return None
    return float((x <= x.iloc[-1]).mean()*100)
def pct_rank_window(s, n):
    x = s.dropna().iloc[-n:]
    if len(x) < 30: return None
    return float((x <= x.iloc[-1]).mean()*100)
# robust normalization: median/MAD, winsorized — far less sensitive to COVID-type outliers
def robust_zseries(s, clip=3.5):
    x = s.dropna()
    if len(x) < 60: return s*0
    med = x.median(); mad = (x - med).abs().median()
    scale = 1.4826*mad if mad>0 else (x.std() or 1.0)
    z = (s - med)/scale
    return z.clip(-clip, clip)

# ------------------------------------------------------------------ composite risk score
# Each component z-scored & oriented so (+) = tighter / more risk-off / more stress.
comp_defs = []   # (key, oriented_series, weight, label_en, label_tc)
def add_comp(key, series, w, en, tc):
    comp_defs.append((key, series, w, en, tc))

if have("BAMLH0A0HYM2"):
    add_comp("hy_level", zseries(ff["BAMLH0A0HYM2"]), 0.18, "HY OAS level", "高收益利差水準")
    add_comp("hy_mom",   zseries(ff["BAMLH0A0HYM2"].diff(21)), 0.18, "HY OAS 1M momentum", "高收益利差1月動能")
if have("VIXCLS"):
    add_comp("vix", zseries(ff["VIXCLS"]), 0.12, "VIX (equity vol)", "VIX股票波動率")
if have("MOVE"):
    add_comp("move", zseries(ff["MOVE"]), 0.12, "MOVE (rate vol)", "MOVE利率波動率")
if have("NFCI"):
    add_comp("nfci", ff["NFCI"], 0.14, "NFCI (tightness)", "金融狀況指數")  # already ~z, +=tight
if have("T10Y3M"):
    add_comp("curve", -zseries(ff["T10Y3M"]), 0.09, "Curve 3M10Y (inverted=stress)", "殖利率曲線(倒掛為壓力)")
if have("DFII10"):
    add_comp("realmom", zseries(ff["DFII10"].diff(21)), 0.09, "Real yield 1M momentum", "實質殖利率1月動能")
if have("DISP"):
    add_comp("disp", zseries(ff["DISP"]), 0.08, "CCC-BB dispersion", "CCC-BB離散度")

# renormalise weights to available components
wsum = sum(w for *_, w, _, _ in [(k,s,w,e,t) for (k,s,w,e,t) in comp_defs]) or 1.0
comp_series = None
components = []
for (k, s, w, en, tc) in comp_defs:
    wn = w / wsum
    contrib = s * wn
    comp_series = contrib if comp_series is None else comp_series.add(contrib, fill_value=0)
    components.append({"key": k, "en": en, "tc": tc, "weight": round(wn,3),
                       "z": (round(last(s),2) if last(s) is not None else None),
                       "contrib": (round(last(contrib),3) if last(contrib) is not None else None)})

def to_gauge(z):
    if z is None or (isinstance(z,float) and math.isnan(z)): return None
    return max(0.0, min(100.0, 50.0 + z*16.667))

gauge_series = comp_series.apply(lambda v: to_gauge(v) if pd.notna(v) else np.nan) if comp_series is not None else None
composite_z_last = last(comp_series) if comp_series is not None else None
gauge_last = to_gauge(composite_z_last)

# ------------------------------------------------------------------ point-in-time (expanding-window) gauge — for the backtest only
# At each date t the z-scores use ONLY data up to t (no look-ahead). The live/current gauge above is full-sample
# (which equals the expanding value at the latest point anyway); this PIT series is what makes the backtest honest.
def expanding_z(s, minp=252):
    m = s.expanding(min_periods=minp).mean(); sd = s.expanding(min_periods=minp).std()
    return (s - m) / sd.replace(0, np.nan)
pit_parts = []
def pit_add(raw, w): pit_parts.append((expanding_z(raw), w))
if have("BAMLH0A0HYM2"):
    pit_add(ff["BAMLH0A0HYM2"], 0.18); pit_add(ff["BAMLH0A0HYM2"].diff(21), 0.18)
if have("VIXCLS"): pit_add(ff["VIXCLS"], 0.12)
if have("MOVE"):   pit_add(ff["MOVE"], 0.12)
if have("NFCI"):   pit_add(ff["NFCI"], 0.14)
if have("T10Y3M"): pit_add(-ff["T10Y3M"], 0.09)
if have("DFII10"): pit_add(ff["DFII10"].diff(21), 0.09)
if have("DISP"):   pit_add(ff["DISP"], 0.08)
gauge_series_pit = None
if pit_parts:
    wsp = sum(w for _, w in pit_parts) or 1.0
    comp_pit = None
    for z, w in pit_parts:
        c = z * (w / wsp); comp_pit = c if comp_pit is None else comp_pit.add(c, fill_value=0)
    gauge_series_pit = comp_pit.apply(lambda v: to_gauge(v) if pd.notna(v) else np.nan)

# ------------------------------------------------------------------ four pillar scores (robust median/MAD → sigmoid 0-100)
# Risk is split by TYPE so a single normal composite can't mask one extreme pillar.
def sigmoid01(z): return float(100.0/(1.0+np.exp(-0.9*z)))
pillar_specs = {
  "stress":    ("系統性壓力", "Systemic Stress", [
      ("BAMLH0A0HYM2",+1,"HY OAS"),("BAMLH0A3HYC",+1,"CCC OAS"),("DISP",+1,"CCC-BB 離散度"),
      ("VIXCLS",+1,"VIX"),("NFCI",+1,"NFCI"),("STLFSI4",+1,"StL 壓力")]),
  "duration":  ("存續期與估值", "Duration & Valuation", [
      ("DFII10",+1,"10Y 實質"),("DFII5",+1,"5Y 實質"),("THREEFYTP10",+1,"期限溢酬"),
      ("MOVE",+1,"MOVE"),("DTWEXBGS",+1,"廣義美元")]),
  "cycle":     ("週期與衰退", "Cycle & Recession", [
      ("T10Y3M",-1,"曲線倒掛 3M10Y"),("__HYMOM__",+1,"信用動能 3M")]),
  "liquidity": ("流動性與資金", "Liquidity & Funding", [
      ("SOFREFFR",+1,"SOFR−EFFR"),("WRESBAL",-1,"準備金")]),
}
deriv_members = {}
if have("BAMLH0A0HYM2"): deriv_members["__HYMOM__"] = ff["BAMLH0A0HYM2"].diff(63)
pillars = {}; pillar_score_series = {}
for pk,(tc,en,members) in pillar_specs.items():
    zsers=[]; comps=[]
    for (mid, sign, mtc) in members:
        src = deriv_members.get(mid) if mid.startswith("__") else (ff[mid] if mid in ff.columns else None)
        if src is None: continue
        zs = robust_zseries(src)*sign
        zsers.append(zs); zl=last(zs)
        comps.append({"id":mid,"tc":mtc,"z":(round(zl,2) if zl is not None else None)})
    if not zsers: continue
    raw = pd.concat(zsers, axis=1).mean(axis=1)
    score = raw.apply(lambda v: sigmoid01(v) if pd.notna(v) else np.nan)
    sl = last(score); sdrop = score.dropna()
    ago = lambda n: (round(float(sdrop.iloc[-1-n]),1) if len(sdrop)>n else None)
    # signed POINT contribution per component: local sigmoid slope × (z_i / n). Sums ≈ score − 50, stable at raw≈0.
    n_comp = len([c for c in comps if c["z"] is not None]) or 1
    slope = 0.9 * (sl if sl is not None else 50) * (100 - (sl if sl is not None else 50)) / 100.0
    for c in comps:
        c["pts"] = (round(slope * (c["z"]/n_comp), 1) if c["z"] is not None else None)
    withpts = [c for c in comps if c.get("pts") is not None]
    pressure = sorted([c for c in withpts if c["pts"]>0], key=lambda c:c["pts"], reverse=True)
    offset   = sorted([c for c in withpts if c["pts"]<0], key=lambda c:c["pts"])
    csorted  = sorted(withpts, key=lambda c:c["z"], reverse=True)
    # dampened WoW (5-day median now vs 5d ago) so a single repo/quarter-end spike can't swing the pillar 20+ pts
    med5 = score.rolling(5, min_periods=3).median().dropna()
    wow_damp = (round(float(med5.iloc[-1]-med5.iloc[-6]),1) if len(med5)>6 else None)
    pillars[pk] = {"tc":tc,"en":en,
        "score":(round(sl,1) if sl is not None else None),
        "score_med5":(round(float(med5.iloc[-1]),1) if len(med5) else None),
        "wow":(round(sl-ago(5),1)  if sl is not None and ago(5)  is not None else None),
        "wow_damp":wow_damp,
        "mom":(round(sl-ago(21),1) if sl is not None and ago(21) is not None else None),
        "z":(round(last(raw),2) if last(raw) is not None else None),
        "coverage":n_comp,
        "pressure":pressure[:2], "offset_d":offset[:2],
        "top":csorted[:2], "offset":csorted[-2:][::-1], "components":comps}
    pillar_score_series[pk] = score.reindex(frame.index)
print("Pillars: " + " | ".join(f"{k}={v['score']}(cov{v['coverage']})" for k,v in pillars.items()))

# ------------------------------------------------------------------ data health (per-series freshness)
_olast = frame.index.max()
_health = []
for cid in frame.columns:
    s = frame[cid].dropna()
    if len(s)==0: _health.append({"id":cid,"last":None,"days":None}); continue
    ld = s.index.max(); _health.append({"id":cid,"last":ld.strftime("%Y-%m-%d"),"days":int((_olast-ld).days)})
_stale = [h for h in _health if h["days"] is not None and h["days"]>10]
data_health = {"as_of":_olast.strftime("%Y-%m-%d"), "series_count":len(frame.columns),
    "stale_count":len(_stale), "stale":sorted(_stale,key=lambda h:-h["days"])[:8],
    "worst_lag":(max((h["days"] for h in _health if h["days"] is not None), default=None))}

# ------------------------------------------------------------------ regime (2x2)
# X = curve direction = 63d change in 2s10s (>0 steepening, <0 flattening)
# Y = credit direction = 63d change in HY OAS (>0 widening/bad, <0 tightening/good)
spread2s10s = ff["T10Y2Y"] if have("T10Y2Y") else (ff["DGS10"]-ff["DGS2"] if have("DGS2","DGS10") else None)
hy = ff["BAMLH0A0HYM2"] if have("BAMLH0A0HYM2") else None
regime = None; regime_trail = []
if spread2s10s is not None and hy is not None:
    cx = spread2s10s.diff(63)   # curve dir
    cy = hy.diff(63)            # credit dir
    x_now, y_now = last(cx), last(cy)
    # deadbands = 0.25 * stdev of each 63d-change distribution → kills whipsawing near 0
    dx = round(0.25 * float(cx.dropna().std()), 3)
    dy = round(0.25 * float(cy.dropna().std()), 3)
    def classify(x, y):
        if x is None or y is None: return ("unknown","未知","neutral","neutral")
        cs = "neutral" if abs(x) <= dx else ("steepen" if x > 0 else "flatten")
        kr = "neutral" if abs(y) <= dy else ("widen"   if y > 0 else "tighten")
        if cs == "neutral" or kr == "neutral":
            return ("transition","過渡期／維持現狀", cs, kr)
        if cs=="steepen" and kr=="tighten": return ("reflation","復甦／再通膨", cs, kr)
        if cs=="flatten" and kr=="tighten": return ("goldilocks","金髮女孩／中循環", cs, kr)
        if cs=="flatten" and kr=="widen":   return ("late_cycle","循環末段／壓力醞釀", cs, kr)
        return ("risk_off","避險／衰退動態", cs, kr)
    qk, qtc, cs, kr = classify(x_now, y_now)
    regime = {"x": (round(x_now,3) if x_now is not None else None),
              "y": (round(y_now,3) if y_now is not None else None),
              "key": qk, "tc": qtc, "curve_state": cs, "credit_state": kr,
              "dx": dx, "dy": dy}
    # weekly trail, last 26 weeks. W-FRI labels the (possibly incomplete) current week by its coming Friday,
    # which can read as a future date — clamp every label to the actual last observation date.
    j = pd.concat([cx.rename("x"), cy.rename("y")], axis=1).dropna()
    _last_obs = j.index.max()
    j = j.resample("W-FRI").last().dropna().tail(26)
    for ts, row in j.iterrows():
        dlabel = min(ts, _last_obs)
        regime_trail.append([dlabel.strftime("%Y-%m-%d"), round(float(row["x"]),3), round(float(row["y"]),3)])

# ------------------------------------------------------------------ dis-inversion tracker (2s10s)
disinv = None
if spread2s10s is not None:
    s = spread2s10s.dropna()
    cur = float(s.iloc[-1])
    inverted_now = cur < 0
    # find last sign change
    sign = (s >= 0).astype(int)
    flips = sign.ne(sign.shift())
    last_flip_date = s.index[flips][-1] if flips.any() else s.index[0]
    days_since_flip = int((s.index[-1] - last_flip_date).days)
    # longest inversion run within last 2y
    s2 = s[s.index >= (s.index[-1] - pd.Timedelta(days=730))]
    runs, cur_run, max_run = [], 0, 0
    for v in s2.values:
        if v < 0: cur_run += 1; max_run = max(max_run, cur_run)
        else: cur_run = 0
    if inverted_now:
        status_en = f"Inverted ({days_since_flip}d since cross)"
        status_tc = f"倒掛中（距上次穿越 {days_since_flip} 日）"
    else:
        status_en = f"Positive ({days_since_flip}d since re-steepen)"
        status_tc = f"正斜率（距倒掛修復 {days_since_flip} 日）"
    disinv = {"current": round(cur,3), "inverted": inverted_now,
              "days_since_flip": days_since_flip, "max_inv_run_2y": int(max_run),
              "status_en": status_en, "status_tc": status_tc,
              "last_flip": last_flip_date.strftime("%Y-%m-%d")}

# ------------------------------------------------------------------ curve state machine (richer than "inverted = stress")
curve_state = None
sp_3m10y = ff["T10Y3M"] if have("T10Y3M") else None
if spread2s10s is not None:
    s2 = spread2s10s.dropna(); cur2 = float(s2.iloc[-1])
    s3 = sp_3m10y.dropna() if sp_3m10y is not None else None
    cur3 = float(s3.iloc[-1]) if s3 is not None and len(s3) else None
    primary = s3 if (s3 is not None and len(s3)) else s2     # 3M10Y preferred for recession framing
    inv_now = float(primary.iloc[-1]) < 0
    def inv_run_days(series):                                # calendar days of the current sub-zero run
        v = series.values
        if v[-1] >= 0: return 0
        i = len(v)-1
        while i >= 0 and v[i] < 0: i -= 1
        return int((series.index[-1] - series.index[i+1]).days)
    def days_since_disinv(series):                           # if positive now, days since last neg→pos cross
        v = series.values
        if v[-1] < 0: return None
        for i in range(len(v)-1, -1, -1):
            if v[i] < 0: return int((series.index[-1] - series.index[i]).days)
        return None
    dinv = inv_run_days(primary); dsd = days_since_disinv(primary)
    depth_bps = round(-float(primary.iloc[-1])*100, 0) if inv_now else 0
    # bull/bear shape over 21d, decomposed by which leg moved
    shape = "stable"; d2 = d10 = None
    if have("DGS2","DGS10"):
        d2 = chg(ff["DGS2"],21); d10 = chg(ff["DGS10"],21)
        if d2 is not None and d10 is not None:
            ds = d10 - d2; eps = 0.05; dom_long = abs(d10) >= abs(d2)
            if ds > eps:
                shape = "bear_steepener" if (dom_long and d10>0) else ("bull_steepener" if ((not dom_long) and d2<0) else "steepening")
            elif ds < -eps:
                shape = "bull_flattener" if (dom_long and d10<0) else ("bear_flattener" if ((not dom_long) and d2>0) else "flattening")
    # credit confirmation (HY OAS 3M direction)
    hy_chg = chg(ff["BAMLH0A0HYM2"],63) if have("BAMLH0A0HYM2") else None
    credit_confirm = "neutral"
    if hy_chg is not None:
        credit_confirm = "confirming" if hy_chg > 0.10 else ("not_confirming" if hy_chg < -0.10 else "neutral")
    # state synthesis + warning
    warning = None
    if inv_now and dinv >= 60:
        state_key="deep_inversion"; warning="deep_inversion"
        state_tc=f"深度倒掛 約 {int(depth_bps)}bps,已 {dinv} 日"; state_en=f"Deeply inverted ~{int(depth_bps)}bps, {dinv}d"
    elif inv_now:
        state_key="inverted"; state_tc=f"倒掛 約 {int(depth_bps)}bps（{dinv} 日)"; state_en=f"Inverted ~{int(depth_bps)}bps ({dinv}d)"
    elif (dsd is not None) and dsd <= 90:
        state_key="recent_disinversion"; warning="dis_inversion"
        state_tc=f"近期倒掛修復(距今 {dsd} 日)—— 歷史衰退時點警訊"; state_en=f"Recent dis-inversion ({dsd}d ago) — recession-timing warning"
    else:
        lbl={"bull_steepener":"正斜率 · 牛市趨陡(前端下行)","bear_steepener":"正斜率 · 熊市趨陡(長端上行)",
             "bull_flattener":"正斜率 · 牛市趨平(長端下行 · 成長疑慮)","bear_flattener":"正斜率 · 熊市趨平(前端上行 · 鷹派)",
             "steepening":"正斜率 · 趨陡","flattening":"正斜率 · 趨平","stable":"正斜率 · 平穩"}
        state_key="positive_"+shape; state_tc=lbl.get(shape,"正斜率 · 平穩"); state_en="Positive — "+shape.replace("_"," ")
    c1=chg(spread2s10s,21); c3=chg(spread2s10s,63)
    curve_state={"spread_2s10s":round(cur2,3),"spread_3m10y":(round(cur3,3) if cur3 is not None else None),
        "inverted":inv_now,"depth_bps":depth_bps,"days_inverted":dinv,"days_since_disinv":dsd,
        "chg_2s10s_1m":(round(c1,3) if c1 is not None else None),"chg_2s10s_3m":(round(c3,3) if c3 is not None else None),
        "d2y_1m":(round(d2,3) if d2 is not None else None),"d10y_1m":(round(d10,3) if d10 is not None else None),
        "shape":shape,"credit_confirm":credit_confirm,
        "state_key":state_key,"state_tc":state_tc,"state_en":state_en,"warning":warning}
    print(f"Curve state: {state_en} | shape={shape} | credit={credit_confirm}")

# ------------------------------------------------------------------ per-series summary
def jround(v, n=4):
    if v is None or (isinstance(v,float) and (math.isnan(v) or math.isinf(v))): return None
    return round(float(v), n)

def col_payload(cid):
    s = frame[cid]
    return {
        "last":  jround(last(s),4),
        "chg1m": jround(chg(s,21),4),
        "chg3m": jround(chg(s,63),4),
        "z":     jround(zscore_last(s),2),
        "pct":   jround(pct_rank(s),1),
    }

summary = {cid: col_payload(cid) for cid in frame.columns}

# ------------------------------------------------------------------ 30d rolling correlation
# correlation of DAILY CHANGES (returns for index/USD, diffs for spreads/yields/vol)
correlation = None
corr_assets = [  # (id, short_en, tc, transform)
    ("SP500",        "SPX",      "標普500",   "ret"),
    ("BAMLH0A0HYM2", "HY OAS",   "高收益利差", "dlt"),
    ("DFII10",       "10Y Real", "10年實質",   "dlt"),
    ("MOVE",         "MOVE",     "MOVE",      "dlt"),
    ("DTWEXBGS",     "USD",      "廣義美元",   "dlt"),
]
avail_c = [(cid,en,tc,k) for (cid,en,tc,k) in corr_assets if cid in ff.columns]
if len(avail_c) >= 3:
    chgs = {}
    for cid,en,tc,k in avail_c:
        chgs[cid] = ff[cid].pct_change() if k=="ret" else ff[cid].diff()
    cdf = pd.DataFrame(chgs).replace([np.inf,-np.inf], np.nan).dropna()
    WIN = 30
    cm = cdf.tail(WIN).corr()
    cols = [cid for cid,_,_,_ in avail_c]
    matrix = [[ (jround(cm.loc[r,c],2) if (r in cm.index and c in cm.columns and not pd.isna(cm.loc[r,c])) else None)
               for c in cols] for r in cols]
    head = []
    if "SP500" in cdf.columns and "BAMLH0A0HYM2" in cdf.columns:
        rc = cdf["SP500"].rolling(WIN).corr(cdf["BAMLH0A0HYM2"]).dropna().resample("W-FRI").last().dropna().tail(52)
        head = [[ts.strftime("%Y-%m-%d"), jround(float(v),2)] for ts,v in rc.items()]
    correlation = {
        "labels_en": [en for _,en,_,_ in avail_c],
        "labels_tc": [tc for _,_,tc,_ in avail_c],
        "matrix": matrix, "window": WIN,
        "headline": head, "headline_pair": ["SPX","HY OAS"],
        "headline_now": (head[-1][1] if head else None),
    }
    print(f"30d corr SPX~HY: {correlation['headline_now']}")

# ------------------------------------------------------------------ assemble time series (aligned, nulls preserved)
dates = [d.strftime("%Y-%m-%d") for d in frame.index]
def col_vals(cid, n=4):
    return [jround(v,n) for v in frame[cid].tolist()]

series_out = {cid: col_vals(cid) for cid in frame.columns}
if gauge_series is not None:
    series_out["GAUGE"] = [jround(v,2) for v in gauge_series.reindex(frame.index).tolist()]
if comp_series is not None:
    series_out["COMPZ"] = [jround(v,3) for v in comp_series.reindex(frame.index).tolist()]
for pk, ser in pillar_score_series.items():
    series_out["P_"+pk] = [jround(v,1) for v in ser.tolist()]

# ------------------------------------------------------------------ model validation (in-sample, descriptive)
# Does the signal actually line up with subsequent S&P outcomes? Reuses the displayed regime logic.
model_validation = None
if gauge_series is not None and have("SP500"):
    spx = ff["SP500"].dropna()
    g   = (gauge_series_pit if gauge_series_pit is not None else gauge_series).reindex(spx.index)   # point-in-time gauge
    HZ  = {"1M":21, "3M":63, "6M":126}
    def fwd_ret(h): return spx.shift(-h)/spx - 1.0
    def fwd_mae(h):                                   # worst level below entry within next h days (max adverse excursion)
        rmin = spx[::-1].rolling(h, min_periods=max(3,h//3)).min()[::-1]
        return rmin/spx - 1.0
    fr = {k: fwd_ret(h) for k,h in HZ.items()}
    fm = {k: fwd_mae(h) for k,h in HZ.items()}
    def stats_block(mask):
        out={}
        for k in HZ:
            r = fr[k][mask].dropna(); m = fm[k][mask].dropna()
            out[k] = {"n": int(min(len(r),len(m))),
                "ret_mean": jround(float(r.mean())*100,1) if len(r) else None,
                "ret_med":  jround(float(r.median())*100,1) if len(r) else None,
                "pos":      jround(float((r>0).mean())*100,0) if len(r) else None,
                "mae_mean": jround(float(m.mean())*100,1) if len(m) else None,
                "mae_p05":  jround(float(m.quantile(0.05))*100,1) if len(m) else None}
        return out
    gmask = g.notna()                                  # common eligible universe: PIT gauge exists at t
    baseline = stats_block(gmask)                      # baseline now on the SAME sample as the quintiles (N matches Σ buckets)
    # gauge quintiles (equal-count)
    gq = g.dropna(); qc = gq.quantile([0,.2,.4,.6,.8,1.0]).values
    gauge_buckets=[]
    for i in range(5):
        lo,hi = float(qc[i]), float(qc[i+1])
        mask = ((g>=lo)&(g<hi)) if i<4 else ((g>=lo)&(g<=hi))
        gauge_buckets.append({"q":i+1, "lo":jround(lo,1), "hi":jround(hi,1), "stats":stats_block(mask.fillna(False))})
    # regime daily classification (consistent with displayed regime), forward stats
    cxr = cx.reindex(spx.index); cyr = cy.reindex(spx.index)
    reg_daily = pd.Series(index=spx.index, dtype=object)
    for idx in spx.index:
        xv, yv = cxr.get(idx), cyr.get(idx)
        if pd.notna(xv) and pd.notna(yv): reg_daily[idx] = classify(float(xv), float(yv))[0]
    regime_stats={}
    for rk in ["reflation","goldilocks","late_cycle","risk_off","transition"]:
        mask=(reg_daily==rk)
        if int(mask.sum())>=20: regime_stats[rk]={"n":int(mask.sum()),"stats":stats_block(mask)}
    # predictor comparison — Spearman IC vs forward 3M outcomes + top-quintile hit rate, ALL on the eligible sample
    def spear(a,b):
        j=pd.concat([a,b],axis=1).dropna()
        if len(j)<60: return None
        return float(j.iloc[:,0].rank().corr(j.iloc[:,1].rank()))   # Spearman = Pearson of ranks (no scipy dependency)
    preds={"綜合儀表 Composite": g}
    if have("NFCI"): preds["NFCI"]=ff["NFCI"].reindex(spx.index)
    if have("STLFSI4"): preds["StL FSI"]=ff["STLFSI4"].reindex(spx.index)
    if have("BAMLH0A0HYM2"): preds["HY OAS"]=ff["BAMLH0A0HYM2"].reindex(spx.index)
    ev=(fm["3M"]<-0.05)
    base_rate=float(ev[gmask].dropna().mean())          # event rate on the eligible sample
    pred_rows=[]
    for nm,sv in preds.items():
        sve=sv[gmask]                                   # compare every predictor on the SAME eligible dates
        thr=sve.dropna().quantile(0.8); sig=(sve>=thr)
        jj=pd.concat([sig.rename("s"),ev[gmask].rename("e")],axis=1).dropna()
        hit=float(jj[jj.s].e.mean()) if int(jj.s.sum())>0 else None
        pred_rows.append({"name":nm,
            "ic_mae": jround(spear(sve,fm["3M"][gmask]),2), "ic_ret": jround(spear(sve,fr["3M"][gmask]),2),
            "hit": (jround(hit*100,0) if hit is not None else None)})
    rd=reg_daily.dropna(); switches=int((rd!=rd.shift()).sum()-1) if len(rd)>1 else 0
    yrs=max(1e-9,(spx.index[-1]-spx.index[0]).days/365.25)
    # ---- non-overlapping (every 63 trading days ≈ independent 3M blocks) robustness check ----
    def spear_n(a,b,minn):
        j=pd.concat([a,b],axis=1).dropna()
        if len(j)<minn: return None
        return float(j.iloc[:,0].rank().corr(j.iloc[:,1].rank()))
    gne = g.dropna().iloc[::63]
    nonoverlap={"n":int(gne.shape[0]),
        "ic_ret":jround(spear_n(gne, fr["3M"].reindex(gne.index), 24),2),
        "ic_mae":jround(spear_n(gne, fm["3M"].reindex(gne.index), 24),2)}
    # ---- walk-forward (rolling-origin): expanding train, test on each subsequent year ----
    def ic_block(idx):
        a=g.reindex(idx)
        return {"n":int(min(a.notna().sum(), fr["3M"].reindex(idx).notna().sum())),
                "ic_ret":jround(spear(a, fr["3M"].reindex(idx)),2),
                "ic_mae":jround(spear(a, fm["3M"].reindex(idx)),2)}
    def _median(xs):
        ys=sorted(v for v in xs if v is not None)
        if not ys: return None
        mid=len(ys)//2
        return jround(ys[mid] if len(ys)%2 else (ys[mid-1]+ys[mid])/2, 2)
    gv = g.dropna(); years=sorted(set(gv.index.year)); y0=years[0]
    folds=[]
    for ty in years:
        if ty - y0 < 2: continue                        # need ≥2y of expanding training history before a test year
        blk = ic_block(spx.index[spx.index.year==ty])
        if blk["n"]>=40:
            folds.append({"test_year":int(ty),"train_through":int(ty-1),"n":blk["n"],
                          "ic_ret":blk["ic_ret"],"ic_mae":blk["ic_mae"]})
    walk_forward=None
    if folds:
        nret=[f["ic_ret"] for f in folds if f["ic_ret"] is not None]
        nmae=[f["ic_mae"] for f in folds if f["ic_mae"] is not None]
        walk_forward={"folds":folds,"n_folds":len(folds),
            "median_ic_ret":_median(nret),"median_ic_mae":_median(nmae),
            "ret_pos_share": (jround(sum(1 for x in nret if x>0)/len(nret)*100,0) if nret else None),
            "mae_neg_share": (jround(sum(1 for x in nmae if x<0)/len(nmae)*100,0) if nmae else None),
            "worst_ret": (jround(min(nret),2) if nret else None),
            "worst_mae": (jround(max(nmae),2) if nmae else None)}   # most-positive MAE-IC = weakest downside-warning fold
    last_year=max(set(spx.index.year))
    ic_by_year=[]
    for yr in sorted(set(spx.index.year)):
        blk = ic_block(spx.index[spx.index.year==yr])
        if blk["n"] >= 40: ic_by_year.append({"year":int(yr), "partial":(yr==last_year), **blk})
    credit_start=None
    if "BAMLH0A0HYM2" in ff.columns and ff["BAMLH0A0HYM2"].dropna().shape[0]:
        credit_start=ff["BAMLH0A0HYM2"].dropna().index.min().strftime("%Y-%m-%d")
    model_validation={"baseline":baseline,"gauge_buckets":gauge_buckets,"regime_stats":regime_stats,
        "predictors":pred_rows,"event_def":"未來3個月最大不利位移 < −5%","base_rate":jround(base_rate*100,0),
        "switches_per_yr":jround(switches/yrs,1),"n_obs":int(gv.shape[0]),"pit":(gauge_series_pit is not None),
        "walk_forward":walk_forward,"nonoverlap":nonoverlap,"ic_by_year":ic_by_year,"credit_start":credit_start,
        "span":[gv.index[0].strftime("%Y-%m-%d"),gv.index[-1].strftime("%Y-%m-%d")]}
    print("Model validation: rolling-origin folds=%d | median test IC ret/mae=%s/%s | baseline 3M N=%s (Σbuckets=%s)"%(
        len(folds), walk_forward["median_ic_ret"] if walk_forward else "—",
        walk_forward["median_ic_mae"] if walk_forward else "—",
        baseline["3M"]["n"], sum(b["stats"]["3M"]["n"] for b in gauge_buckets)))

labels = {}
for cid in frame.columns:
    if cid in SERIES:       en, tc = SERIES[cid]
    elif cid in YF_LABELS:  en, tc = YF_LABELS[cid]
    else:                   en = tc = cid
    labels[cid] = {"en": en, "tc": tc}
labels["S5S30"]    = {"en":"5s30s","tc":"5年30年利差"}
labels["BFLY"]     = {"en":"2s5s10s Butterfly","tc":"2-5-10蝴蝶"}
labels["DISP"]     = {"en":"CCC-BB Dispersion","tc":"CCC-BB離散度"}
labels["SOFREFFR"] = {"en":"SOFR − EFFR (bps)","tc":"SOFR減EFFR利差"}
labels["EXPRATE"]  = {"en":"10Y Exp. Rate Path","tc":"10年預期利率路徑"}

# ------------------------------------------------------------------ cross-run alert state (persisted first-triggered dates)
# Evaluates the same breakage conditions as the dashboard, then reads/updates alert_state.json so each run knows
# how long a condition has truly been active across cron runs (New / Ongoing) — not just re-derived from one snapshot.
STATE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "alert_state.json")
as_of_str = frame.index.max().strftime("%Y-%m-%d")
def _lastpct(cid): return pct_rank(ff[cid]) if cid in ff.columns else None
def _wk_surge(cid, n=5, thr=20.0):
    s = ff[cid].dropna() if cid in ff.columns else None
    if s is None or len(s) <= n: return False
    a, b = s.iloc[-1], s.iloc[-1-n]; return (b > 0) and ((a-b)/b*100 > thr)
active_keys = set()
def _flag(key, cond):
    if cond: active_keys.add(key)
_cs = curve_state
_flag("curve_disinv", bool(_cs and _cs.get("warning") == "dis_inversion"))
_flag("curve_deepinv", bool(_cs and _cs.get("warning") == "deep_inversion"))
_flag("move_surge", _wk_surge("MOVE", 5, 20))
_flag("vix_surge", _wk_surge("VIXCLS", 5, 30))
_flag("gauge_stress", (gauge_last is not None and gauge_last >= 70))
_flag("gauge_tight", (gauge_last is not None and 58 <= gauge_last < 70))
_flag("disp_extreme", (_lastpct("DISP") or 0) > 90)
if "THREEFYTP10" in ff.columns:
    _tpl, _tpc = last(ff["THREEFYTP10"]), chg(ff["THREEFYTP10"], 63)
    _flag("termprem", (_tpl is not None and _tpc is not None and _tpl > 0.5 and _tpc > 0.3))
if "DTWEXBGS" in ff.columns:
    _d3, _d1 = chg(ff["DTWEXBGS"], 63), chg(ff["DTWEXBGS"], 21)
    _flag("dollar", (_d3 is not None and _d1 is not None and _d3 > 3 and _d1 > 0))
_flag("rrp", ("RRPONTSYD" in ff.columns and last(ff["RRPONTSYD"]) is not None and last(ff["RRPONTSYD"]) < 50))
_flag("repo", ("SOFREFFR" in ff.columns and last(ff["SOFREFFR"]) is not None and last(ff["SOFREFFR"]) >= 10))
_old_state = {}
try:
    if os.path.exists(STATE_PATH): _old_state = json.load(open(STATE_PATH))
except Exception: _old_state = {}
_new_state, _active_out, _resolved = {}, {}, []
for k in active_keys:
    prev = _old_state.get(k)
    fs = (prev.get("first_seen") if isinstance(prev, dict) else prev) or as_of_str
    _new_state[k] = {"first_seen": fs, "last_seen": as_of_str}
    days = (pd.Timestamp(as_of_str) - pd.Timestamp(fs)).days
    _active_out[k] = {"first_seen": fs, "days": int(days), "status": ("new" if days <= 7 else "ongoing")}
for k, prev in _old_state.items():            # conditions that were active last run but cleared this run
    if k not in active_keys:
        fs = (prev.get("first_seen") if isinstance(prev, dict) else prev)
        _resolved.append({"key": k, "first_seen": fs, "resolved": as_of_str})
try: json.dump(_new_state, open(STATE_PATH, "w"), indent=0, ensure_ascii=False)
except Exception as e: print("alert_state write failed:", e)
alerts_state = {"as_of": as_of_str, "active": _active_out, "resolved": _resolved}
print("Alert state:", {k: v["days"] for k, v in _active_out.items()} or "none")

out = {
    "generated_utc": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC"),
    "source": "FRED (St. Louis Fed) · ICE BofA OAS · Chicago Fed NFCI · MOVE/S&P via Yahoo Finance",
    "start": START,
    "dates": dates,
    "labels": labels,
    "series": series_out,
    "summary": summary,
    "available": list(frame.columns),
    "recessions": recessions,
    "correlation": correlation,
    "composite": {
        "gauge": jround(gauge_last,1),
        "z": jround(composite_z_last,3),
        "components": components,
    },
    "regime": regime,
    "regime_trail": regime_trail,
    "disinversion": disinv,
    "curve_state": curve_state,
    "pillars": pillars,
    "data_health": data_health,
    "model_validation": model_validation,
    "alerts_state": alerts_state,
}

with open(OUT, "w") as f:
    json.dump(out, f, separators=(",",":"), ensure_ascii=False)

sz = os.path.getsize(OUT)/1024
print(f"\nWrote {OUT}  ({sz:.0f} KB)  | {len(frame.columns)} series | {len(dates)} dates")
print(f"Composite gauge: {gauge_last}  | regime: {regime['key'] if regime else None}")
print(f"Dis-inversion: {disinv['status_en'] if disinv else None}")
