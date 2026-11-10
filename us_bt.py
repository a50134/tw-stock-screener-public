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
NAMES = {}
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
                t = m.group(1).replace(".", "-")
                n = re.findall(r"<a[^>]*>([^<]+)</a>", row)
                NAMES[t] = n[1] if len(n) > 1 else t
                out.append(t)
        return out
    except Exception as e:
        log("標普 500 名單抓取失敗：", type(e).__name__)
        return []


def prices(t, years=YEARS + 1):
    url = "https://query1.finance.yahoo.com/v8/finance/chart/%s?range=%dy&interval=1d&events=div%%2Csplits&includeAdjustedClose=true" % (t, years)
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
                    (q["low"][i] or c) * f, a, q["volume"][i] or 0, c))  # 最後一個是當時股價（算本益比、殖利率用）
    divs = sorted((dt.datetime.fromtimestamp(int(k), dt.timezone.utc).strftime("%Y-%m-%d"), v["amount"]) for k, v in ((res.get("events") or {}).get("dividends") or {}).items())
    return out, divs


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


def series(facts, names, unit, kind, restate=False):
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
            if 80 <= d <= 100:
                if key not in q:
                    q[key] = (x["val"], x["filed"], x["filed"])
                else:
                    v0, f0, c0 = q[key]  # 數值、第一次申報日、採用數值的申報日
                    if restate:  # 用最後一次申報的數字（股票分割後重編過）
                        q[key] = (x["val"] if x["filed"] > c0 else v0, min(f0, x["filed"]), max(c0, x["filed"]))
                    else:
                        q[key] = (x["val"] if x["filed"] < c0 else v0, min(f0, x["filed"]), min(c0, x["filed"]))
            if 350 <= d <= 380 and (key not in yr or x["filed"] < yr[key][1]):
                yr[key] = (x["val"], x["filed"], x["start"])
            if kind == "ytd" and d >= 80:
                if key not in ytd[x["start"]] or x["filed"] < ytd[x["start"]][key][1]:
                    ytd[x["start"]][key] = (x["val"], x["filed"])
        q = {k: (v[0], v[1]) for k, v in q.items()}
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
    eps = series(f, ["EarningsPerShareDiluted", "EarningsPerShareBasic"], "USD/shares", "flow", restate=True)
    gp = series(f, ["GrossProfit"], "USD", "flow")
    op = series(f, ["OperatingIncomeLoss"], "USD", "flow")
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
        out.append({"end": e, "filed": eps[e][1], "eps": eps[e][0], "rev": g(rev), "ni": g(ni), "ocf": g(ocf), "eq": g(eq), "liab": g(liab), "assets": g(assets), "gp": g(gp), "op": g(op)})
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


def rsi(c, t, n=14):
    up = sum(max(c[i] - c[i - 1], 0) for i in range(t - n + 1, t + 1))
    dn = sum(max(c[i - 1] - c[i], 0) for i in range(t - n + 1, t + 1))
    return 100 if dn == 0 else 100 - 100 / (1 + up / dn)


def step(p):
    """整數關卡間距：股價 45 → 5（關卡 50）、175 → 50（關卡 200）、1,200 → 500"""
    import math
    e = 10 ** math.floor(math.log10(p))
    return e / 2 if p < e * 5 else e


def dip_signals(sig, t, t_, o, h, l, c, v, q, B, vb):
    """好公司跌深抄底（美股版「大跌撿好股」，使用者 2026-11-10 提議，像輝達這種賺很多、跌很深的大公司）
    好公司：近 4 季 EPS 合計 > 0、而且比一年前多（還在成長）、財報健檢沒有不過
    跌深：比近一年高點跌 25% 以上（另算 35% 的版本）
    不是系統性衰退：標普 500（VOO）在 200 日線上（另算不看大盤的版本）
    進場訊號（比較哪個好）：每天都買、超賣往上勾、破整數關卡＋超賣背離（使用者的第 1 批）、站回 5 日線（第 2 批）"""
    import math
    if len(q) < 8:
        return
    e4, e8 = [x["eps"] for x in q[-4:]], [x["eps"] for x in q[-8:-4]]
    if not all(x is not None for x in e4 + e8) or sum(e4) <= 0 or sum(e4) < sum(e8) or B is False:
        return
    hi = max(c[t_ - 251:t_ + 1])
    dd = c[t_] / hi - 1
    if dd > -0.25:
        return
    add = lambda nm: sig[nm][t].append(t_)
    ok_mkt = vb[t_] > ma(vb, 200, t_)
    r0, r1 = rsi(c, t_), rsi(c, t_ - 1)
    hook = r1 < 30 and r0 > r1
    lo20 = min(c[t_ - 20:t_])
    i_lo = c.index(lo20, t_ - 20, t_)
    div = c[t_] <= lo20 and r0 > rsi(c, i_lo) + 2
    st_ = step(c[t_])
    lv = math.ceil(c[t_] / st_) * st_
    broke = c[t_] < lv and any(c[i] > lv for i in range(t_ - 10, t_))  # 近 10 天內跌破現價上面最近的整數關卡
    m5 = ma(c, 5, t_)
    back5 = c[t_] > m5 and c[t_ - 1] > ma(c, 5, t_ - 1) and c[t_ - 2] <= ma(c, 5, t_ - 2)
    add("抄底：好公司跌深 25%（每天都買，不看大盤）")
    if not ok_mkt:
        return
    add("抄底：好公司跌深 25%（每天都買）")
    if dd <= -0.35:
        add("抄底：好公司跌深 35%（每天都買）")
    if hook:
        add("抄底：跌深 25%＋超賣往上勾")
    if broke and (div or hook):
        add("抄底：跌深 25%＋破整數關卡＋超賣背離（你的第 1 批）")
        if dd <= -0.35:
            add("抄底：跌深 35%＋破整數關卡＋超賣背離")
    if back5:
        add("抄底：跌深 25%＋站回 5 日線（第 2 批）")


def ema(x, n):
    out, k, e = [None] * len(x), 2 / (n + 1), None
    for i, v in enumerate(x):
        if v is None:
            continue
        e = v if e is None else v * k + e * (1 - k)
        out[i] = e
    return out


def indicators(h, l, c):
    n = len(c)
    first = next(i for i in range(n) if c[i] is not None)
    days_ = list(range(first + 9, n))
    # 日 KD：每天用前 9 天
    Kd, Dd, k, d = [None] * n, [None] * n, 50.0, 50.0
    for i in days_:
        lo, hi = min(l[i - 8:i + 1]), max(h[i - 8:i + 1])
        rsv = (c[i] - lo) / (hi - lo) * 100 if hi > lo else 50
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
        Kd[i], Dd[i] = k, d
    # 週 KD：每 5 個交易日一根（用最近 45 天的高低）
    Kw, Dw, k, d = [None] * n, [None] * n, 50.0, 50.0
    for i in range(first + 45, n):
        if (i - first) % 5:
            Kw[i], Dw[i] = Kw[i - 1], Dw[i - 1]
            continue
        lo, hi = min(l[i - 44:i + 1]), max(h[i - 44:i + 1])
        rsv = (c[i] - lo) / (hi - lo) * 100 if hi > lo else 50
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
        Kw[i], Dw[i] = k, d
    e12, e26 = ema(c, 12), ema(c, 26)
    dif = [a - b if a is not None and b is not None else None for a, b in zip(e12, e26)]
    sg = ema(dif, 9)
    bw, up = [None] * n, [None] * n
    for i in range(first + 20, n):
        w = c[i - 19:i + 1]
        m = sum(w) / 20
        sd = st.pstdev(w)
        up[i], bw[i] = m + 2 * sd, 4 * sd / m * 100 if m else None
    return {"K": Kd, "D": Dd, "Kw": Kw, "Dw": Dw, "dif": dif, "sig": sg, "bw": bw, "up": up}


def cross(a, b, t, k):
    """近 k 天內 a 由下往上穿過 b"""
    return any(a[i] is not None and a[i - 1] is not None and b[i] is not None and b[i - 1] is not None and a[i - 1] <= b[i - 1] and a[i] > b[i]
               for i in range(t - k + 1, t + 1))


def extra(sig, t, t_, o, h, l, c, v, I, q, px, dv, B):
    """之前在台股刪掉（或台股才有）的策略，改成美股版：沒有法人、融資資料的條件拿掉"""
    m5, m20, m60 = ma(c, 5, t_), ma(c, 20, t_), ma(c, 60, t_)
    vol20 = sum(v[t_ - 19:t_ + 1]) / 20
    add = lambda nm: sig[nm][t].append(t_)
    # s3 量價突破：創 60 日新高＋爆量 1.5 倍＋均線多頭排列
    if c[t_] >= max(c[t_ - 59:t_ + 1]) and v[t_] > vol20 * 1.5 and m5 > m20 > m60:
        add("量價突破（台股已刪）")
    # s6 低檔轉強：離 60 日低點 8% 內＋KD 金叉（K<40）＋MACD 金叉
    near_low = c[t_] <= min(c[t_ - 59:t_ + 1]) * 1.08
    kdx = cross(I["K"], I["D"], t_, 3) and (I["K"][t_] or 99) < 40
    mx = cross(I["dif"], I["sig"], t_, 5)
    if near_low and kdx and mx:
        add("低檔轉強（台股已刪）")
    wk = cross(I["Kw"], I["Dw"], t_, 5)
    if near_low and (kdx or mx) and wk:
        add("低檔轉強＋週KD金叉（台股已刪）")
    # s10 週 KD 金叉＋日 KD 向上
    if cross(I["Kw"], I["Dw"], t_, 1) and I["K"][t_] is not None and I["K"][t_] > I["D"][t_] and (I["Kw"][t_] or 99) < 50:
        add("週KD金叉＋日KD多方（台股已刪）")
    # s8 布林開口：10 天內帶寬 < 5%＋上軌上翹 > 1%＋帶寬 < 20%
    bw, up = I["bw"], I["up"]
    if bw[t_] is not None and up[t_ - 1] and any(x is not None and x < 5 for x in bw[t_ - 9:t_ + 1]) and (up[t_] / up[t_ - 1] - 1) * 100 > 1 and bw[t_] < 20:
        add("布林開口（台股已刪）")
    # s16 跌深站回月線：比 60 日高點跌 20% 以上＋今天剛站回月線
    if c[t_] <= max(c[t_ - 59:t_ + 1]) * 0.8 and c[t_] > m20 and c[t_ - 1] <= ma(c, 20, t_ - 1):
        add("跌深站回月線（台股已刪）")
    # 需要財報的
    if len(q) >= 8 and px:
        eps4 = [x["eps"] for x in q[-4:]]
        if all(e is not None for e in eps4):
            ttm = sum(eps4)
            pe = px / ttm if ttm > 0 else None
            dy = dv / px * 100
            nis = [x["ni"] for x in q[-4:]]
            eq = q[-1]["eq"]
            roe = sum(nis) / eq * 100 if all(n_ is not None for n_ in nis) and eq and eq > 0 else None
            sh = sum(nis) / ttm if all(n_ is not None for n_ in nis) and ttm else None  # 推算股數
            pb = px / (eq / sh) if sh and eq and eq > 0 and sh > 0 else None
            # s4 高殖利率低本益比：殖利率 > 4%、本益比 < 15、站上季線
            if pe and dy > 4 and pe < 15 and c[t_] > m60:
                add("高殖利率低本益比（台股已刪）")
            # s14 價值股：近 4 季 EPS 都 > 0（必要）＋本益比<12、淨值比<1.5、殖利率>5%、ROE>10% 至少 3 項
            if all(e > 0 for e in eps4) and sum([bool(pe and pe < 12), bool(pb and pb < 1.5), dy > 5, bool(roe and roe > 10)]) >= 3:
                add("價值股（台股已刪）")
            # s13 彼得林區：本益比 < 15、近四季 EPS > 0、近 2 年營收年複合成長 > 15%、EPS 年成長 > 10%
            r0 = [x["rev"] for x in q[-4:]]
            r2 = [x["rev"] for x in q[-12:-8]] if len(q) >= 12 else []
            e1 = [x["eps"] for x in q[-8:-4]]
            if pe and pe < 15 and ttm > 0 and len(r2) == 4 and all(r0) and all(r2) and all(e is not None for e in e1) and sum(e1) > 0:
                cagr = ((sum(r0) / sum(r2)) ** 0.5 - 1) * 100
                if cagr > 15 and (ttm / sum(e1) - 1) * 100 > 10:
                    add("彼得林區（台股保留）")
            # s11 三率三升（毛利率、營益率、淨利率都比上季高）＋月線上揚＋週KD金叉
            a, b = q[-1], q[-2]
            if all(x.get(k) is not None for x in (a, b) for k in ("gp", "op", "ni", "rev")) and a["rev"] and b["rev"]:
                up3 = all(a[k] / a["rev"] > b[k] / b["rev"] for k in ("gp", "op", "ni"))
                if up3 and m20 > ma(c, 20, t_ - 3) and wk:
                    add("三率三升＋週KD金叉（台股保留）")


def watchlist(S, vam, Q, D):
    """美股穩健動能觀察名單（給每晚報告）：最新一天前 15 名＋財報健檢"""
    T = len(D) - 1
    out = []
    for t in sorted(vam.get(T, [])):
        o, h, l, c, v = S[t]
        q = [x for x in (Q.get(t) or []) if x["filed"] <= D[T]]
        _, B, _ = canslim(q) if q else (False, None, None)
        oc = [x["ocf"] for x in q[-4:]]
        ocf = sum(oc) if len(oc) == 4 and all(x is not None for x in oc) else None
        debt = q[-1]["liab"] / q[-1]["assets"] * 100 if q and q[-1]["liab"] is not None and q[-1]["assets"] else None
        m20, m60 = ma(c, 20, T), ma(c, 60, T)
        out.append({"t": t, "name": NAMES.get(t) or us.UNIVERSE.get(t) or t, "close": round(c[T], 2), "r6m": round((c[T] / c[T - 126] - 1) * 100, 1),
                    "ma20": round(m20, 2), "ma60": round(m60, 2), "bias": round((c[T] / m20 - 1) * 100, 1),
                    "ocf": ocf, "debt": round(debt, 0) if debt is not None else None, "health": B})
    return out


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
            p, dv = prices(t)
            if len(p) > 300:
                P[t] = (p, dv)
        except Exception:
            pass
        if t in cm:
            try:
                Q[t] = fundamentals(cm[t])
            except Exception:
                pass
            time.sleep(0.12)  # SEC 每秒最多 10 次
    bench = prices("VOO")[0]
    log("價格 %d 檔、財報 %d 檔" % (len(P), sum(1 for v in Q.values() if v)))
    # 共同日期
    D = [x[0] for x in bench]
    di = {d: i for i, d in enumerate(D)}
    N = len(D)
    start = max(260, next(i for i, d in enumerate(D) if d >= (dt.date.fromisoformat(D[-1]) - dt.timedelta(days=365 * YEARS)).isoformat()))
    S = {}
    RAW, DIV = {}, {}
    for t, (p, dv) in P.items():
        o, h, l, c, v, rc = [None] * N, [None] * N, [None] * N, [None] * N, [0] * N, [None] * N
        for d, a, b, x, y, z, r in p:
            if d in di:
                k = di[d]
                o[k], h[k], l[k], c[k], v[k], rc[k] = a, b, x, y, z, r
        for k in range(1, N):  # 補空值
            if c[k] is None and c[k - 1] is not None:
                o[k] = h[k] = l[k] = c[k] = c[k - 1]
                rc[k] = rc[k - 1]
        if c[start - 260] is None:
            continue
        S[t] = (o, h, l, c, v)
        RAW[t] = rc
        # 近一年配息合計（每天）
        dd = [(di.get(d), a) for d, a in dv]
        acc, ttm = [0.0] * N, [0.0] * N
        for k, a in dd:
            if k is not None:
                acc[k] += a
        run = 0.0
        for k in range(N):
            run += acc[k]
            if k >= 252:
                run -= acc[k - 252]
            ttm[k] = run
        DIV[t] = ttm
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
    vb = [x[4] for x in bench]
    sig = defaultdict(lambda: defaultdict(list))
    for t, (o, h, l, c, v) in S.items():
        IND = indicators(h, l, c)
        rc, dvt = RAW[t], DIV[t]
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
            fq = q_all[:qi]
            extra(sig, t, t_, o, h, l, c, v, IND, fq, rc[t_], dvt[t_], B)
            dip_signals(sig, t, t_, o, h, l, c, v, fq, B, vb)
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
        R, Y, RB = [], defaultdict(list), []
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
                    RB.append((vb[t_ + hold] / vb[t_ + 1] - 1) * 100)  # 同一段時間抱 VOO
                    last = t_ + hold
        return R, Y, RB
    v0 = vb[start]
    L = ["🇺🇸 美股策略回測（近 %d 年：%s～%s，%d 檔有價格、%d 檔有 SEC 財報；只有你看得到）" % (YEARS, D[start], D[-1], len(S), sum(1 for v in Q.values() if v)),
         "方法：訊號隔天開盤買、抱 20／60／120 個交易日收盤賣、扣 0.3%% 成本；同期 VOO（標普 500）買進抱著 %+.0f%%" % ((vb[-1] / v0 - 1) * 100), ""]
    rows = []
    for nm, s in sig.items():
        r20, y20, b20 = bt(s, 20)
        r60, _, b60 = bt(s, 60)
        r120, _, b120 = bt(s, 120)
        if not r20:
            L.append("・%s：這 5 年沒有訊號" % nm)
            continue
        f = lambda R, Bm: "%d 次、勝率 %.0f%%、平均 %+.1f%%、中位 %+.1f%%、最差 %+.0f%%（同期抱 VOO 平均 %+.1f%%）" % (
            len(R), sum(x > 0 for x in R) / len(R) * 100, st.mean(R), st.median(R), min(R), st.mean(Bm)) if R else "—"
        yrs = "、".join("%s %+.0f%%" % (y, st.mean(v)) for y, v in sorted(y20.items()))
        L.append("・%s\n　抱 20 天：%s\n　抱 60 天：%s\n　抱 120 天：%s\n　每年平均（抱 20 天）：%s" % (nm, f(r20, b20), f(r60, b60), f(r120, b120), yrs))
        rows.append({"name": nm, "n20": len(r20), "win20": sum(x > 0 for x in r20) / len(r20) * 100, "avg20": st.mean(r20),
                     "n60": len(r60), "win60": sum(x > 0 for x in r60) / len(r60) * 100 if r60 else None, "avg60": st.mean(r60) if r60 else None,
                     "n120": len(r120), "win120": sum(x > 0 for x in r120) / len(r120) * 100 if r120 else None, "avg120": st.mean(r120) if r120 else None,
                     "voo60": st.mean(b60) if b60 else None, "voo120": st.mean(b120) if b120 else None})
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
    json.dump({"asOf": D[-1], "list": watchlist(S, vam, Q, D)}, open("us_watch.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    json.dump({"asOf": D[-1], "rows": rows, "now": now}, open("us_bt.json", "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
