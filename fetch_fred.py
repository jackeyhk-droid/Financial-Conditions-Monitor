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
    # weekly trail, last 26 weeks
    j = pd.concat([cx.rename("x"), cy.rename("y")], axis=1).dropna()
    j = j.resample("W-FRI").last().dropna().tail(26)
    for ts, row in j.iterrows():
        regime_trail.append([ts.strftime("%Y-%m-%d"), round(float(row["x"]),3), round(float(row["y"]),3)])

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
}

with open(OUT, "w") as f:
    json.dump(out, f, separators=(",",":"), ensure_ascii=False)

sz = os.path.getsize(OUT)/1024
print(f"\nWrote {OUT}  ({sz:.0f} KB)  | {len(frame.columns)} series | {len(dates)} dates")
print(f"Composite gauge: {gauge_last}  | regime: {regime['key'] if regime else None}")
print(f"Dis-inversion: {disinv['status_en'] if disinv else None}")
