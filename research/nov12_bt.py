"""
2026-11-12 錢線百分百三集的想法回測（每晚 data.json，約 2025-03～2026-11）
1. 大跌後的反彈：「領先過前波高」的強勢股 vs「均線空方排列、反彈無力」的弱勢股；強勢股回測 5 日線再買
2. MACD：DIF>0 且柱狀體>0（多方）、DIF<0 但柱狀體負值縮小（跌深反彈）、其他
3. 融資連減＋不破底（築底）的好公司：建承說記憶體融資一直減、底部不破就可以買
買進：訊號隔天開盤；停損 −8%（逆勢的 3 用 −15%）；同一檔 10 天內只算一次
"""
import json
import os
import statistics as st
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import crash
import fin_health

d = json.load(open(sys.argv[1], encoding="utf-8"))
D, S = d["dates"], d["stocks"]
n = len(D)
m = next(x["c"] for x in S if x["id"] == "0050")
ev = crash.events(D, m)


def ma(c, k, t):
    w = c[t - k + 1:t + 1]
    return sum(w) / k if t >= k - 1 and all(w) else None


def ema(c, k):
    out, e = [], None
    for x in c:
        e = x if e is None else (x * 2 / (k + 1) + e * (1 - 2 / (k + 1)) if x else e)
        out.append(e)
    return out


def fwd(s, t, H, stop=0.08):
    c, o, l = s["c"], s["o"], s["l"]
    e = t + 1 + H
    if e >= n or not o[t + 1] or not all(c[t:e + 1]) or any(abs(c[i] / c[i - 1] - 1) > 0.11 for i in range(t + 1, e + 1)):
        return None
    p = o[t + 1]
    for u in range(t + 1, e + 1):
        if l[u] and l[u] <= p * (1 - stop):
            return min(o[u] or p, p * (1 - stop)) / p - 1 - 0.006
    return c[e] / p - 1 - 0.006


def show(name, L):
    L = [x for x in L if x is not None]
    if not L:
        print("・%s：0 筆" % name)
        return
    print("・%-34s %4d 筆｜勝率 %3.0f%%｜平均 %+5.1f%%｜最差 %+4.0f%%" % (name, len(L), 100 * sum(x > 0 for x in L) / len(L), 100 * st.mean(L), 100 * min(L)))


def liquid(s, t):
    v = s["v"]
    return not s["id"].startswith("00") and s["c"][t] and t > 70 and all(v[t - 20:t]) and sum(v[t - 20:t]) / 20 >= 500


print("資料 %s～%s；大跌事件：%s" % (D[0], D[-1], "、".join(D[e] for e in ev)))
# ---------- 1 ----------
print("\n【1】大跌後反彈：領先過前波高 vs 弱勢（抱 20 天，停損 −8%）")
R = {k: [] for k in ("強勢：先過前波高，隔天買", "強勢：過高後回測 5 日線才買", "弱勢：均線空方排列、反彈不到大盤一半", "全部（大跌後第 5 天買）")}
for t0 in ev:
    lo_t = min(range(t0, min(t0 + 10, n)), key=lambda k: m[k])
    mk = lambda t: m[t] / m[lo_t] - 1
    for s in S:
        c, l = s["c"], s["l"]
        if not liquid(s, t0) or t0 < 30:
            continue
        pre = max(x for x in c[t0 - 25:t0 - 4] if x)  # 大跌前的前波高
        if t0 + 6 < n:
            R["全部（大跌後第 5 天買）"].append(fwd(s, t0 + 5, 20))
        hit = next((t for t in range(t0 + 1, min(t0 + 25, n - 2)) if c[t] and c[t] > pre), None)
        if hit:
            R["強勢：先過前波高，隔天買"].append(fwd(s, hit, 20))
            pb = next((t for t in range(hit + 1, min(hit + 15, n - 2)) if l[t] and ma(c, 5, t) and l[t] <= ma(c, 5, t)), None)
            if pb:
                R["強勢：過高後回測 5 日線才買"].append(fwd(s, pb, 20))
        t5 = t0 + 7
        if t5 < n - 2 and c[t5] and ma(c, 60, t5):
            lo_s = min(x for x in c[t0:t5 + 1] if x)
            if ma(c, 5, t5) < ma(c, 20, t5) < ma(c, 60, t5) and c[t5] / lo_s - 1 < 0.5 * mk(t5):
                R["弱勢：均線空方排列、反彈不到大盤一半"].append(fwd(s, t5, 20))
for k, v in R.items():
    show(k, v)

# ---------- 2 ----------
print("\n【2】MACD（12/26/9）每 5 天看一次，抱 20 天，停損 −8%")
M = {k: [] for k in ("多方：DIF>0 且柱狀體>0", "跌深反彈：DIF<0、柱狀體負值縮小", "空方：DIF<0、柱狀體負值擴大", "其他")}
for s in S:
    c = s["c"]
    if not c[-1] or s["id"].startswith("00"):
        continue
    e12, e26 = ema(c, 12), ema(c, 26)
    dif = [a - b if a and b else None for a, b in zip(e12, e26)]
    dea = ema([x or 0 for x in dif], 9)
    hist = [(x - y) if x is not None else None for x, y in zip(dif, dea)]
    for t in range(80, n - 2, 5):
        if not liquid(s, t) or hist[t] is None or hist[t - 1] is None:
            continue
        if dif[t] > 0 and hist[t] > 0:
            k = "多方：DIF>0 且柱狀體>0"
        elif dif[t] < 0 and hist[t] < 0 and hist[t] > hist[t - 1]:
            k = "跌深反彈：DIF<0、柱狀體負值縮小"
        elif dif[t] < 0 and hist[t] < hist[t - 1]:
            k = "空方：DIF<0、柱狀體負值擴大"
        else:
            k = "其他"
        M[k].append(fwd(s, t, 20))
for k, v in M.items():
    show(k, v)

# ---------- 3 ----------
print("\n【3】融資連減＋不破底的好公司（離一年高點跌 25% 以上；融資 20 天減 15% 以上；近 10 天沒破前 20 天低點）")
B = {"築底買": {20: [], 60: []}, "同樣跌深但融資沒減": {20: [], 60: []}}
for s in S:
    c, mg = s["c"], s.get("mg") or []
    last = -99
    for t in range(260, n - 2):
        if t - last <= 10 or not liquid(s, t) or len(mg) <= t or not mg[t] or not mg[t - 20]:
            continue
        hi = max(x for x in c[t - 250:t + 1] if x)
        if c[t] / hi - 1 > -0.25 or not crash.grows(s, D[t]) or fin_health.check(s, D[t])[0] is not True:
            continue
        floor = min(x for x in c[t - 30:t - 10] if x)
        held = min(x for x in c[t - 9:t + 1] if x) >= floor
        k = "築底買" if mg[t] / mg[t - 20] - 1 <= -0.15 and held else ("同樣跌深但融資沒減" if mg[t] / mg[t - 20] - 1 > -0.05 else None)
        if not k:
            continue
        last = t
        for H in (20, 60):
            B[k][H].append(fwd(s, t, H, 0.15))
for k, v in B.items():
    for H in (20, 60):
        show("%s｜抱 %d 天（停損 −15%%）" % (k, H), v[H])
