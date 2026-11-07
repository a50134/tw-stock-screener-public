"""
us_bt.py - 美股策略回測（近 5 年）：台股用的策略搬到美股，看勝率如何（只發給自己：私人專案 us_bt.yml 執行）

股票：標普 500 成分股（維基百科）＋ us.py 的觀察名單
資料：Yahoo 日K（含成交量，用還原股價）、美國證管會 SEC 公開財報（companyfacts：EPS、營收、淨利、股東權益、負債、營業現金流）
  ・財報用「申報日」判斷當時看不看得到，不偷看未來
  ・現金流量表是今年累計，換成單季；第 4 季＝全年－前 3 季
策略（美股沒有外資／投信買賣超，改用「相對強弱」代替法人條件）：
  A. CAN SLIM（你的版本）：連 2 季 EPS 年增 >25%、近 2 年 EPS（近 4 季合計）每年成長 >25%、連 2 季營收年增 >25%、近 4 季 ROE >17%、最新一季 EPS >0
  B. 財報健檢：近 4 季營業現金流為正＋負債比 <60%
  C. 強勢股回檔月線量縮：60 日漲 >20%、碰月線收在上、5 日量 < 20 日量 7 成、月線上揚、站上季線
  D. 穩健動能：近 6 個月漲幅÷波動 排名前 15
回測：訊號隔天開盤買，抱 20／60 個交易日收盤賣，扣 0.3% 成本（手續費＋匯差），同一檔抱著時不重複買
用法：python us_bt.py [--max 600] > us_bt_latest.txt
"""
import datetime as dt
import json
import re
import statistics as st
import sys
import time
from collections import defaultdict

import requests

import us

SEC_UA = {"User-Agent": "tw-stock-screener research (github.com/a50134/tw-stock-screener-public)", "Accept-Encoding": "gzip, deflate"}
COST = 0.3
YEARS = 5


def log(*a):
    print(*a, file=sys.stderr, flush=True)


def sp500():
    try:
        h = requests.get("https://en.wikipedia.org/wiki/List_of_S%26P_500_companies", headers=us.UA, timeout=30).text
        tb = h[h.index('id="constituents"'):]
        tb = tb[:tb.index("</table>")]
        out = []
        for row in tb.split("<tr")[2:]:
            m = re.search(r"<td[^>]*>\s*<a[^>]*>([A-Z.\-]+)</a>", row)
            if m:
                out.append(m.group(1).replace(".", "-"))
        return out
    except Exception as e:
        log("標普 500 名單抓取失敗：", type(e).__name__)
        return []


def prices(t, years=YEARS + 1):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%dy&interval=1d&includeAdjustedClose=true" % (t, years)
    r = requests.get(url, headers=us.UA, timeout=30)
    r.raise_for_status()
    res = r.json()["chart"]["result"][0]
    q = res["indicators"]["quote"][0]
    adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
    out = []
    for i, ts in enumerate(res.get("timestamp") or []):
        c, a = q["close"][i], adj[i]
        if not c or not a:
            continue
        f = a / c  # 還原係數：開高低一起調整
        out.append((dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d"), (q["open"][i] or c) * f, (q["high"][i] or c) * f,
                    (q["low"][i] or c) * f, a, q["volume"][i] or 0))
    return out


def cik_map():
    """SEC 要求請求要有聯絡資訊；可以在私人專案的 Secrets 設 SEC_USER_AGENT（例如「名字 email」）。依序試，第一個成功的就沿用"""
    import os
    cands = [os.environ.get("SEC_USER_AGENT", "").strip(), SEC_UA["User-Agent"], "TwStockScreener research-bot@users.noreply.github.com", us.UA["User-Agent"]]
    for ua in [c for c in cands if c]:
        r = requests.get("https://www.sec.gov/files/company_tickers.json", headers={**SEC_UA, "User-Agent": ua}, timeout=30)
        log("SEC 代號對照：HTTP %d" % r.status_code)
        if r.status_code == 200:
            SEC_UA["User-Agent"] = ua
            break
        time.sleep(1)
    r.raise_for_status()
    return {v["ticker"].upper().replace(".", "-"): int(v["cik_str"]) for v in r.json().values()}


def days(a, b):
    return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days


def series(facts, names, unit, kind):
    """kind: 'flow'（損益：單季）、'ytd'（現金流：累計→單季）、'inst'（資產負債：期末）→ {期末日: (數值, 申報日)}"""
    for nm in names:
        u = (((facts.get("us-gaap") or {}).get(nm) or {}).get("units") or {}).get(unit)
        if not u:
            continue
        if kind == "inst":
            o = {}
            for x in u:
                if x.get("form", "").startswith(("10-Q", "10-K")):
                    e = x["end"]
                    if e not in o or x["filed"] < o[e][1]:
                        o[e] = (x["val"], x["filed"])
            if o:
                return o
            continue
        q, yr, ytd = {}, {}, defaultdict(dict)
        for x in u:
            if not x.get("start") or not x.get("form", "").startswith(("10-Q", "10-K")):
                continue
            d = days(x["start"], x["end"])
            key = x["end"]
            if 80 <= d <= 100 and (key not in q or x["filed"] < q[key][1]):
                q[key] = (x["val"], x["filed"])
            if 350 <= d <= 380 and (key not in yr or x["filed"] < yr[key][1]):
                yr[key] = (x["val"], x["filed"], x["start"])
            if kind == "ytd" and d >= 80:
                if key not in ytd[x["start"]] or x["filed"] < ytd[x["start"]][key][1]:
                    ytd[x["start"]][key] = (x["val"], x["filed"])
        if kind == "ytd":  # 累計 → 單季：同一個起點，依期末日相減
            for s0, m in ytd.items():
                prev = None
                for e in sorted(m):
                    v, f = m[e]
                    if prev is None:
                        if 80 <= days(s0, e) <= 100:
                            q.setdefault(e, (v, f))
                    elif 80 <= days(prev, e) <= 100:
                        q.setdefault(e, (v - m[prev][0], f))
                    prev = e
        else:  # 第 4 季＝全年－同一年度的前 3 季
            for e, (v, f, s0) in yr.items():
                if e in q:
                    continue
                inside = [k for k in q if s0 < k < e and days(s0, k) > 60]
                if len(inside) == 3:
                    q[e] = (v - sum(q[k][0] for k in inside), f)
        if q:
            return q
    return {}


def fundamentals(cik):
    r = requests.get("https://data.sec.gov/api/xbrl/companyfacts/CIK%010d.json" % cik, headers=SEC_UA, timeout=60)
    if r.status_code != 200:
        if r.status_code in (403, 429):
            log("SEC 財報：HTTP %d" % r.status_code)
        return []
    f = r.json().get("facts") or {}
    eps = series(f, ["EarningsPerShareDiluted", "EarningsPerShareBasic"], "USD/shares", "flow")
    rev = series(f, ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet", "RevenueFromContractWithCustomerIncludingAssessedTax"], "USD", "flow")
    ni = series(f, ["NetIncomeLoss", "ProfitLoss"], "USD", "flow")
    ocf = series(f, ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"], "USD", "ytd")
    eq = series(f, ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"], "USD", "inst")
    liab = series(f, ["Liabilities"], "USD", "inst")
    assets = series(f, ["Assets"], "USD", "inst")
    out = []
    for e in sorted(eps):
        if e < "2018-01-01":
            continue
        g = lambda m: m.get(e, (None, None))[0]
        out.append({"end": e, "filed": eps[e][1], "eps": eps[e][0], "rev": g(rev), "ni": g(ni), "ocf": g(ocf), "eq": g(eq), "liab": g(liab), "assets": g(assets)})
    return out


def yoy(q, i):
    """第 i 季和去年同季（期末日差 330～400 天）"""
    for j in range(i - 1, -1, -1):
        d = days(q[j]["end"], q[i]["end"])
        if 330 <= d <= 400:
            return q[j]
        if d > 400:
            break
    return None


def growth(a, b):
    if a is None or b is None:
        return None
    if b > 0:
        return (a / b - 1) * 100
    return 999 if a > 0 else None


def canslim(q):
    """q＝當時已申報的季報。回傳 (A 是否通過, B 財報健檢是否通過)"""
    if len(q) < 9:
        return False, None, None
    k = len(q) - 1
    g = [growth(q[i]["eps"], (yoy(q, i) or {}).get("eps")) for i in (k, k - 1)]
    rg = [growth(q[i]["rev"], (yoy(q, i) or {}).get("rev")) for i in (k, k - 1)]
    ttm = lambda i: sum(x["eps"] for x in q[i - 3:i + 1]) if i >= 3 and all(x["eps"] is not None for x in q[i - 3:i + 1]) else None
    a0, a1, a2 = ttm(k), ttm(k - 4), ttm(k - 8)
    ya = [growth(a0, a1), growth(a1, a2)]
    nis = [x["ni"] for x in q[-4:]]
    roe = sum(nis) / q[-1]["eq"] * 100 if all(v is not None for v in nis) and q[-1]["eq"] and q[-1]["eq"] > 0 else None
    A = (all(x is not None and x > 25 for x in g) and all(x is not None and x > 25 for x in ya)
         and all(x is not None and x > 25 for x in rg) and roe is not None and roe > 17 and (q[-1]["eps"] or 0) > 0)
    oc = [x["ocf"] for x in q[-4:]]
    ocf = sum(oc) if all(v is not None for v in oc) else None
    debt = q[-1]["liab"] / q[-1]["assets"] * 100 if q[-1]["liab"] is not None and q[-1]["assets"] else None
    B = None if ocf is None and debt is None else (ocf is None or ocf > 0) and (debt is None or debt < 60)
    B_ocf = None if ocf is None else ocf > 0
    return A, B, B_ocf


def ma(c, n, t):
    return sum(c[t - n + 1:t + 1]) / n


def main():
    mx = int(sys.argv[sys.argv.index("--max") + 1]) if "--max" in sys.argv else 600
    names = dict(us.UNIVERSE)
    tick = [t for t in sp500() + list(names) if t not in ("VOO", "VTI", "SCHD", "VYM", "DGRO", "HDV", "NOBL")]
    tick = list(dict.fromkeys(tick))[:mx]
    log("股票 %d 檔" % len(tick))
    try:
        cm = cik_map()
    except Exception as e:
        log("SEC 代號對照抓不到：", type(e).__name__)
        cm = {}
    P, Q = {}, {}
    for i, t in enumerate(tick, 1):
        if i % 50 == 0:
            log("  %d/%d" % (i, len(tick)))
        try:
            p = prices(t)
            if len(p) > 300:
                P[t] = p
        except Exception:
            pass
        if t in cm:
            try:
                Q[t] = fundamentals(cm[t])
            except Exception:
                pass
            time.sleep(0.12)  # SEC 每秒最多 10 次
    bench = prices("VOO")
    log("價格 %d 檔、財報 %d 檔" % (len(P), sum(1 for v in Q.values() if v)))
    # 共同日期
    D = [x[0] for x in bench]
    di = {d: i for i, d in enumerate(D)}
    N = len(D)
    start = max(260, next(i for i, d in enumerate(D) if d >= (dt.date.fromisoformat(D[-1]) - dt.timedelta(days=365 * YEARS)).isoformat()))
    S = {}
    for t, p in P.items():
        o, h, l, c, v = [None] * N, [None] * N, [None] * N, [None] * N, [0] * N
        for d, a, b, x, y, z in p:
            if d in di:
                k = di[d]
                o[k], h[k], l[k], c[k], v[k] = a, b, x, y, z
        for k in range(1, N):  # 補空值
            if c[k] is None and c[k - 1] is not None:
                o[k] = h[k] = l[k] = c[k] = c[k - 1]
        if c[start - 260] is None:
            continue
        S[t] = (o, h, l, c, v)
    # 穩健動能排名（每天）
    vam = {}
    for t_ in range(start, N):
        sc = []
        for t, (o, h, l, c, v) in S.items():
            r = [c[k] / c[k - 1] - 1 for k in range(t_ - 125, t_ + 1)]
            sd = st.pstdev(r)
            if sd > 0:
                sc.append((-(c[t_] / c[t_ - 126] - 1) / sd, t))
        vam[t_] = set(x[1] for x in sorted(sc)[:15])
    # 相對強弱（近 120 日漲幅前 30%）
    rs = {}
    for t_ in range(start, N):
        arr = sorted((S[t][3][t_] / S[t][3][t_ - 120], t) for t in S)
        rs[t_] = set(x[1] for x in arr[int(len(arr) * 0.7):])
    sig = defaultdict(lambda: defaultdict(list))
    for t, (o, h, l, c, v) in S.items():
        q_all = Q.get(t) or []
        qi, last_qi, cs = 0, -1, (False, None, None)
        for t_ in range(start, N - 1):
            day = D[t_]
            while qi < len(q_all) and q_all[qi]["filed"] <= day:
                qi += 1
            if qi != last_qi:  # 有新季報才重算
                cs = canslim(q_all[:qi]) if qi else (False, None, None)
                last_qi = qi
            A, B, Bo = cs
            m20, m60 = ma(c, 20, t_), ma(c, 60, t_)
            vol20 = sum(v[t_ - 19:t_ + 1]) / 20
            sig["隨便買（全部股票每天都買）"][t].append(t_)
            if A:
                sig["CAN SLIM（你的版本）"][t].append(t_)
                if B is not False:
                    sig["CAN SLIM＋財報健檢"][t].append(t_)
                if Bo is not False:
                    sig["CAN SLIM＋只看現金流（不看負債比）"][t].append(t_)
                if t in rs[t_]:
                    sig["CAN SLIM＋相對強弱前 30%"][t].append(t_)
                if B is not False and t in rs[t_]:
                    sig["CAN SLIM＋健檢＋相對強弱"][t].append(t_)
                if c[t_] > ma(c, 50, t_):
                    sig["CAN SLIM＋站上 50 日線"][t].append(t_)
            pull = (c[t_] / c[t_ - 60] > 1.2 and l[t_] <= m20 * 1.01 and c[t_] > m20 and vol20 > 0
                    and sum(v[t_ - 4:t_ + 1]) / 5 < vol20 * 0.7 and m20 > ma(c, 20, t_ - 1) and c[t_] > m60)
            if pull:
                sig["強勢股回檔月線量縮"][t].append(t_)
                if B is not False:
                    sig["強勢回檔＋財報健檢"][t].append(t_)
            if t in vam[t_]:
                sig["穩健動能（前 15 名）"][t].append(t_)
                if B is not False:
                    sig["穩健動能＋財報健檢"][t].append(t_)
    # 回測
    def bt(s, hold):
        R, Y = [], defaultdict(list)
        for t, ts in s.items():
            o, h, l, c, v = S[t]
            last = -1
            for t_ in ts:
                if t_ <= last or t_ + hold >= N:
                    continue
                e, x = o[t_ + 1], c[t_ + hold]
                if e and x:
                    r = (x / e - 1) * 100 - COST
                    R.append(r)
                    Y[D[t_][:4]].append(r)
                    last = t_ + hold
        return R, Y
    vb = [x[4] for x in bench]
    v0 = vb[start]
    L = ["🇺🇸 美股策略回測（近 %d 年：%s～%s，%d 檔有價格、%d 檔有 SEC 財報；只有你看得到）" % (YEARS, D[start], D[-1], len(S), sum(1 for v in Q.values() if v)),
         "方法：訊號隔天開盤買、抱 20／60 個交易日收盤賣、扣 0.3%% 成本；同期 VOO（標普 500）買進抱著 %+.0f%%" % ((vb[-1] / v0 - 1) * 100), ""]
    rows = []
    for nm, s in sig.items():
        r20, y20 = bt(s, 20)
        r60, _ = bt(s, 60)
        if not r20:
            L.append("・%s：這 5 年沒有訊號" % nm)
            continue
        f = lambda R: "%d 次、勝率 %.0f%%、平均 %+.1f%%、中位 %+.1f%%" % (len(R), sum(x > 0 for x in R) / len(R) * 100, st.mean(R), st.median(R)) if R else "—"
        yrs = "、".join("%s %+.0f%%" % (y, st.mean(v)) for y, v in sorted(y20.items()))
        L.append("・%s\n　抱 20 天：%s\n　抱 60 天：%s\n　每年平均（抱 20 天）：%s" % (nm, f(r20), f(r60), yrs))
        rows.append({"name": nm, "n20": len(r20), "win20": sum(x > 0 for x in r20) / len(r20) * 100, "avg20": st.mean(r20),
                     "n60": len(r60), "win60": sum(x > 0 for x in r60) / len(r60) * 100 if r60 else None, "avg60": st.mean(r60) if r60 else None})
    # 今天符合的股票
    T = N - 2
    now = defaultdict(list)
    for nm, s in sig.items():
        if nm.startswith("隨便"):
            continue
        for t, ts in s.items():
            if ts and ts[-1] >= T - 1:
                now[nm].append(t)
    L.append("")
    L.append("📌 最近符合的股票（%s）：" % D[-1])
    for nm, ts in now.items():
        L.append("・%s：%s" % (nm, "、".join(sorted(ts)[:20]) or "—"))
    print("\n".join(L))
    json.dump({"asOf": D[-1], "rows": rows, "now": now}, open("us_bt.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
