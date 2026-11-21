"""
2026-11-16 使用者要的「新想法勝率太低時，和既有策略（含已刪除）搭配看看」回測
資料：網頁資料 data.json（約 1 年半）；策略每天選到的股票由 research/strat_hits.js 算（網頁同一套條件）
新想法（單獨勝率低、沒加入的）：
  SEPA 趨勢樣板突破、16 種型態的偏多 8 種、融資換手（融資 20 天減 5%＋法人買＋創 60 天新高）、
  一年高點 5% 內＋外資買、投信一直買＋股價在投信成本附近、MACD 翻正＋布林開口＋站上上揚月線（2026-11-17）、PEG < 0.75、短期反轉（大型股 5 日跌最多的 10%，2026-11-21）
搭配＝新想法今天出現訊號，而且這檔近 5 個交易日內被某策略選到 → 隔天開盤買，抱 20 天，跌 8% 停損，扣成本 0.6%
同一個搭配、同一檔 20 天內只算一次；至少 15 筆才列出
用法：node research/strat_hits.js data.json hits.json && python research/combo_bt.py data.json hits.json
"""
import json
import os
import statistics as stt
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from pattern_bt import BULL, NAMES, detect, K, LB  # noqa: E402
from sepa_bt import MA  # noqa: E402
from macd_boll_bt import signals as mb_signals  # noqa: E402

d = json.load(open(sys.argv[1], encoding="utf-8"))
hits = json.load(open(sys.argv[2], encoding="utf-8"))
D, S = d["dates"], d["stocks"]
n = len(D)
di = {x: i for i, x in enumerate(D)}
m0050 = next((s["c"] for s in S if s["id"] == "0050"), None)
if not m0050 or not all(m0050[-260:]):  # 資料裡沒有 0050 時，用全部股票的等權平均當大盤
    m0050, lv = [], 100.0
    for t in range(n):
        if t:
            rr = [s["c"][t] / s["c"][t - 1] - 1 for s in S if not s["id"].startswith("00") and s["c"][t] and s["c"][t - 1] and abs(s["c"][t] / s["c"][t - 1] - 1) < 0.11]
            lv *= 1 + (stt.median(rr) if rr else 0)
        m0050.append(lv)
MM = MA([x or 0 for x in m0050])


def fwd(s, t, H=20, stop=0.08):
    c, o, l = s["c"], s["o"], s["l"]
    e = t + 1 + H
    if e >= n or not o[t + 1] or not all(c[t:e + 1]) or any(abs(c[i] / c[i - 1] - 1) > 0.11 for i in range(t + 1, e + 1)):
        return None
    p = o[t + 1]
    for u in range(t + 1, e + 1):
        if l[u] and l[u] <= p * (1 - stop):
            return min(o[u] or p, p * (1 - stop)) / p - 1 - 0.006
    return c[e] / p - 1 - 0.006


def sm(a, t, k):
    return sum(x or 0 for x in a[t - k + 1:t + 1]) if a and t >= k - 1 else 0


# 每個策略：股票 → 被選到的日子（索引）
pick = {k: defaultdict(set) for k in hits}
for k, v in hits.items():
    for day, ids in v["days"].items():
        for i in ids:
            pick[k][i].add(di[day])

QEND = {"Q1": "-05-15", "Q2": "-08-14", "Q3": "-11-14", "Q4": "-03-31"}  # 季報最晚公布日（Q4 是隔年）


def ttm_eps(s, day):
    """day 當天已公布的近 4 季 EPS 合計、與一年前的近 4 季合計"""
    qs = []
    for q in s.get("q") or []:
        y, k = int(q["q"][:4]), q["q"][4:]
        pub = ("%d" % (y + 1) if k == "Q4" else "%d" % y) + QEND[k]
        if pub <= day and q.get("eps") is not None:
            qs.append(q["eps"])
    if len(qs) < 8:
        return None, None
    return sum(qs[-4:]), sum(qs[-8:-4])


BIG = {x["id"] for _, x in sorted(((float(x["shares"]) * x["c"][-1], x) for x in S if not x["id"].startswith("00") and x.get("shares") and x["c"][-1]), key=lambda z: -z[0])[:50]}
REV = {}  # 每 5 天：大型股 5 日跌幅最大的 10%
for t in range(70, n - 2, 1):
    L = sorted((s["c"][t] / s["c"][t - 5] - 1, s["id"]) for s in S if s["id"] in BIG and s["c"][t] and s["c"][t - 5])
    for r, sid in L[:max(1, len(L) // 10)]:
        REV.setdefault(sid, set()).add(t)
IDEA = {}  # (想法, 股票) → 訊號日
for s in S:
    sid, c, o, h, l, v = s["id"], s["c"], s["o"], s["h"], s["l"], s["v"]
    if sid.startswith("00") or not c[-1] or not all(c[-250:]) or not all(o[-250:]):
        continue
    if any(x is None for x in c + o + h + l + v):
        continue
    mv, mc = MA(v), MA(c)
    ph = [K <= i < n - K and h[i] == max(h[i - K:i + K + 1]) for i in range(n)]
    pl = [K <= i < n - K and l[i] == min(l[i - K:i + K + 1]) for i in range(n)]
    fi, it, mg = s.get("fi") or [], s.get("it") or [], s.get("mg") or []
    mb = set(mb_signals(o, h, l, c, v)[0])
    for t in range(LB + 10, n - 2):
        if (mv(20, t - 1) or 0) < 300:
            continue
        sig = set()
        for p in detect(o, h, l, c, v, ph, pl, mv, t):
            if p in BULL:
                sig.add(NAMES[p])
        if t >= 252:  # SEPA 趨勢樣板突破（強過 0050、0050 在 50 日線上）
            m50, m150, m200 = mc(50, t), mc(150, t), mc(200, t)
            if (c[t] > m50 > m150 > m200 and m200 > mc(200, t - 20) and c[t] >= min(l[t - 251:t + 1]) * 1.3
                    and c[t] >= max(h[t - 251:t + 1]) * 0.75 and v[t] > mv(50, t) * 1.5 and c[t] > max(h[t - 20:t])
                    and c[t] / c[t - 250] > m0050[t] / m0050[t - 250] and m0050[t] > MM(50, t)):
                sig.add("SEPA 趨勢樣板突破")
            if c[t] >= max(c[t - 249:t + 1]) * 0.95 and sm(fi, t, 20) > 0:
                sig.add("一年高點 5% 內＋外資買")
        if len(mg) > t and mg[t] and mg[t - 20] and mg[t] < mg[t - 20] * 0.95 and c[t] >= max(c[t - 59:t + 1]) and sm(fi, t, 20) + sm(it, t, 20) > 0:
            sig.add("融資換手＋創 60 天新高")
        if it and sum((x or 0) > 0 for x in it[t - 19:t + 1]) >= 12 and sm(it, t, 60) > 0:
            ww = [(it[k], c[k]) for k in range(t - 59, t + 1) if (it[k] or 0) > 0]
            cost = sum(a * b for a, b in ww) / sum(a for a, _ in ww)
            if -0.05 <= c[t] / cost - 1 <= 0.03:
                sig.add("投信一直買＋股價在投信成本附近")
        if t in mb:
            sig.add("MACD 翻正＋布林開口＋站上上揚月線")
        if t in REV.get(sid, ()):
            sig.add("短期反轉：大型股 5 日跌最多的 10%")
        if t % 5 == 0:
            e1, e0 = ttm_eps(s, D[t])
            if e1 and e0 and e0 > 0 and e1 > e0:
                peg = (c[t] / e1) / ((e1 / e0 - 1) * 100)
                if peg < 0.75:
                    sig.add("PEG < 0.75（本益比÷EPS 年增率）")
                if peg < 0.75 and c[t] > mc(60, t):
                    sig.add("PEG < 0.75＋站上季線")
        for g in sig:
            IDEA.setdefault((g, sid), []).append(t)

SS = {s["id"]: s for s in S}


def stats(L):
    L = [x for x in L if x is not None]
    if not L:
        return None
    return len(L), sum(x > 0 for x in L) / len(L), stt.mean(L)


# 策略單獨（第一次被選到，20 天內不重複）
alone = {}
for k in hits:
    R = []
    for sid, days in pick[k].items():
        last = -99
        for t in sorted(days):
            if t - last > 20 and sid in SS:
                last = t
                R.append(fwd(SS[sid], t))
    alone[k] = stats(R)
ideas = sorted({g for g, _ in IDEA})
solo = {}
for g in ideas:
    R = []
    for (gg, sid), ts in IDEA.items():
        if gg != g:
            continue
        last = -99
        for t in ts:
            if t - last > 20:
                last = t
                R.append(fwd(SS[sid], t))
    solo[g] = stats(R)
rows = []
for g in ideas:
    for k in hits:
        R = []
        for (gg, sid), ts in IDEA.items():
            if gg != g:
                continue
            last = -99
            for t in ts:
                if t - last > 20 and any(u in pick[k][sid] for u in range(t - 4, t + 1)):
                    last = t
                    R.append(fwd(SS[sid], t))
        st = stats(R)
        if st and st[0] >= 15:
            rows.append((g, k, st))
print("資料 %s～%s；訊號隔天開盤買、抱 20 天、跌 8%% 停損\n" % (D[0], D[-1]))
print("【新想法單獨】")
for g in ideas:
    st = solo[g]
    if st:
        print("・%-24s %4d 筆｜勝率 %3.0f%%｜平均 %+5.1f%%" % (g, st[0], 100 * st[1], 100 * st[2]))
print("\n【策略單獨】（含已刪除）")
for k, st in alone.items():
    if st:
        print("・%-4s %-22s %4d 筆｜勝率 %3.0f%%｜平均 %+5.1f%%" % (k, hits[k]["name"][:22], st[0], 100 * st[1], 100 * st[2]))
print("\n【搭配】勝率由高到低（至少 15 筆），↑＝比策略單獨勝率高幾個百分點")
for g, k, st in sorted(rows, key=lambda r: -r[2][1])[:40]:
    a = alone.get(k)
    print("・%-24s ＋ %-4s %-18s %4d 筆｜勝率 %3.0f%%（%s）｜平均 %+5.1f%%" % (
        g, k, hits[k]["name"][:18], st[0], 100 * st[1], ("↑%+.0f" % (100 * (st[1] - a[1]))) if a else "—", 100 * st[2]))
