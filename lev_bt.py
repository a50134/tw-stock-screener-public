"""
lev_bt.py - 0050 正2（00631L）什麼時候買的回測（2026-11-11 使用者問的）

資料：Yahoo Finance 還原股價（0050.TW、00631L.TW；GitHub Actions 上跑）。
正2 在 2014-10 才上市，更早的年份（含 2008、2011）用「0050 每天漲跌 × 2，再扣每年約 1% 費用」模擬，
並先跟真的正2 在重疊期間對照，確認模擬值可不可信。

比較的買法（大跌事件＝0050 5 日跌 6% 以上，同 crash.py）：
  甲. 大跌隔天就買（接刀）
  乙. 等反彈後回跌 6% 以上、而且收盤沒破這波低點才買（等回跌）；先破低就不買
  丙. 等 0050 站回月線和季線、月線往上才買（等轉強）
  丁. 乙或丙哪個先到就買
每種買法看正2 抱 20／60／120 天的勝率、平均、最差，持有期間最多賠多少，以及同樣時間點買 0050 的結果。
另外看長期規則：一直抱正2、只在 0050 站上季線／年線時抱正2（其餘時間空手）、一直抱 0050。

2026-11-11 加：0050 反1（00632R，每天漲跌是 0050 的 −1 倍）什麼時候可以抱。
2014-10 以前同樣用模擬（−1 倍、每年扣 1%），系統性衰退警訊同 crash.regime（美股跌破 200 日線＋美債殖利率近一年倒掛）。

用法：python lev_bt.py
"""
import datetime as dt
import sys

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
HOLDS = (20, 60, 120)
COST = 0.003
WAIT = 40  # 大跌後最多等幾個交易日


def yahoo(sym):
    for host in ("query1", "query2"):
        try:
            r = requests.get("https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=1104537600&period2=%d&interval=1d&includeAdjustedClose=true"
                             % (host, sym, int(dt.datetime.now().timestamp())), headers=UA, timeout=40)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            adj = res["indicators"]["adjclose"][0]["adjclose"]
            return {dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d"): adj[i]
                    for i, ts in enumerate(res.get("timestamp") or []) if adj[i]}
        except Exception as e:
            print("  ! %s 抓取失敗（%s）：%s" % (sym, host, e), file=sys.stderr)
    return {}


def clean(D, c):
    """把價格接成連續的：單日漲跌超過 25%（正2 一天最多 ±20%）視為分割或壞資料，那天當作沒漲跌，之後照每天漲跌幅接下去"""
    out, bad = [c[0]], []
    for i in range(1, len(c)):
        r = c[i] / c[i - 1] - 1
        if abs(r) > 0.25:
            bad.append("%s %+.0f%%" % (D[i], r * 100))
            r = 0
        out.append(out[-1] * (1 + r))
    if bad:
        print("  （資料斷層 %d 處，已接起來：%s）" % (len(bad), "、".join(bad[:8])))
    return out


def ma(c, n, t):
    return sum(c[t - n + 1:t + 1]) / n if t >= n - 1 else None


def stat(L):
    if not L:
        return "0 筆"
    v = sorted(L)
    return "%2d 筆｜勝率 %3.0f%%｜平均 %+6.1f%%｜中位數 %+6.1f%%｜最差 %+4.0f%%" % (
        len(v), 100 * sum(x > 0 for x in v) / len(v), 100 * sum(v) / len(v), 100 * v[len(v) // 2], 100 * v[0])


def curve_stats(eq, D):
    yrs = (dt.date.fromisoformat(D[-1]) - dt.date.fromisoformat(D[0])).days / 365.25
    pk, mdd = eq[0], 0
    for x in eq:
        pk = max(pk, x)
        mdd = min(mdd, x / pk - 1)
    return "年化 %+5.1f%%｜最大跌幅 %4.0f%%｜1 元變 %.1f 元" % (100 * ((eq[-1] / eq[0]) ** (1 / yrs) - 1), 100 * mdd, eq[-1] / eq[0])


def main():
    a, b, rv = yahoo("0050.TW"), yahoo("00631L.TW"), yahoo("00632R.TW")
    if not a:
        print("0050 抓不到")
        return
    D = sorted(a)
    m = clean(D, [a[d] for d in D])
    # 模擬正2：每天 2 倍、每年扣 1%
    sim = [100.0]
    for i in range(1, len(D)):
        sim.append(sim[-1] * (1 + 2 * (m[i] / m[i - 1] - 1) - 0.01 / 250))
    real_d = [d for d in D if d in b]
    L2 = list(sim)
    if real_d:
        i0 = D.index(real_d[0])
        rc = clean(real_d, [b[d] for d in real_d])
        rmap = dict(zip(real_d, rc))
        k = sim[i0] / rc[0]
        prev = sim[i0]
        for i in range(i0, len(D)):
            prev = rmap[D[i]] * k if D[i] in rmap else prev
            L2[i] = prev
        yrs = (dt.date.fromisoformat(D[-1]) - dt.date.fromisoformat(D[i0])).days / 365.25
        print("0050 資料 %s～%s（%d 天）；真的正2 從 %s 開始" % (D[0], D[-1], len(D), real_d[0]))
        print("模擬對照（%s 之後）：真的正2 年化 %+.1f%%、模擬 %+.1f%% → 更早的年份用模擬值" % (
            real_d[0], 100 * ((rc[-1] / rc[0]) ** (1 / yrs) - 1), 100 * ((sim[-1] / sim[i0]) ** (1 / yrs) - 1)))
    n = len(D)

    # ---- 大跌事件 ----
    ev, last = [], -99
    for t in range(5, n):
        r = m[t] / m[t - 5] - 1
        if -0.4 < r <= -0.06:
            if t - last > 5:
                ev.append(t)
            last = t
    ev = [t for t in ev if t >= 70]
    print("\n大跌事件（0050 5 日跌 6%% 以上）共 %d 次：%s" % (len(ev), "、".join(D[t] for t in ev)))

    def entry_b(t0):
        """乙：反彈後從高點回跌 6% 以上且沒破低 → 買進日；先破低回傳 None"""
        lo, pk, bounced = m[t0], m[t0], False
        for t in range(t0 + 1, min(t0 + WAIT, n - 1)):
            if not bounced:
                if m[t] < lo:
                    lo = m[t]
                    pk = m[t]
                pk = max(pk, m[t])
                if pk / lo - 1 >= 0.06:
                    bounced = True
                continue
            if m[t] < lo:
                return None
            pk = max(pk, m[t])
            if m[t] / pk - 1 <= -0.06:
                return t
        return None

    def entry_c(t0):
        for t in range(t0 + 1, min(t0 + WAIT, n - 1)):
            m20, m20p, m60 = ma(m, 20, t), ma(m, 20, t - 5), ma(m, 60, t)
            if m[t] > m20 and m[t] > m60 and m20 > m20p:
                return t
        return None

    def entry_d(t0):
        x = [e for e in (entry_b(t0), entry_c(t0)) if e]
        return min(x) if x else None

    rules = (("甲. 大跌隔天就買", lambda t0: t0), ("乙. 等回跌 6% 且沒破低", entry_b), ("丙. 等站回月線季線", entry_c), ("丁. 乙或丙先到", entry_d))
    print("\n【大跌後買正2】（訊號隔天收盤買，扣 0.3% 成本）")
    detail = {}
    for name, f in rules:
        E = [(t0, f(t0)) for t0 in ev]
        got = [(t0, e) for t0, e in E if e is not None and e + 1 < n]
        print("\n%s：%d 次大跌裡買到 %d 次，平均等 %.0f 天" % (name, len(ev), len(got), sum(e - t0 for t0, e in got) / max(1, len(got))))
        for H in HOLDS:
            r2 = [L2[e + 1 + H] / L2[e + 1] - 1 - COST for _, e in got if e + 1 + H < n]
            r1 = [m[e + 1 + H] / m[e + 1] - 1 - COST for _, e in got if e + 1 + H < n]
            dd = [min(L2[e + 1:e + 2 + H]) / L2[e + 1] - 1 for _, e in got if e + 1 + H < n]
            print("  抱 %3d 天｜正2：%s｜期間最多賠 平均 %+.0f%%、最慘 %+.0f%%" % (H, stat(r2), 100 * sum(dd) / max(1, len(dd)), 100 * min(dd or [0])))
            print("          ｜0050：%s" % stat(r1))
        detail[name] = dict(E)
    print("\n【每次大跌的明細】正2 抱 60 天報酬（— 表示沒買到或還沒滿 60 天）")
    print("大跌日       甲隔天買   乙等回跌   丙等轉強   之後 60 天 0050 最多再跌")
    for t0 in ev:
        row = []
        for name, _ in rules[:3]:
            e = detail[name][t0]
            row.append("%+5.0f%%" % (100 * (L2[e + 61] / L2[e + 1] - 1)) if e is not None and e + 61 < n else "   —  ")
        more = "%+.0f%%" % (100 * (min(m[t0 + 1:t0 + 62]) / m[t0] - 1)) if t0 + 2 < n else "—"
        print("%s   %s     %s     %s     %s" % (D[t0], row[0], row[1], row[2], more))

    # ---- 長期規則 ----
    print("\n【長期抱法比較】（%s 起，換手一次扣 0.3%%）" % D[250])
    s0 = 250

    def run(cond):
        eq, held = [1.0], False
        for t in range(s0 + 1, n):
            x = eq[-1] * (L2[t] / L2[t - 1] if held else 1)
            want = cond(t)
            if want != held:
                x *= 1 - COST
                held = want
            eq.append(x)
        return eq

    DD = D[s0:]
    print("  一直抱 0050：%s" % curve_stats([m[t] / m[s0] for t in range(s0, n)], DD))
    print("  一直抱正2：%s" % curve_stats([L2[t] / L2[s0] for t in range(s0, n)], DD))
    print("  0050 在季線（60 日）上才抱正2：%s" % curve_stats(run(lambda t: m[t] > ma(m, 60, t)), DD))
    print("  0050 在年線（240 日）上才抱正2：%s" % curve_stats(run(lambda t: m[t] > ma(m, 240, t)), DD))
    print("  0050 在月線和季線上才抱正2：%s" % curve_stats(run(lambda t: m[t] > ma(m, 20, t) and m[t] > ma(m, 60, t)), DD))
    inverse(D, m, rv, L2, n, s0, run_any=lambda cond, S: run_series(S, cond, s0, n), DD=DD)
    simulate(D, m, L2, n, s0, DD)
    t = n - 1
    print("\n現在（%s）：0050 月線 %s、季線 %s、年線 %s" % (D[t], "上" if m[t] > ma(m, 20, t) else "下", "上" if m[t] > ma(m, 60, t) else "下", "上" if m[t] > ma(m, 240, t) else "下"))


def simulate(D, m, L2, n, s0, DD):
    """2026-11-13 使用者要的：照我們現在的規則「模擬買」0050 和正2，跟一直抱比
    正2 規則（crash.lev_line）：衰退警訊沒亮、0050 在年線上才買；分 3 筆——條件成立那天買第 1 筆，
    之後 0050 單日跌 2% 以上、或距上一筆滿 10 個交易日就買下一筆；0050 收盤跌破年線或警訊亮就全部賣掉，條件再成立重新開始。
    0050 規則：同樣分 3 筆、同樣進出（看 0050 用同一套規則會怎樣）；另外看「0050 一直抱、只在大跌（5 日跌 6%）時加碼」"""
    reg = regime_series(D) or {}
    y = lambda t: ma(m, 240, t)
    print("\n" + "=" * 60 + "\n【模擬照規則買 0050／正2】（%s 起，每筆交易扣 0.3%%；沒買的錢放著不生利息）" % D[s0])
    print("衰退警訊資料：%s" % ("有" if reg else "抓不到，只用年線"))

    def run(S, label):
        cash, units, lots, last, trades, days_in = 1.0, 0.0, 0, -99, 0, 0
        eq = []
        for t in range(s0, n):
            ok = m[t] >= y(t) and not reg.get(D[t], False)
            if units and not ok:  # 出場
                cash += units * S[t] * (1 - COST)
                units, lots = 0.0, 0
                trades += 1
            elif ok and lots < 3:
                drop = m[t] / m[t - 1] - 1 <= -0.02
                if lots == 0 or drop or t - last >= 10:
                    amt = cash / (3 - lots)  # 剩下的錢平均分給還沒買的筆數
                    units += amt * (1 - COST) / S[t]
                    cash -= amt
                    lots += 1
                    last = t
                    trades += 1
            days_in += 1 if units else 0
            eq.append(cash + units * S[t])
        print("  %s：%s｜交易 %d 次｜有持股的天數 %.0f%%" % (label, curve_stats(eq, DD), trades, 100 * days_in / (n - s0)))
        return eq
    print("  一直抱 0050：%s" % curve_stats([m[t] / m[s0] for t in range(s0, n)], DD))
    print("  一直抱正2：%s" % curve_stats([L2[t] / L2[s0] for t in range(s0, n)], DD))
    run(L2, "照規則買正2（分 3 筆、跌破年線出場）")
    run(m, "照規則買 0050（同樣規則）")
    # 0050 一直抱，大跌時加碼：先放 50%，每次大跌（5 日跌 6%）加碼剩下現金的一半
    cash, units = 0.5, 0.5 / m[s0]
    eq, last = [], -99
    for t in range(s0, n):
        if t >= 5 and m[t] / m[t - 5] - 1 <= -0.06 and t - last > 5 and cash > 0.01:
            amt = cash / 2
            units += amt * (1 - COST) / m[t]
            cash -= amt
            last = t
        eq.append(cash + units * m[t])
    print("  0050 先買一半、每次大跌加碼剩下的一半：%s" % curve_stats(eq, DD))
    # 年度報酬
    print("\n  每年報酬：年份｜0050 一直抱｜正2 一直抱｜照規則買正2")
    rule = []
    cash, units, lots, last = 1.0, 0.0, 0, -99
    for t in range(s0, n):
        ok = m[t] >= y(t) and not reg.get(D[t], False)
        if units and not ok:
            cash += units * L2[t] * (1 - COST)
            units, lots = 0.0, 0
        elif ok and lots < 3 and (lots == 0 or m[t] / m[t - 1] - 1 <= -0.02 or t - last >= 10):
            amt = cash / (3 - lots)
            units += amt * (1 - COST) / L2[t]
            cash -= amt
            lots += 1
            last = t
        rule.append(cash + units * L2[t])
    yrs = sorted({d[:4] for d in DD})
    for yy in yrs:
        ix = [k for k, d in enumerate(DD) if d[:4] == yy]
        a_, b_ = ix[0], ix[-1]
        f = lambda S: (S[b_] / S[a_ - 1 if a_ else a_] - 1) * 100
        print("  %s｜%+6.1f%%｜%+6.1f%%｜%+6.1f%%" % (yy, f([m[t] for t in range(s0, n)]), f([L2[t] for t in range(s0, n)]), f(rule)))


def run_series(S, cond, s0, n):
    """cond(t) 為真時抱 S（當天收盤決定，隔天起算報酬），否則空手；換手扣成本"""
    eq, held = [1.0], False
    for t in range(s0 + 1, n):
        x = eq[-1] * (S[t] / S[t - 1] if held else 1)
        want = cond(t)
        if want != held:
            x *= 1 - COST
            held = want
        eq.append(x)
    return eq


def regime_series(D):
    """每天的系統性衰退警訊（美股跌破 200 日線＋近一年 10 年減 3 個月殖利率曾倒掛）"""
    spx, tnx, irx = yahoo("%5EGSPC"), yahoo("%5ETNX"), yahoo("%5EIRX")
    if not spx or not tnx or not irx:
        return None
    sd = sorted(spx)
    sc = [spx[d] for d in sd]
    cd = [d for d in sorted(tnx) if d in irx]
    cv = [tnx[d] - irx[d] for d in cd]
    out, i, j = {}, 0, 0
    for d in D:
        while i + 1 < len(sd) and sd[i + 1] < d:  # 美股用前一個交易日（台股收盤時美股還沒開）
            i += 1
        while j + 1 < len(cd) and cd[j + 1] < d:
            j += 1
        if i < 200 or j < 250 or sd[i] >= d:
            out[d] = False
            continue
        below = sc[i] < sum(sc[i - 199:i + 1]) / 200
        out[d] = below and min(cv[j - 250:j + 1]) < 0
    return out


def inverse(D, m, rv, L2, n, s0, run_any, DD):
    print("\n" + "=" * 60 + "\n【0050 反1（00632R）】")
    inv = [100.0]
    for i in range(1, n):
        inv.append(inv[-1] * (1 - (m[i] / m[i - 1] - 1) - 0.01 / 250))
    real_d = [d for d in D if d in rv]
    R = list(inv)
    if real_d:
        i0 = D.index(real_d[0])
        rc = clean(real_d, [rv[d] for d in real_d])
        rmap = dict(zip(real_d, rc))
        k, prev = inv[i0] / rc[0], inv[i0]
        for i in range(i0, n):
            prev = rmap[D[i]] * k if D[i] in rmap else prev
            R[i] = prev
        yrs = (dt.date.fromisoformat(D[-1]) - dt.date.fromisoformat(D[i0])).days / 365.25
        print("模擬對照（%s 之後）：真的反1 年化 %+.1f%%、模擬 %+.1f%%" % (
            real_d[0], 100 * ((rc[-1] / rc[0]) ** (1 / yrs) - 1), 100 * ((inv[-1] / inv[i0]) ** (1 / yrs) - 1)))
    reg = regime_series(D)
    print("系統性衰退警訊：%s" % ("抓不到美股資料，略過" if reg is None else "亮燈 %d 天（%s）" % (
        sum(reg.values()), "、".join(sorted({d[:4] for d, v in reg.items() if v})) or "無")))
    y = lambda t: ma(m, 240, t)
    q = lambda t: ma(m, 60, t)
    mo = lambda t: ma(m, 20, t)
    rules = [
        ("一直抱反1", lambda t: True),
        ("0050 在年線下才抱反1", lambda t: m[t] < y(t)),
        ("0050 在季線下才抱反1", lambda t: m[t] < q(t)),
        ("0050 在年線下、而且月線季線都往下才抱反1", lambda t: m[t] < y(t) and mo(t) < ma(m, 20, t - 5) and q(t) < ma(m, 60, t - 5)),
        ("年線下＋跌破季線才抱反1", lambda t: m[t] < y(t) and m[t] < q(t)),
    ]
    if reg:
        rules.append(("系統性衰退警訊亮才抱反1", lambda t: reg[D[t]]))
        rules.append(("警訊亮＋0050 在季線下才抱反1", lambda t: reg[D[t]] and m[t] < q(t)))
    print("\n【只抱反1，其餘時間空手】（%s 起）" % D[s0])
    for name, f in rules:
        eq = run_any(f, R)
        days = sum(1 for t in range(s0, n) if f(t))
        print("  %s：%s｜抱的天數 %.0f%%" % (name, curve_stats(eq, DD), 100 * days / (n - s0)))
    print("\n【正2＋反1 輪流】（年線上抱正2、年線下抱反1）")
    eq, held = [1.0], None
    for t in range(s0 + 1, n):
        S = L2 if held == "L" else R if held == "R" else None
        x = eq[-1] * (S[t] / S[t - 1] if S else 1)
        want = "L" if m[t] > y(t) else "R"
        if want != held:
            x *= 1 - COST
            held = want
        eq.append(x)
    print("  年線上正2、年線下反1：%s" % curve_stats(eq, DD))
    print("  （對照）年線上正2、年線下空手：%s" % curve_stats(run_any(lambda t: m[t] > y(t), L2), DD))

    # 事件：0050 收盤跌破年線（之前 20 天都在年線上）→ 買反1
    print("\n【0050 第一次跌破年線就買反1】（之前 20 天都在年線上；隔天收盤買）")
    ev = [t for t in range(s0 + 20, n - 1) if m[t] < y(t) and all(m[u] > y(u) for u in range(t - 20, t))]
    for H in HOLDS:
        r = [R[t + 1 + H] / R[t + 1] - 1 - COST for t in ev if t + 1 + H < n]
        print("  抱 %3d 天：%s" % (H, stat(r)))
    print("  明細（抱 60 天）：" + "、".join("%s %s" % (D[t], "%+.0f%%" % (100 * (R[t + 61] / R[t + 1] - 1)) if t + 61 < n else "—") for t in ev))
    # 事件：大跌後第一波反彈 13% 以上 → 買反1（賭回跌）
    print("\n【大跌後反彈 13% 以上就買反1】（賭第一波反彈後會回跌；大跌＝0050 5 日跌 6%，40 天內反彈 13%）")
    evs, last = [], -99
    for t in range(5, n):
        if -0.4 < m[t] / m[t - 5] - 1 <= -0.06:
            if t - last > 5:
                evs.append(t)
            last = t
    got = []
    for t0 in evs:
        lo = min(m[t0:t0 + 6]) if t0 + 6 < n else m[t0]
        for t in range(t0 + 1, min(t0 + 40, n - 1)):
            lo = min(lo, m[t])
            if m[t] / lo - 1 >= 0.13:
                got.append(t)
                break
    for H in (10, 20, 60):
        r = [R[t + 1 + H] / R[t + 1] - 1 - COST for t in got if t + 1 + H < n]
        print("  抱 %3d 天：%s" % (H, stat(r)))
    print("  明細（抱 20 天）：" + "、".join("%s %s" % (D[t], "%+.0f%%" % (100 * (R[t + 21] / R[t + 1] - 1)) if t + 21 < n else "—") for t in got))
    t = n - 1
    print("\n現在（%s）：0050 %s 年線、%s 季線；系統性衰退警訊 %s" % (D[t], "在" if m[t] > y(t) else "跌破", "在" if m[t] > q(t) else "跌破",
                                                       "—" if reg is None else ("亮" if reg[D[t]] else "沒亮")))


if __name__ == "__main__":
    main()
