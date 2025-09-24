#!/usr/bin/env python3
import os, json, datetime as dt
import pandas as pd
import yfinance as yf

# --- CONFIG ---
UNIVERSE_FILE = "qm1w.txt"   # <-- your ticker list file
NEWS_LOOKBACK_DAYS = 90
VOL_SMA_WINDOW = 50
GAP_THRESHOLD = 0.10
VOL_RATIO_GOOD = 2.0
NEWS_KEYWORDS = [
    "earnings","guidance","revenue","eps","beats","miss",
    "acquire","acquisition","merger","partnership","strategic",
    "approval","fda","phase","contract","order","upgrade","initiates coverage"
]

def load_tickers(path: str) -> list:
    txt = open(path).read()
    raw = [t.strip() for line in txt.splitlines() for t in line.split(",")]
    return [t for t in raw if t]

def get_news_score(news_items, since_ts):
    score = 0.0
    for n in news_items or []:
        ts = n.get("providerPublishTime") or n.get("published")
        if ts is None: continue
        try:
            published = dt.datetime.utcfromtimestamp(int(ts)) if isinstance(ts,(int,float)) else dt.datetime.fromisoformat(str(ts).replace("Z",""))
        except: 
            continue
        if published < since_ts: continue
        title = (n.get("title") or "").lower()
        s = 0.5
        for kw in NEWS_KEYWORDS:
            if kw in title:
                s += 1.0
        score += min(s,3.0)
    return min(score,10.0)

def compute_gap_and_volume_metrics(ticker):
    tk = yf.Ticker(ticker)
    hist = tk.history(period="6mo")
    if hist.empty or len(hist) < VOL_SMA_WINDOW+2: return None
    hist["ADV"] = hist["Volume"].rolling(VOL_SMA_WINDOW).mean()
    last, prev = hist.iloc[-1], hist.iloc[-2]
    gap_pct = (last["Open"] - prev["Close"]) / prev["Close"]
    vol_ratio = last["Volume"] / max(1.0, last["ADV"])
    return dict(gap_pct=float(gap_pct), vol_ratio=float(vol_ratio), close=float(last["Close"]), date=str(last.name.date()))

def compute_diff():
    prev_content = os.popen("git show HEAD~1:qm1w.txt 2>/dev/null").read()
    prev = set([t.strip() for line in prev_content.splitlines() for t in line.split(",") if t.strip()])
    cur = set(load_tickers(UNIVERSE_FILE))
    added, removed = sorted(list(cur - prev)), sorted(list(prev - cur))
    return added, removed

def build():
    tickers = load_tickers(UNIVERSE_FILE)
    since_ts = dt.datetime.utcnow() - dt.timedelta(days=NEWS_LOOKBACK_DAYS)
    rows = []
    for t in tickers:
        try:
            metrics = compute_gap_and_volume_metrics(t)
            news = yf.Ticker(t).news or []
            news_score = get_news_score(news, since_ts)
            if metrics is None:
                rows.append(dict(ticker=t, overall=0.0, gap_pct=None, vol_ratio=None, fresh_catalyst_score=0.0, justified_story_score=0.0, rerating_potential=0.0))
                continue
            fresh = min(5.0, news_score)
            inst = 5.0 if (metrics["gap_pct"]>=GAP_THRESHOLD and metrics["vol_ratio"]>=VOL_RATIO_GOOD) else (3.0 if metrics["gap_pct"]>=0.05 and metrics["vol_ratio"]>=1.5 else (1.5 if metrics["vol_ratio"]>=1.2 else 0.0))
            justified = 4.0 if (fresh>=2.0 and inst>=3.0) else (2.0 if fresh>0 else 0.5)
            rerate = min(5.0, fresh + (inst/2.0))
            overall = round(fresh*0.4 + inst*0.35 + justified*0.15 + rerate*0.10,2)
            rows.append(dict(ticker=t, gap_pct=round(metrics["gap_pct"]*100,2), vol_ratio=round(metrics["vol_ratio"],2), fresh_catalyst_score=round(fresh,2), justified_story_score=round(justified,2), rerating_potential=round(rerate,2), overall=overall, last_date=metrics["date"], price=metrics["close"]))
        except Exception as e:
            rows.append(dict(ticker=t, overall=0.0, error=str(e)))

    df = pd.DataFrame(rows).sort_values(by=["overall","fresh_catalyst_score","vol_ratio"], ascending=[False,False,False])
    df.to_json("ep_report.json", orient="records", indent=2)

    added, removed = compute_diff()
    now = dt.datetime.utcnow().strftime("%Y-%m-%d %H:%M UTC")
    with open("ep_report.html","w") as f:
        f.write(f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"/><title>EP Screener</title>
<style>body{{font-family:Arial,sans-serif;margin:20px}}table{{border-collapse:collapse;width:100%}}th,td{{border:1px solid #ddd;padding:8px;text-align:center}}th{{background:#f7f7f7}}</style>
</head><body>
<h1>Qullamaggie EP Screener (Daily)</h1>
<p>Updated: {now}</p>
<p><b>Diff vs previous list:</b> Added: {', '.join(added) if added else '—'} | Removed: {', '.join(removed) if removed else '—'}</p>
{df.to_html(index=False)}
</body></html>""")

if __name__ == "__main__":
    build()
