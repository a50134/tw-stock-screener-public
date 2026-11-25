"""
2026-11-25 情境機率（odds.py）能不能讓推薦名單更準？
做法：每個策略（含已刪除）過去每天選到的股票（research/strat_hits.js 算），在選到那天，
  用「當時已經知道結果」的歷史（全市場相似情境、結果要在那天以前就揭曉）算出相似情境 20 天上漲比例＝分數；
  再看分數高的、分數低的，實際買了（隔天開盤買、抱 20 天、跌 8% 停損、扣成本 0.6%）哪個好。
另外檢查「隔天最低跌 5% 以上」的機率準不準（預測 vs 實際）。
用法：node research/strat_hits.js data.json hits.json && python research/odds_bt.py data.json hits.json [sop_config.json]
"""
import bisect
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import odds  # noqa: E402

d = json.load(open(sys.argv[1], encoding="utf-8"))
hits = json.load(open(sys.argv[2], encoding="utf-8"))
skip = set()
if len(sys.argv) > 3 and os.path.exists(sys.argv[3]):
    skip = set(json.load(open(sys.argv[3], encoding="utf-8")).get("skip") or [])
D, S = d["dates"], d["stocks"]
n = len(D)
di = {x: i for i, x in enumerate(D)}
SI = {s["id"]: s for s in S}
START = 150  # 前面的日子歷史太少，不評分


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


# 全市場情境庫，依「放寬程度」分別建索引：level → key → 依時間排序的 (t, 20 天上漲, 隔天跌 5%)
P = odds.pool_market(d)
IDX = {}
for lv in odds.LEVELS:
    if 4 in lv:
        continue
    m = defaultdict(list)
    for k, t, y in P:
        if all(k[i] is not None for i in lv):
            m[tuple(k[i] for i in lv)].append((t, 1 if y[4] > 0 else 0, 1 if y[0] <= -0.05 else 0))
    for v in m.values():
        v.sort()
    ts = {k: [x[0] for x in v] for k, v in m.items()}
    pre = {}
    for k, v in m.items():
        a, b, acc = [0], [0], (0, 0)
        for x in v:
            acc = (acc[0] + x[1], acc[1] + x[2])
            a.append(acc[0])
            b.append(acc[1])
        pre[k] = (a, b)
    IDX[lv] = (ts, pre)


def score(key, T):
    """只用 t + 20 < T 的歷史：回傳 (20 天上漲比例, 隔天跌 5% 比例, 筆數)"""
    for lv in odds.LEVELS:
        if 4 in lv or any(key[i] is None for i in lv):
            continue
        ts, pre = IDX[lv]
        k = tuple(key[i] for i in lv)
        if k not in ts:
            continue
        j = bisect.bisect_left(ts[k], T - 20)  # t < T-20
        if j >= odds.MIN_N:
            a, b = pre[k]
            return a[j] / j, b[j] / j, j
    return None


def summary(rows):
    if not rows:
        return "0 筆"
    w = sum(1 for r in rows if r > 0) / len(rows)
    return "%d 筆、勝率 %d%%、平均 %+.1f%%" % (len(rows), round(w * 100), sum(rows) / len(rows) * 100)


picks = []  # (策略, 是否還在用, T, id, 分數, 隔天跌5%機率, 結果, 實際隔天最低)
for k, v in hits.items():
    last = {}
    for day, ids in sorted(v["days"].items()):
        T = di[day]
        if T < START:
            continue
        for i in ids:
            s = SI.get(i)
            if not s or str(i).startswith("00") or (i in last and T - last[i] < 20):
                continue
            f = odds.feats(s["c"], T, s.get("fi"))
            r = fwd(s, T)
            if not f or r is None:
                continue
            sc = score(f + (None,), T)
            if not sc:
                continue
            last[i] = T
            lo = s["l"][T + 1] / s["c"][T] - 1 if s["l"][T + 1] and s["c"][T] else None
            picks.append((k, k not in skip, T, i, sc[0], sc[1], r, lo))

print("資料 %s～%s，策略選到的股票（同策略同一檔 20 天內只算一次）、第 %d 天以後才評分" % (D[0], D[-1], START))
for name, rows in (("全部策略（含已刪除）", picks), ("現在還在用的策略", [p for p in picks if p[1]])):
    print("\n【%s】" % name)
    print("  全部：", summary([p[6] for p in rows]))
    if len(rows) < 30:
        continue
    sc = sorted(p[4] for p in rows)
    q1, q2 = sc[len(sc) // 3], sc[2 * len(sc) // 3]
    print("  分數低（相似情境 20 天上漲 < %d%%）：" % round(q1 * 100), summary([p[6] for p in rows if p[4] < q1]))
    print("  分數中：", summary([p[6] for p in rows if q1 <= p[4] < q2]))
    print("  分數高（≥ %d%%）：" % round(q2 * 100), summary([p[6] for p in rows if p[4] >= q2]))
    for cut in (0.45, 0.5, 0.55, 0.6):
        print("  只留分數 ≥ %d%%：" % round(cut * 100), summary([p[6] for p in rows if p[4] >= cut]),
              "｜剔除的：", summary([p[6] for p in rows if p[4] < cut]))
    # 隔天最低跌 5% 以上：預測準不準
    cal = defaultdict(lambda: [0, 0])
    for p in rows:
        if p[7] is None:
            continue
        b = min(int(p[5] * 10), 4)
        cal[b][0] += 1
        cal[b][1] += p[7] <= -0.05
    print("  隔天最低跌 5% 以上：預測機率 → 實際（筆數）")
    for b in sorted(cal):
        print("    預測 %d～%d%% → 實際 %d%%（%d 筆）" % (b * 10, b * 10 + 10 if b < 4 else 100, round(cal[b][1] / cal[b][0] * 100), cal[b][0]))
# 每個策略各自：分數高 vs 低
print("\n【各策略：分數 ≥ 55% vs < 55%】（至少 20 筆才列）")
by = defaultdict(list)
for p in picks:
    by[p[0]].append(p)
for k, rows in sorted(by.items(), key=lambda x: -len(x[1])):
    if len(rows) < 20:
        continue
    print("  %s %s%s：全部 %s｜高 %s｜低 %s" % (k, hits[k]["name"][:14], "" if k not in skip else "（已刪）", summary([p[6] for p in rows]),
                                           summary([p[6] for p in rows if p[4] >= 0.55]), summary([p[6] for p in rows if p[4] < 0.55])))
print("\n注意：只有約 1 年半的資料、而且是現在還在名單上的股票（倖存者偏差），結果只能當參考。")
