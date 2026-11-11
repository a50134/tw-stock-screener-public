"""
tape_bt.py - 回測 2026-11-10「錢線百分百」提到的 4 個抄底想法（用每晚的 data.json，約 400 個交易日）

A. 避開高融資股：融資餘額佔股本比例高的股票，大跌後反彈是不是比較差
   （資料沒有融資限額，用「融資餘額 ÷ 股本」代替；融資限額通常是股本的 25%，所以佔股本 20% ≈ 使用率 80%）
B. 融資減肥排名：大跌期間融資減最多的股票，之後是不是漲比較多
C. 負乖離＋低檔爆量：離季線跌很深、當天爆量收紅
D. 回到年線＋投信買：好股票第一次回到年線，投信近 5 天買超

買進：訊號隔天開盤；抱 20／60 個交易日；扣 0.6% 交易成本；同一檔 10 天內重複訊號只算一次
用法：python tape_bt.py data.json          # 用每晚資料回測 A～D
      python tape_bt.py data.json --long   # C、D 用 Yahoo 2010 年起的還原股價再驗證（只有價量，沒有法人與財報；GitHub Actions 上跑）
"""
import json
import os
import sys

import crash
import fin_health

DIR = os.path.dirname(os.path.abspath(__file__))
HOLDS = (20, 60)
COST = 0.006


def ma(c, n, t):
    w = c[t - n + 1:t + 1]
    return sum(w) / n if t >= n - 1 and all(w) else None


def fwd(s, t, H):
    c, o = s["c"], s["o"]
    e = t + 1 + H
    if e >= len(c) or not c[e] or not (o[t + 1] or c[t]):
        return None
    return c[e] / (o[t + 1] or c[t]) - 1 - COST


def stat(L):
    if not L:
        return "0 筆"
    v = sorted(L)
    return "%4d 筆｜勝率 %3.0f%%｜平均 %+6.1f%%｜中位數 %+6.1f%%｜最差 %+4.0f%%" % (
        len(v), 100 * sum(x > 0 for x in v) / len(v), 100 * sum(v) / len(v), 100 * v[len(v) // 2], 100 * v[0])


def show(title, sigs, S):
    """sigs: [(股票, 第幾天)]；同一檔 10 天內只算一次"""
    seen, keep = {}, []
    for s, t in sorted(sigs, key=lambda x: x[1]):
        if t - seen.get(s["id"], -99) > 10:
            keep.append((s, t))
            seen[s["id"]] = t
    for H in HOLDS:
        print("  %s｜抱 %d 天：%s" % (title, H, stat([r for s, t in keep for r in [fwd(s, t, H)] if r is not None])))
    return keep


def liquid(s, t):
    return not s["id"].startswith("00") and s["c"][t] and t >= 25 and all(s["v"][t - 20:t]) and sum(s["v"][t - 20:t]) / 20 >= 500


def good(s, day):
    return crash.grows(s, day) and fin_health.check(s, day)[0] is True


def mratio(s, t):
    """融資餘額佔股本（%）；shares 單位是千股＝張"""
    mg = s.get("mg") or []
    if len(mg) <= t or not mg[t] or not s.get("shares"):
        return None
    return 100.0 * mg[t] / float(s["shares"])


def main():
    path = next((a for a in sys.argv[1:] if not a.startswith("--")), os.path.join(DIR, "data.json"))
    data = json.load(open(path, encoding="utf-8"))
    D, S = data["dates"], data["stocks"]
    n = len(D)
    m = next(x["c"] for x in S if x["id"] == "0050")
    ev = crash.events(D, m)
    print("資料 %s～%s，%d 天、%d 檔；大跌事件 %d 次：%s" % (D[0], D[-1], n, len(S), len(ev), "、".join(D[t] for t in ev)))

    print("\n【對照組】隨便買（均量 500 張以上的個股，每 5 天買一次）")
    base = [(s, t) for s in S for t in range(70, n, 5) if liquid(s, t)]
    for H in HOLDS:
        print("  全期間｜抱 %d 天：%s" % (H, stat([r for s, t in base for r in [fwd(s, t, H)] if r is not None])))
    base2 = [(s, t) for s, t in base if t >= 245]
    for H in HOLDS:
        print("  有年線的期間（%s 之後）｜抱 %d 天：%s" % (D[245], H, stat([r for s, t in base2 for r in [fwd(s, t, H)] if r is not None])))

    # ---------- A ----------
    print("\n【A】避開高融資股（融資餘額佔股本比例）")
    rs = sorted(r for s in S for r in [mratio(s, n - 1)] if r is not None and liquid(s, n - 1))
    if rs:
        print("  目前分布：中位數 %.1f%%、前 20%% 的門檻 %.1f%%、最高 %.1f%%；佔股本 10%% 以上 %d 檔、20%% 以上（使用率約 80%%）%d 檔" % (
            rs[len(rs) // 2], rs[int(len(rs) * 0.8)], rs[-1], sum(r >= 10 for r in rs), sum(r >= 20 for r in rs)))
    for name, lo, hi in (("低（<2%）", 0, 2), ("中（2～5%）", 2, 5), ("高（5～10%）", 5, 10), ("很高（≥10%）", 10, 999)):
        sig = [(s, t) for s, t in base for r in [mratio(s, t)] if r is not None and lo <= r < hi]
        for H in HOLDS:
            print("  平常｜融資佔股本 %s｜抱 %d 天：%s" % (name, H, stat([r for s, t in sig for r in [fwd(s, t, H)] if r is not None])))
    for name, lo, hi in (("低（<2%）", 0, 2), ("中（2～5%）", 2, 5), ("高（5～10%）", 5, 10), ("很高（≥10%）", 10, 999)):
        sig = [(s, t0) for t0 in ev for s in S if liquid(s, t0) for r in [mratio(s, t0 - 5)] if r is not None and lo <= r < hi]
        for H in HOLDS:
            print("  大跌後買｜大跌前融資佔股本 %s｜抱 %d 天：%s" % (name, H, stat([r for s, t in sig for r in [fwd(s, t, H)] if r is not None])))
    # 現有的抄底訊號（第 1 批）裡，高融資和低融資的差別
    dip = [(s, t) for s in S for t in range(260, n) if liquid(s, t) and s["c"][t] / max(x for x in s["c"][t - 250:t + 1] if x) - 1 <= -0.25
           and all(s["c"][t - 21:t + 1]) and crash.dip_signal(s, t) and good(s, D[t])]
    print("  ── 現有「好公司跌深抄底」第 1 批訊號，依融資高低分開看")
    show("全部", dip, S)
    show("融資佔股本 <5%", [(s, t) for s, t in dip if (mratio(s, t) or 0) < 5], S)
    show("融資佔股本 ≥5%", [(s, t) for s, t in dip if (mratio(s, t) or 0) >= 5], S)

    # ---------- B ----------
    print("\n【B】融資減肥排名（大跌起始日前 5 天 → 大跌後第 5 天，融資餘額減少幅度；第 6 天開盤買）")
    for only_good in (False, True):
        rows = []
        for t0 in ev:
            t1 = t0 + 5
            if t1 + 1 >= n:
                continue
            L = []
            for s in S:
                mg = s.get("mg") or []
                if not liquid(s, t1) or len(mg) <= t1 or not mg[t1] or not mg[t0 - 5] or (only_good and not good(s, D[t1])):
                    continue
                L.append((mg[t1] / mg[t0 - 5] - 1, s))
            L.sort(key=lambda x: x[0])
            k = len(L) // 3
            rows.append((t1, L[:k], L[k:len(L) - k], L[len(L) - k:]))
        print("  ── %s" % ("只看好公司（賺錢成長＋財報健檢過）" if only_good else "全部個股"))
        for i, name in enumerate(("融資減最多的 1/3", "中間 1/3", "融資減最少（或增加）的 1/3")):
            for H in HOLDS:
                print("  %s｜抱 %d 天：%s" % (name, H, stat([r for t1, *G in rows for _, s in G[i] for r in [fwd(s, t1, H)] if r is not None])))
        for H in HOLDS:
            print("  融資減 15%% 以上｜抱 %d 天：%s" % (H, stat([r for t1, *G in rows for g in G for ch, s in g if ch <= -0.15 for r in [fwd(s, t1, H)] if r is not None])))

    # ---------- C ----------
    print("\n【C】負乖離＋低檔爆量（離季線跌很深、當天量是 20 日均量的倍數、收紅）")
    for dev in (-0.15, -0.20, -0.25):
        for vol in (1.5, 2.0):
            for only_good in (False, True):
                sig = []
                for s in S:
                    c, o, v = s["c"], s["o"], s["v"]
                    for t in range(70, n):
                        if not liquid(s, t) or not o[t]:
                            continue
                        m60 = ma(c, 60, t)
                        if not m60 or c[t] / m60 - 1 > dev or c[t] <= o[t] or v[t] < vol * sum(v[t - 20:t]) / 20:
                            continue
                        if only_good and not good(s, D[t]):
                            continue
                        sig.append((s, t))
                keep = show("季乖離 ≤%d%%、量 ≥%.1f 倍%s" % (dev * 100, vol, "、好公司" if only_good else ""), sig, S)
                if dev == -0.20 and vol == 2.0 and not only_good:
                    # 節目的賣法：反彈到 10 日線就賣（最多抱 20 天）
                    out = []
                    for s, t in keep:
                        c, o, h = s["c"], s["o"], s["h"]
                        if t + 1 >= n or not o[t + 1]:
                            continue
                        e, px = o[t + 1], None
                        for u in range(t + 1, min(t + 21, n)):
                            m10 = ma(c, 10, u)
                            if m10 and h[u] and h[u] >= m10 and u > t + 1:
                                px = max(m10, o[u]) if o[u] and o[u] > m10 else m10
                                break
                        if px is None:
                            if t + 21 >= n:
                                continue
                            px = c[t + 20]
                        out.append(px / e - 1 - COST)
                    print("    ↳ 同一批改成「碰到 10 日線就賣（最多 20 天）」：%s" % stat(out))

    # ---------- D ----------
    print("\n【D】回到年線＋投信買（之前 60 天都在年線上 5% 以上，第一次跌到年線 ±3% 內，年線往上）")
    for name, need_it, need_fi_sell, only_good in (("不看法人", 0, 0, 0), ("投信 5 日買超", 1, 0, 0), ("投信買＋外資賣（土洋對作）", 1, 1, 0),
                                                   ("不看法人、好公司", 0, 0, 1), ("投信 5 日買超、好公司", 1, 0, 1)):
        sig = []
        for s in S:
            c, lo_ = s["c"], s["l"]
            for t in range(245, n):
                if not liquid(s, t):
                    continue
                y, yp = ma(c, 240, t), ma(c, 240, t - 20)
                if not y or not yp or y <= yp or not lo_[t]:
                    continue
                if not (lo_[t] <= y * 1.03 and c[t] >= y * 0.97):
                    continue
                if not all(c[u] and c[u] > y * 1.05 for u in range(t - 60, t - 5)):
                    continue
                it5 = sum(s["it"][i] or 0 for i in range(t - 4, t + 1))
                fi5 = sum(s["fi"][i] or 0 for i in range(t - 4, t + 1))
                if (need_it and it5 <= 0) or (need_fi_sell and fi5 >= 0) or (only_good and not good(s, D[t])):
                    continue
                sig.append((s, t))
        show(name, sig, S)


def yahoo(sym):
    import datetime as dt
    import requests
    ua = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
    for host in ("query1", "query2"):
        try:
            r = requests.get("https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=1262304000&period2=%d&interval=1d&includeAdjustedClose=true"
                             % (host, sym, int(dt.datetime.now().timestamp())), headers=ua, timeout=40)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            q, adj = res["indicators"]["quote"][0], res["indicators"]["adjclose"][0]["adjclose"]
            out = dict(d=[], o=[], l=[], c=[], v=[])
            for i, ts in enumerate(res.get("timestamp") or []):
                if not q["close"][i] or not adj[i] or not q["open"][i] or not q["low"][i]:
                    continue
                k = adj[i] / q["close"][i]  # 還原除權息
                out["d"].append(dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d"))
                out["o"].append(q["open"][i] * k)
                out["l"].append(q["low"][i] * k)
                out["c"].append(adj[i])
                out["v"].append((q["volume"][i] or 0) / 1000)
            return out
        except Exception as e:
            err = e
    print("  ! %s 抓不到：%s" % (sym, err), file=sys.stderr)
    return None


def long_main(path):
    """C、D 用 2010 年起的資料再驗證，分年度看（現在這批股票，所以有「活下來的才在名單裡」的偏差）"""
    import time
    data = json.load(open(path, encoding="utf-8"))
    P = []
    for s in data["stocks"]:
        if s["id"].startswith("00"):
            continue
        x = yahoo(s["id"] + (".TWO" if s.get("mkt") == "tpex" else ".TW"))
        if x and len(x["c"]) > 300:
            P.append(x)
        time.sleep(0.15)
    print("抓到 %d 檔（2010 年起、還原股價）" % len(P))

    def f(x, t, H):
        e = t + 1 + H
        return x["c"][e] / x["o"][t + 1] - 1 - COST if e < len(x["c"]) else None

    def liq(x, t):
        return sum(x["v"][t - 20:t]) / 20 >= 500

    def dedupe(sig):
        last, keep = {}, []
        for i, t in sig:
            if t - last.get(i, -99) > 10:
                keep.append((i, t))
                last[i] = t
        return keep

    def by_year(title, sig):
        print("\n" + title)
        yrs = sorted({P[i]["d"][t][:4] for i, t in sig})
        for H in HOLDS:
            print("  全部｜抱 %d 天：%s" % (H, stat([r for i, t in sig for r in [f(P[i], t, H)] if r is not None])))
        for y in yrs:
            L = [(i, t) for i, t in sig if P[i]["d"][t][:4] == y]
            b = [r for i, t in base if P[i]["d"][t][:4] == y for r in [f(P[i], t, 60)] if r is not None]
            g = [r for i, t in L for r in [f(P[i], t, 60)] if r is not None]
            if g and b:
                print("  %s｜抱 60 天：%s｜同年隨便買 勝率 %.0f%%、平均 %+.1f%%" % (y, stat(g), 100 * sum(r > 0 for r in b) / len(b), 100 * sum(b) / len(b)))

    base = [(i, t) for i, x in enumerate(P) for t in range(245, len(x["c"]), 10) if liq(x, t)]
    print("\n【對照組】隨便買（每 10 天買一次）")
    for H in HOLDS:
        print("  抱 %d 天：%s" % (H, stat([r for i, t in base for r in [f(P[i], t, H)] if r is not None])))

    for dev, vol in ((-0.15, 1.5), (-0.20, 1.5), (-0.20, 2.0), (-0.25, 2.0)):
        sig = []
        for i, x in enumerate(P):
            c, o, v = x["c"], x["o"], x["v"]
            for t in range(245, len(c)):
                m60 = sum(c[t - 59:t + 1]) / 60
                if c[t] / m60 - 1 <= dev and c[t] > o[t] and liq(x, t) and v[t] >= vol * sum(v[t - 20:t]) / 20:
                    sig.append((i, t))
        by_year("【C】季乖離 ≤%d%%、量 ≥%.1f 倍、收紅" % (dev * 100, vol), dedupe(sig))

    for name, band, need_up in (("年線往上、之前 60 天都在年線上 5% 以上、第一次跌到年線 ±3% 內", 0.03, True), ("同上但不管年線方向", 0.03, False)):
        sig = []
        for i, x in enumerate(P):
            c, lo_ = x["c"], x["l"]
            run = sum(c[5:245])
            ys = {}
            for t in range(244, len(c)):
                if t > 244:
                    run += c[t] - c[t - 240]
                ys[t] = sum(c[t - 239:t + 1]) / 240 if t == 244 else run / 240
            for t in range(265, len(c)):
                y = ys[t]
                if need_up and y <= ys[t - 20]:
                    continue
                if not (lo_[t] <= y * (1 + band) and c[t] >= y * (1 - band)) or not liq(x, t):
                    continue
                if all(c[u] > y * 1.05 for u in range(t - 60, t - 5)):
                    sig.append((i, t))
        by_year("【D】回到年線：" + name, dedupe(sorted(sig, key=lambda z: z[1])))


if __name__ == "__main__":
    if "--long" in sys.argv:
        long_main(next((a for a in sys.argv[1:] if not a.startswith("--")), os.path.join(DIR, "data.json")))
    else:
        main()
