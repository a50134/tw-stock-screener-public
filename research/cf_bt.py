"""
C：年底投信作帳選股（錢線 11/11）：投信 10 天內買超 6 天以上＋最新月營收創 12 個月新高＋同產業 3 家以上也創高＋股價在月線上
F：記憶體股在「好公司跌深抄底」第 1 批買訊裡，表現是不是比較差
資料：每晚的 data.json（約 2025-03～2026-11，只有一次年底）。用法：python research/cf_bt.py data.json
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
MEM = {"2408", "2344", "2337", "6770", "8299", "3260", "4967", "3006", "5351", "6531", "8150", "2451"}


def ma(c, k, t):
    w = c[t - k + 1:t + 1]
    return sum(w) / k if all(w) else None


def ok_window(c, t, e):
    cc = c[t:e + 1]
    return all(cc) and not any(abs(cc[i] / cc[i - 1] - 1) > 0.11 for i in range(1, len(cc)))


def fwd(s, t, H, stop=0.08):
    c, o, l = s["c"], s["o"], s["l"]
    e = t + 1 + H
    if e >= n or not o[t + 1] or not ok_window(c, t, e):
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
    print("・%s：%4d 筆｜勝率 %3.0f%%｜平均 %+5.1f%%｜最差 %+4.0f%%" % (name, len(L), 100 * sum(x > 0 for x in L) / len(L), 100 * st.mean(L), 100 * min(L)))


def pub(m):  # 月營收 YYYY-MM 在隔月 10 日公布
    y, mm = int(m[:4]), int(m[5:])
    y, mm = (y + 1, 1) if mm == 12 else (y, mm + 1)
    return "%d-%02d-10" % (y, mm)


def rev_high(s, day):
    R = [x for x in (s.get("rev") or []) if pub(x["m"]) <= day and x.get("v")]
    if len(R) < 13:
        return None
    return R[-1]["m"] if R[-1]["v"] >= max(x["v"] for x in R[-13:-1]) else ""


def liquid(s, t):
    v = s["v"]
    return not s["id"].startswith("00") and s["c"][t] and all(v[t - 20:t]) and sum(v[t - 20:t]) / 20 >= 500


print("資料 %s～%s" % (D[0], D[-1]))
# ---------- C ----------
print("\n【C】年底投信作帳選股（買進：隔天開盤；停損 −8%；同一檔 10 天內只算一次）")
sig = {k: [] for k in ("全部隨便買", "投信 10 天買超 6 天以上", "＋營收創 12 個月新高", "＋同產業 3 家以上創高", "＋股價在月線上（完整條件）")}
for t in range(80, n - 2, 1):
    day = D[t]
    hi = {}
    for s in S:
        if s["id"].startswith("00"):
            continue
        r = rev_high(s, day)
        if r:
            hi.setdefault((s.get("industry"), r), 0)
            hi[(s.get("industry"), r)] += 1
    for s in S:
        if not liquid(s, t):
            continue
        if t % 5 == 0:
            sig["全部隨便買"].append((s, t))
        it = s["it"][t - 9:t + 1]
        if sum(1 for x in it if (x or 0) > 0) < 6 or sum(x or 0 for x in it) <= 0:
            continue
        sig["投信 10 天買超 6 天以上"].append((s, t))
        r = rev_high(s, day)
        if not r:
            continue
        sig["＋營收創 12 個月新高"].append((s, t))
        if hi.get((s.get("industry"), r), 0) < 3:
            continue
        sig["＋同產業 3 家以上創高"].append((s, t))
        m20 = ma(s["c"], 20, t)
        if m20 and s["c"][t] > m20:
            sig["＋股價在月線上（完整條件）"].append((s, t))


def dedupe(L):
    last, out = {}, []
    for s, t in sorted(L, key=lambda x: x[1]):
        if t - last.get(s["id"], -99) > 10:
            out.append((s, t))
            last[s["id"]] = t
    return out


q4 = lambda t: D[t][5:] >= "10-15" or D[t][5:] <= "01-10"
for H in (20, 40):
    print("抱 %d 天" % H)
    for k, L in sig.items():
        L = dedupe(L) if k != "全部隨便買" else L
        show(k + "｜全年", [fwd(s, t, H) for s, t in L])
        show(k + "｜只看年底（10/15～1/10）", [fwd(s, t, H) for s, t in L if q4(t)])
full = dedupe(sig["＋股價在月線上（完整條件）"])
print("完整條件最近 10 筆：", "、".join("%s %s %s" % (D[t], s["id"], s["name"]) for s, t in full[-10:]))

# ---------- F ----------
print("\n【F】記憶體股 vs 其他：好公司跌深抄底的第 1 批買訊（比一年高點跌 25% 以上、財報健檢過、近 4 季賺錢且成長）")
mem, oth = {20: [], 60: []}, {20: [], 60: []}
for s in S:
    if s["id"].startswith("00"):
        continue
    last = -99
    for t in range(260, n - 2):
        if t - last <= 10 or not liquid(s, t):
            continue
        c = s["c"]
        if not all(c[t - 250:t + 1]) or c[t] / max(c[t - 250:t + 1]) - 1 > -0.25 or not crash.dip_signal(s, t):
            continue
        if not crash.grows(s, D[t]) or fin_health.check(s, D[t])[0] is not True:
            continue
        last = t
        for H in (20, 60):
            (mem if s["id"] in MEM else oth)[H].append(fwd(s, t, H))
for H in (20, 60):
    show("記憶體股｜抱 %d 天" % H, mem[H])
    show("其他股票｜抱 %d 天" % H, oth[H])
print("\n記憶體股整體（不看買訊）近 60 天、近 120 天漲跌：")
for s in S:
    if s["id"] in MEM and s["c"][-1]:
        c = s["c"]
        print("  %s %s：60 天 %+.0f%%、120 天 %+.0f%%、離一年高點 %+.0f%%" % (s["id"], s["name"], (c[-1] / c[-61] - 1) * 100, (c[-1] / c[-121] - 1) * 100, (c[-1] / max(x for x in c[-250:] if x) - 1) * 100))
