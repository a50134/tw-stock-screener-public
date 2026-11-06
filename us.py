"""
us.py - 美股：持股追蹤＋「跌深又穩定配息」篩選＋依預算算買幾股＋查個股 5 年回測（只發 Discord）

設定在私人專案 sop_config.json 的 us：
  {"budget_twd": 100000,                                   # 美股預算（台幣）
   "holdings": [{"t": "KO", "qty": 1, "cost": 58.5}, ...],  # 你的美股持股（成本美元）
   "watch": ["O", "TGT"]}                                   # 想另外追蹤的（選填）
資料：Yahoo Finance 日 K（含配息、分割；不佔 FinMind 額度），抓不到才用 FinMind 的 USStockPrice
匯率：FinMind 台銀即期賣出；抓不到用 32

篩選「跌深配息」的規則（固定、可回測）：
  殖利率 ≥ 2.5%（≥ 4% 再加分）、近 5 年每年都有配息、近 3 年股利沒有被砍、
  離 52 週高點跌 12% 以上（20% 以上再加分）、RSI < 35（短線超跌）、5 年年化報酬 > 5%（體質好）、
  在 5 年高低區間的 40% 以下（位階低）
每檔最多放預算的 30%，分 3 批買（現價／再跌 5%／再跌 10%），美股可以只買 1 股

用法：python us.py                # 印出今晚的美股報告（用 sop_config.json 的 us 設定）
      python us.py KO MMM          # 查個股（含 5 年回測，和 VOO 比）
"""
import datetime as dt
import json
import os
import statistics as st
import sys
import time

import requests

DIR = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64)"}
# 預設篩選名單：大盤／高股息 ETF＋長期穩定配息的大型股（不含純 AI 題材股）
UNIVERSE = {
    "VOO": "標普 500 ETF", "VTI": "全美股市 ETF", "SCHD": "美國高股息 ETF", "VYM": "高股息 ETF", "DGRO": "股利成長 ETF",
    "HDV": "核心高股息 ETF", "NOBL": "股利貴族 ETF",
    "KO": "可口可樂", "PEP": "百事", "PG": "寶僑", "CL": "高露潔", "KMB": "金百利", "MO": "奧馳亞（菸草）", "PM": "菲利普莫里斯",
    "JNJ": "嬌生", "MRK": "默克藥廠", "ABBV": "艾伯維", "PFE": "輝瑞", "AMGN": "安進", "BMY": "必治妥",
    "MCD": "麥當勞", "HD": "家得寶", "LOW": "勞氏", "TGT": "Target", "WMT": "沃爾瑪", "COST": "好市多",
    "TXN": "德州儀器", "IBM": "IBM", "CSCO": "思科", "MSFT": "微軟", "AAPL": "蘋果",
    "XOM": "埃克森美孚", "CVX": "雪佛龍", "VZ": "Verizon", "T": "AT&T", "O": "Realty Income（每月配息 REIT）",
    "MMM": "3M", "UPS": "UPS", "ADP": "ADP", "LMT": "洛克希德", "NEE": "NextEra 能源", "DUK": "杜克能源", "SO": "南方電力",
    "JPM": "摩根大通", "BLK": "貝萊德",
}


def yahoo(t, years=6):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%dy&interval=1d&events=div%%2Csplits&includeAdjustedClose=true" % (t, years)
    r = requests.get(url, headers=UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
    rows = []
    for i, ts in enumerate(res.get("timestamp") or []):
        c = q["close"][i]
        if c is None:
            continue
        rows.append({"date": dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"), "open": q["open"][i] or c, "high": q["high"][i] or c,
                     "low": q["low"][i] or c, "close": c, "adj": adj[i] or c})
    divs = [(dt.datetime.utcfromtimestamp(int(k)).strftime("%Y-%m-%d"), v["amount"]) for k, v in ((res.get("events") or {}).get("dividends") or {}).items()]
    return rows, sorted(divs), res.get("meta", {}).get("longName") or res.get("meta", {}).get("shortName")


def finmind(t, years=6):
    import fetch_finmind
    s0 = (dt.date.today() - dt.timedelta(days=365 * years)).isoformat()
    data = fetch_finmind.get("USStockPrice", t, s0)
    rows, divs = [], []
    for d in data:
        c = d.get("Close")
        if not c:
            continue
        rows.append({"date": d["date"], "open": d.get("Open") or c, "high": d.get("High") or c, "low": d.get("Low") or c, "close": c, "adj": d.get("Adj_Close") or c})
    for i in range(1, len(rows)):  # 從還原權值的變化推算配息（除息日：調整係數跳一下）
        f0, f1 = rows[i - 1]["adj"] / rows[i - 1]["close"], rows[i]["adj"] / rows[i]["close"]
        if f1 > f0:
            d_ = rows[i - 1]["close"] * (1 - f0 / f1)
            if 0 < d_ < rows[i - 1]["close"] * 0.15:
                divs.append((rows[i]["date"], round(d_, 4)))
    return rows, divs, None


def history(t):
    for fn in (yahoo, finmind):
        try:
            rows, divs, nm = fn(t)
            if len(rows) > 200:
                return rows, divs, nm
        except Exception as e:
            print("  美股資料抓取失敗（%s）：%s" % (fn.__name__, type(e).__name__), file=sys.stderr)
        time.sleep(0.5)
    return [], [], None


def fx():
    try:
        import fetch_finmind
        d = fetch_finmind.get("TaiwanExchangeRate", "USD", (dt.date.today() - dt.timedelta(days=10)).isoformat())
        v = [x.get("spot_sell") for x in d if x.get("spot_sell")]
        if v:
            return float(v[-1])
    except Exception:
        pass
    try:
        rows, _, _ = yahoo("TWD=X", 1)
        return rows[-1]["close"]
    except Exception:
        return 32.0


def rsi(c, n=14):
    g = l = 0.0
    for i in range(len(c) - n, len(c)):
        d = c[i] - c[i - 1]
        g, l = g + max(d, 0), l + max(-d, 0)
    return 100 - 100 / (1 + g / l) if l else 100


def stats(rows, divs):
    c = [x["close"] for x in rows]
    a = [x["adj"] for x in rows]
    T = len(c) - 1
    last = dt.date.fromisoformat(rows[-1]["date"])
    y1 = (last - dt.timedelta(days=365)).isoformat()
    w52 = [x for x in rows if x["date"] >= y1]
    hi52, lo52 = max(x["high"] for x in w52), min(x["low"] for x in w52)
    ttm = sum(v for d, v in divs if d >= y1)
    y3 = (last - dt.timedelta(days=365 * 3)).isoformat()
    y4 = (last - dt.timedelta(days=365 * 4)).isoformat()
    ttm3 = sum(v for d, v in divs if y4 <= d < y3)
    yrs = {d[:4] for d, _ in divs}
    paid5 = sum(1 for k in range(1, 6) if str(last.year - k) in yrs)
    s5 = (last - dt.timedelta(days=int(365.25 * 5))).isoformat()
    i5 = next((i for i, x in enumerate(rows) if x["date"] >= s5), 0)
    days = (last - dt.date.fromisoformat(rows[i5]["date"])).days
    cagr = ((a[T] / a[i5]) ** (365.25 / days) - 1) * 100 if days > 300 and a[i5] > 0 else None
    pk, mdd = a[i5], 0
    for x in a[i5:]:
        pk = max(pk, x)
        mdd = min(mdd, x / pk - 1)
    hi5, lo5 = max(x["high"] for x in rows[i5:]), min(x["low"] for x in rows[i5:])
    return {"c": c[T], "chg": (c[T] / c[T - 1] - 1) * 100, "date": rows[-1]["date"], "hi52": hi52, "lo52": lo52,
            "drop": (c[T] / hi52 - 1) * 100, "ma50": sum(c[-50:]) / 50, "ma200": sum(c[-200:]) / 200, "rsi": rsi(c),
            "ttm": ttm, "yld": ttm / c[T] * 100 if c[T] else 0, "cut": ttm3 > 0 and ttm < ttm3 * 0.9, "paid5": paid5,
            "cagr": cagr, "mdd": mdd * 100, "pos5": (c[T] - lo5) / (hi5 - lo5) * 100 if hi5 > lo5 else 50}


def score(S):
    r = []
    if S["yld"] >= 2.5:
        r.append("殖利率 %.1f%%" % S["yld"])
    pts = (S["yld"] >= 2.5) + (S["yld"] >= 4) + (S["paid5"] >= 5) + (S["drop"] <= -12) + (S["drop"] <= -20) + \
        (S["rsi"] < 35) + bool(S["cagr"] and S["cagr"] > 5) + (S["pos5"] <= 40) - 2 * S["cut"]
    if S["paid5"] >= 5:
        r.append("5 年都有配息")
    if S["drop"] <= -12:
        r.append("離 52 週高點 %.0f%%" % S["drop"])
    if S["rsi"] < 35:
        r.append("RSI %.0f 超跌" % S["rsi"])
    if S["pos5"] <= 40:
        r.append("5 年區間 %.0f%% 低位階" % S["pos5"])
    if S["cut"]:
        r.append("⚠️ 股利比 3 年前少")
    return pts, r


def plan(S, budget_usd):
    """分 3 批：現價 40%、再跌 5% 30%、再跌 10% 30%（整股；買不起就 1 股）"""
    c = S["c"]
    ps = [c, c * 0.95, c * 0.90]
    n = [int(budget_usd * w / p) for w, p in zip((0.4, 0.3, 0.3), ps)]
    if not any(n):
        return "預算放不下 1 股（%s 美元）" % _p(c), 0
    txt = "、".join("%s 以下買 %d 股" % (_p(p), k) for p, k in zip(ps, n) if k)
    return txt, sum(p * k for p, k in zip(ps, n))


def _p(x):
    return ("%.2f" % x).rstrip("0").rstrip(".")


def report(cfg):
    U = cfg.get("us") or {}
    budget = float(U.get("budget_twd") or 100000)
    rate = fx()
    busd = budget / rate
    hold = U.get("holdings") or []
    tickers = list(dict.fromkeys(["VOO"] + [h["t"] for h in hold] + list(U.get("watch") or []) + list(UNIVERSE)))
    S, names = {}, {}
    for k, t in enumerate(tickers, 1):
        rows, divs, nm = history(t)
        if rows:
            S[t] = stats(rows, divs)
            names[t] = UNIVERSE.get(t) or nm or t
        if k % 10 == 0:
            print("美股資料 %d/%d" % (k, len(tickers)), flush=True)
        time.sleep(0.3)
    if not S:
        return "🇺🇸 美股：今天抓不到資料（Yahoo／FinMind 都失敗），明天再試"
    d0 = max(x["date"] for x in S.values())
    L = ["🇺🇸 美股（%s 收盤，匯率 %.2f，預算 %s 台幣 ≈ %s 美元）" % (d0, rate, "{:,.0f}".format(budget), "{:,.0f}".format(busd))]
    v = S.get("VOO")
    if v:
        L.append("・大盤 VOO %s（今天 %+.1f%%）：離 52 週高點 %.0f%%，%s 200 日均線；%s" % (
            _p(v["c"]), v["chg"], v["drop"], "站上" if v["c"] > v["ma200"] else "跌破", "大跌後分批進場，不要一次買完" if v["drop"] <= -10 else "還在正常範圍"))
    used = 0.0
    if hold:
        L.append("")
        L.append("【你的美股持股】")
        for h in hold:
            x = S.get(h["t"])
            if not x:
                L.append("・%s：今天抓不到資料" % h["t"])
                continue
            q, cost = float(h.get("qty") or 1), float(h["cost"])
            pnl = (x["c"] - cost) * q
            used += cost * q
            note = "比 200 日均線高 %.0f%%，偏高不加碼" % ((x["c"] / x["ma200"] - 1) * 100) if x["c"] > x["ma200"] * 1.15 else \
                "跌破 200 日均線，趨勢轉弱，留意" if x["c"] < x["ma200"] else "趨勢正常，續抱"
            L.append("・%s %s：%s 股，成本 %s → 現價 %s（今天 %+.1f%%），%s 美元（%+.0f%%，約 %s 台幣）；殖利率 %.1f%%、以你的成本算 %.1f%%｜%s" % (
                h["t"], names.get(h["t"], ""), _p(q), _p(cost), _p(x["c"]), x["chg"], "{:+,.0f}".format(pnl), (x["c"] / cost - 1) * 100,
                "{:+,.0f}".format(pnl * rate), x["yld"], x["ttm"] / cost * 100, note))
    # 跌深配息篩選
    cand = []
    for t, x in S.items():
        if t in [h["t"] for h in hold] and x["drop"] > -12:
            continue
        pts, why = score(x)
        if x["yld"] >= 2 and x["drop"] <= -8 and not x["cut"]:
            cand.append((pts, t, x, why))
    cand.sort(key=lambda z: (-z[0], z[2]["drop"]))
    L.append("")
    if not cand:
        L.append("【跌深配息候選】今天沒有符合「殖利率 2% 以上、離高點跌 8% 以上、股利沒被砍」的，先不用急著買")
    else:
        L.append("【跌深配息候選】（每檔最多預算 30%%＝%s 美元，分 3 批）" % _p(busd * 0.3))
        left = max(0.0, busd - used)
        for pts, t, x, why in cand[:5]:
            txt, need = plan(x, min(busd * 0.3, left))
            L.append("・%s %s：%s（今天 %+.1f%%）｜%s｜5 年年化 %s、最慘跌 %.0f%%｜➜ %s" % (
                t, names.get(t, ""), _p(x["c"]), x["chg"], "、".join(why) or "—", "%+.1f%%" % x["cagr"] if x["cagr"] is not None else "—", x["mdd"], txt))
        L.append("規則：殖利率、5 年都配息、離高點跌幅、RSI 超跌、5 年報酬、位階打分數；股利被砍的不列。想買哪檔先用「查美股」看 5 年回測")
    L.append("依 Yahoo Finance／FinMind 公開資料與固定規則整理，不是投資建議；美股還有約 30% 股利稅（美國先扣）與換匯成本。")
    return "\n".join(L)


def lookup(t, get=None):
    """查美股：現況＋5 年回測（和 VOO 比）"""
    import pretrade
    rows, divs, nm = history(t)
    if not rows:
        return "【%s】抓不到美股資料（代號打錯或還沒上市）" % t
    x = stats(rows, divs)
    pts, why = score(x)
    L = ["【%s %s】收 %s 美元（今天 %+.1f%%）" % (t, UNIVERSE.get(t) or nm or "", _p(x["c"]), x["chg"]),
         "・52 週 %s～%s（離高點 %.0f%%）；50 日均線 %s、200 日均線 %s；RSI %.0f" % (_p(x["lo52"]), _p(x["hi52"]), x["drop"], _p(x["ma50"]), _p(x["ma200"]), x["rsi"]),
         "・配息：近一年 %s 美元，殖利率 %.1f%%；近 5 年有配息 %d 年%s" % (_p(x["ttm"]), x["yld"], x["paid5"], "；⚠️ 股利比 3 年前少" if x["cut"] else ""),
         "・跌深配息分數 %d：%s" % (pts, "、".join(why) or "—")]
    br, _, _ = history("VOO") if t != "VOO" else ([], [], None)
    conv = lambda R: [{"date": r["date"], "open": r["open"] * r["adj"] / r["close"], "max": r["high"] * r["adj"] / r["close"],
                       "min": r["low"] * r["adj"] / r["close"], "close": r["adj"]} for r in R]
    try:
        L.append(pretrade.analyze(t, t, conv(rows), [], [], [], conv(br), [], bench="VOO", pre_adjusted=True))
    except Exception as e:
        L.append("・5 年回測失敗：%s" % type(e).__name__)
    return "\n".join(L)


if __name__ == "__main__":
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if args:
        for a in args:
            print(lookup(a.upper()))
            print()
    else:
        p = os.path.join(DIR, "sop_config.json")
        print(report(json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}))
