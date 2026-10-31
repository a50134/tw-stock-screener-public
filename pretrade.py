"""
pretrade.py - 買股前 5 年回測：這檔股票過去 5 年「買了抱著」和「照規則買賣」各賺多少、適不適合買

內容：
  1. 買進抱 5 年（含現金股利）：總報酬、年化報酬、最大跌幅、每年漲跌，和 0050 比
  2. 照規則買賣：
     - 季線順勢：收盤站上季線（60 日均線）隔天買、跌破隔天賣 → 看這檔適合長抱還是適合波段
     - 飆股前兆：長紅 K＋營收創 13 個月新高／投信連買 3 天以上（rocket.py 同一套規則與停損停利）
  3. 現在的位置：在 5 年高低區間的哪裡、離 5 年最高點多遠、近 5 年平均高點／低點
  4. 結論：適合長抱／適合波段／不適合，以及現在進場的時機
減資、分割（一天漲跌超過 11%，台股漲跌幅限制是 10%）會自動把之前的價格調整，避免算錯

用法：python pretrade.py 2492            # 在畫面印出結果（需要 FINMIND_TOKEN）
      lookup.py 查個股時會自動附上這一段
"""
import datetime as dt
import statistics as st

YEARS = 5


def adjust(rows, divs):
    """日K → (日期, 開, 高, 低, 收) 還原權值：除息、減資／分割都往前調整，讓報酬算得對"""
    rows = [r for r in rows if r.get("close")]
    if not rows:
        return []
    ex = {}
    for d in divs or []:
        cash = (d.get("CashEarningsDistribution") or 0) + (d.get("CashStatutorySurplus") or 0)
        stock = (d.get("StockEarningsDistribution") or 0) + (d.get("StockStatutorySurplus") or 0)
        if cash > 0 and d.get("CashExDividendTradingDate"):
            ex.setdefault(d["CashExDividendTradingDate"], [0, 0])[0] += cash
        if stock > 0 and d.get("StockExDividendTradingDate"):
            ex.setdefault(d["StockExDividendTradingDate"], [0, 0])[1] += stock
    f = [1.0] * len(rows)
    k = 1.0
    for i in range(len(rows) - 1, 0, -1):
        f[i] = k
        prev, cur = rows[i - 1]["close"], rows[i]
        x = ex.get(cur["date"])
        if x:  # 除息：前一天價格 × (1 − 股息 ÷ 前收)；除權：÷ (1 + 配股 ÷ 10)
            k *= (1 - x[0] / prev) / (1 + x[1] / 10)
        else:
            r = cur["open"] / prev if cur.get("open") else cur["close"] / prev
            if r > 1.11 or r < 0.89:  # 超過漲跌幅限制＝減資或分割，用開盤跳空調整
                k *= r
    f[0] = k
    return [(r["date"], r["open"] * f[i], r["max"] * f[i], r["min"] * f[i], r["close"] * f[i]) for i, r in enumerate(rows)]


def max_dd(cs):
    pk, dd, at = cs[0], 0, None
    for i, c in enumerate(cs):
        pk = max(pk, c)
        if c / pk - 1 < dd:
            dd, at = c / pk - 1, i
    return dd * 100, at


def cagr(a, b, days):
    return ((b / a) ** (365.25 / days) - 1) * 100 if a > 0 and days > 0 else 0


def trend_trades(P, n=60):
    """收盤站上季線隔天開盤買、跌破隔天開盤賣"""
    c = [x[4] for x in P]
    tr, e, ei = [], None, None
    eq = 1.0
    for i in range(n, len(P) - 1):
        m = sum(c[i - n + 1:i + 1]) / n
        if e is None and c[i] > m:
            e, ei = P[i + 1][1], i + 1
        elif e is not None and c[i] < m:
            x = P[i + 1][1]
            tr.append((P[ei][0], P[i + 1][0], (x / e - 1) * 100 - 0.6))
            eq *= x / e * 0.994
            e = None
    if e is not None:
        tr.append((P[ei][0], "抱著中", (c[-1] / e - 1) * 100))
        eq *= c[-1] / e
    return tr, (eq - 1) * 100


def rocket_trades(P, rev, inst):
    """飆股前兆（長紅 K＋營收創 13 個月新高／投信連買 3 天）＋ rocket.py 的買賣規則"""
    rv = {}
    for d in rev or []:
        rv["%04d-%02d" % (d["revenue_year"], d["revenue_month"])] = d["revenue"]
    it = {}
    for d in inst or []:
        if d.get("name") == "Investment_Trust":
            it[d["date"]] = it.get(d["date"], 0) + d["buy"] - d["sell"]
    c = [x[4] for x in P]
    tr, i, n = [], 61, len(P)
    while i < n - 2:
        d, o, h, l, cl = P[i]
        if not (c[i] / c[i - 1] > 1.05 and (h - cl) <= 0.25 * (h - l + 1e-9)):
            i += 1
            continue
        # 營收：只用當時已公布的（每月 10 日前公布上個月）
        ym = d[:7]
        ks = [k for k in sorted(rv) if k < ym]
        if int(d[8:10]) <= 10 and ks:
            ks = ks[:-1]
        rh = len(ks) >= 13 and rv[ks[-1]] > 0 and rv[ks[-1]] >= max(rv[k] for k in ks[-13:-1])
        k = 0
        while i - k >= 0 and it.get(P[i - k][0], 0) > 0:
            k += 1
        if not (rh or k >= 3):
            i += 1
            continue
        if P[i + 1][1] > cl * 1.03:  # 跳空太多不追
            i += 1
            continue
        e, stop, pk = P[i + 1][1], cl * 0.88, P[i + 1][1]
        j = i + 1
        out = None
        while j < min(i + 41, n - 1):
            pk = max(pk, c[j])
            if c[j] < stop or (pk > e * 1.15 and c[j] < pk * 0.88):
                out = (P[j + 1][0], P[j + 1][1])
                break
            j += 1
        if out is None:
            j = min(i + 40, n - 1)
            out = (P[j][0] if j < n - 1 else "抱著中", c[j])
        tr.append((d, out[0], (out[1] / e - 1) * 100 - 0.6))
        i = j + 1
    return tr


def yearly(P):
    """[(年, 漲跌%, 註記)]：第一年從起始日算、最後一年算到今天"""
    out, prev = [], None
    yl = sorted({x[0][:4] for x in P})
    for y in yl:
        ys = [x for x in P if x[0][:4] == y]
        a = prev if prev else ys[0][1]
        note = "（到今天）" if y == yl[-1] else "（%s 月起）" % ys[0][0][5:7].lstrip("0") if not prev and ys[0][0][5:7] != "01" else ""
        out.append((y, (ys[-1][4] / a - 1) * 100, note))
        prev = ys[-1][4]
    return out


def analyze(sid, name, rows, divs, rev, inst, bench_rows, bench_divs):
    P = adjust(rows, divs)
    if len(P) < 250:
        return "・5 年回測：上市不到 1 年，資料不夠，沒辦法回測"
    B = adjust(bench_rows, bench_divs) if bench_rows else []
    start = (dt.date.fromisoformat(P[-1][0]) - dt.timedelta(days=int(365.25 * YEARS))).isoformat()
    W = [x for x in P if x[0] >= start]
    yrs = (dt.date.fromisoformat(W[-1][0]) - dt.date.fromisoformat(W[0][0])).days
    tot = (W[-1][4] / W[0][4] - 1) * 100
    cg = cagr(W[0][4], W[-1][4], yrs)
    dd, at = max_dd([x[4] for x in W])
    rets = [W[i][4] / W[i - 1][4] - 1 for i in range(1, len(W))]
    vol = st.pstdev(rets) * (245 ** 0.5) * 100
    L = ["・%d 年回測（%s～%s，含股利、已調整減資分割）：" % (round(yrs / 365.25), W[0][0], W[-1][0])]
    bt = ""
    bcg = None
    if B:
        BW = [x for x in B if x[0] >= W[0][0]]
        if len(BW) > 200:
            bcg = cagr(BW[0][4], BW[-1][4], yrs)
            bdd, _ = max_dd([x[4] for x in BW])
            bt = "；同期 0050 年化 %+.1f%%、最大跌幅 %.0f%%" % (bcg, bdd)
    L.append("　1. 買了一直抱著：總報酬 %+.0f%%（年化 %+.1f%%），中間最慘跌 %.0f%%（%s）%s" % (tot, cg, dd, W[at][0][:7] if at else "—", bt))
    L.append("　　每年：" + "、".join("%s %+.0f%%%s" % (y, r, note) for y, r, note in yearly(W)))
    tt, teq = trend_trades(W)
    if tt:
        win = sum(x[2] > 0 for x in tt) / len(tt) * 100
        L.append("　2. 季線順勢（站上季線買、跌破賣）：%d 次、勝率 %.0f%%、累計 %+.0f%%（一直抱著 %+.0f%%）" % (len(tt), win, teq, tot))
    rt = rocket_trades(W, rev, inst)
    if rt:
        r = [x[2] for x in rt]
        L.append("　3. 飆股前兆規則：%d 次、勝率 %.0f%%、平均每次 %+.1f%%（最近：%s）" % (
            len(r), sum(x > 0 for x in r) / len(r) * 100, st.mean(r),
            "、".join("%s %+.0f%%" % (a[2:].replace("-", "/"), x) for a, _, x in rt[-3:])))
    else:
        L.append("　3. 飆股前兆規則：5 年內沒出現過")
    # 現在位置
    c = W[-1][4]
    hi, lo = max(x[2] for x in W), min(x[3] for x in W)
    pos = (c - lo) / (hi - lo) * 100 if hi > lo else 50
    ys = {}
    for x in W:
        y = x[0][:4]
        a = ys.setdefault(y, [x[2], x[3]])
        a[0], a[1] = max(a[0], x[2]), min(a[1], x[3])
    full = [v for y, v in ys.items() if y != W[-1][0][:4]]
    ahi = st.mean(v[0] for v in full) if full else hi
    alo = st.mean(v[1] for v in full) if full else lo
    m60 = sum(x[4] for x in W[-60:]) / 60
    m240 = sum(x[4] for x in W[-240:]) / 240
    raw = rows[-1]["close"]  # 用實際股價說明（上面的計算是還原權值）
    k = raw / c
    L.append("　4. 現在位置：在 5 年高低區間的 %.0f%%，離 5 年最高點 %+.0f%%；近幾年平均每年高點約 %.1f、低點約 %.1f（實際股價）；%s季線、%s年線" % (
        pos, (c / hi - 1) * 100, ahi * k, alo * k, "站上" if c > m60 else "跌破", "站上" if c > m240 else "跌破"))
    # 結論
    good = []
    if bcg is not None:
        lt = "適合長抱" if cg > bcg and dd > -55 else "長抱報酬不如 0050" if cg <= bcg else "長抱賺得多但跌起來很兇"
    else:
        lt = "適合長抱" if cg > 8 and dd > -55 else "長抱報酬普通"
    good.append(lt)
    if tt and teq > tot + 10:
        good.append("用季線波段操作比一直抱著好")
    elif tt and teq < tot - 10:
        good.append("一直抱著比進進出出好")
    if pos > 85:
        tm = "現在在 5 年高檔，追高風險大，最好等拉回或分批"
    elif pos < 25:
        tm = "現在在 5 年低檔，%s" % ("但還在年線下方，等站回季線再進比較安全" if c < m240 and c < m60 else "位置便宜，可以分批買")
    else:
        tm = "現在在中間位置，%s" % ("趨勢向上（站上季線）" if c > m60 else "趨勢偏弱（跌破季線），等站回季線再買")
    L.append("　➜ 結論：%s；%s。年波動 %.0f%%（0050 約 20%%，越大代表漲跌越劇烈）" % ("，".join(good), tm, vol))
    return "\n".join(L)


def run(sid, name, get):
    """get＝fetch_finmind.get；抓 5 年多的資料並回測"""
    s0 = (dt.date.today() - dt.timedelta(days=int(365.25 * YEARS) + 120)).isoformat()
    rows = get("TaiwanStockPrice", sid, s0)
    divs = get("TaiwanStockDividend", sid, (dt.date.today() - dt.timedelta(days=365 * 7)).isoformat())
    rev = get("TaiwanStockMonthRevenue", sid, (dt.date.today() - dt.timedelta(days=365 * 7)).isoformat())
    inst = get("TaiwanStockInstitutionalInvestorsBuySell", sid, s0)
    if sid != "0050" and "0050" not in _BENCH:  # 0050 只抓一次
        _BENCH["0050"] = (get("TaiwanStockPrice", "0050", s0), get("TaiwanStockDividend", "0050", (dt.date.today() - dt.timedelta(days=365 * 7)).isoformat()))
    br, bd = _BENCH.get("0050", ([], [])) if sid != "0050" else ([], [])
    return analyze(sid, name, rows, divs, rev, inst, br, bd)


_BENCH = {}


if __name__ == "__main__":
    import os
    import sys
    import fetch_finmind
    fetch_finmind.load_env()
    fetch_finmind.TOKEN = (os.environ.get("FINMIND_TOKEN") or "").strip()
    for a in sys.argv[1:]:
        print(run(a, a, fetch_finmind.get))
