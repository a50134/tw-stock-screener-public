"""
錢線百分百 11 月節目三個說法的回測
1. 日KD超跌（11/02「日KD驚現超跌訊號 過去4次買都賺」）：加權指數日 KD（9,3,3）K、D 都低於 20／K 低於 10 → 買大盤，看 20／60／120 天
2. 月線負乖離（11/20 前後新聞「月線負乖離 15% 嚴重超跌」）：加權指數收盤比月線（20 日）低 8%／10%／15% → 同上，另看之後還會再跌多深
3. 逆勢抗跌股（11/20「逆勢抗跌」）：大盤從 60 日高點跌 15% 以上那天，市值前 150 檔依「這段期間跌多少」分 5 組，
   看隔天開盤買、60 天後哪一組漲最多（抗跌的贏，還是跌最深的反彈最大）
資料：Yahoo（加權指數約 25 年、個股約 11 年，還原權息）
用法：python research/tv_bt.py data.json
"""
import json
import os
import statistics as stt
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sepa_bt import yahoo  # noqa: E402

H = (20, 60, 120)


def kd(h, l, c, n=9):
    K, D, k, d = [], [], 50.0, 50.0
    for t in range(len(c)):
        lo, hi = min(l[max(0, t - n + 1):t + 1]), max(h[max(0, t - n + 1):t + 1])
        rsv = (c[t] - lo) / (hi - lo) * 100 if hi > lo else 50
        k = k * 2 / 3 + rsv / 3
        d = d * 2 / 3 + k / 3
        K.append(k)
        D.append(d)
    return K, D


def report(name, ts, D, c, l, gap=20):
    """訊號日（同一波 gap 天內只算第一次）→ 收盤買，看 20／60／120 天報酬與之後最深再跌"""
    pick, last = [], -999
    for t in ts:
        if t - last > gap:
            pick.append(t)
            last = t
    if not pick:
        print("%s：沒有訊號" % name)
        return
    print("\n【%s】共 %d 次" % (name, len(pick)))
    for hh in H:
        r = [c[t + hh] / c[t] - 1 for t in pick if t + hh < len(c)]
        if r:
            print("　%3d 天：賺錢 %d/%d（%.0f%%）、平均 %+.1f%%、中位數 %+.1f%%、最差 %+.1f%%" % (
                hh, sum(x > 0 for x in r), len(r), sum(x > 0 for x in r) / len(r) * 100, stt.mean(r) * 100, stt.median(r) * 100, min(r) * 100))
    dd = [min(l[t + 1:t + 61]) / c[t] - 1 for t in pick if t + 61 < len(c)]
    if dd:
        print("　訊號後 60 天內再跌：中位數 %.1f%%、最深 %.1f%%" % (stt.median(dd) * 100, min(dd) * 100))
    print("　各次：" + "、".join("%s(%s)" % (D[t][2:], "%+.0f%%" % ((c[t + 60] / c[t] - 1) * 100) if t + 60 < len(c) else "未滿") for t in pick[-12:]))


def base(D, c):
    for hh in H:
        r = [c[t + hh] / c[t] - 1 for t in range(0, len(c) - hh, 5)]
        print("　隨便買 %3d 天：賺錢 %.0f%%、平均 %+.1f%%" % (hh, sum(x > 0 for x in r) / len(r) * 100, stt.mean(r) * 100))


def main(path):
    rows = yahoo("%5ETWII", 26)
    D = [r[0] for r in rows]
    o, h, l, c = ([r[i] for r in rows] for i in range(1, 5))
    print("加權指數 %s～%s，%d 天" % (D[0], D[-1], len(D)))
    print("【比較基準】")
    base(D, c)
    K, Dd = kd(h, l, c)
    n = len(c)
    report("1a 日KD 都低於 20", [t for t in range(30, n) if K[t] < 20 and Dd[t] < 20], D, c, l)
    report("1b 日K 低於 10", [t for t in range(30, n) if K[t] < 10], D, c, l)
    report("1c 日KD 低於 20 後 K 往上穿過 D（黃金交叉）", [t for t in range(31, n) if Dd[t] < 25 and K[t - 1] < Dd[t - 1] and K[t] > Dd[t]], D, c, l)
    m20 = [None] * 19 + [sum(c[t - 19:t + 1]) / 20 for t in range(19, n)]
    for th in (0.08, 0.10, 0.15):
        report("2 收盤比月線低 %d%% 以上" % (th * 100), [t for t in range(30, n) if c[t] < m20[t] * (1 - th)], D, c, l, gap=40)
    print("\n現在：%s 日K %.0f、D %.0f；收盤比月線 %+.1f%%" % (D[-1], K[-1], Dd[-1], (c[-1] / m20[-1] - 1) * 100))

    # 3. 逆勢抗跌股
    d = json.load(open(path, encoding="utf-8"))
    U = sorted(((float(x["shares"]) * x["c"][-1], x) for x in d["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"] and x["c"][-1]), key=lambda z: -z[0])[:150]
    ti = {x: i for i, x in enumerate(D)}
    ev, last = [], -999
    for t in range(60, n):
        hi = max(range(t - 59, t + 1), key=lambda k: c[k])
        if c[t] / c[hi] - 1 <= -0.15 and t - last > 120:
            ev.append((t, hi))
            last = t
    ev = [(D[t], D[hi]) for t, hi in ev if D[t] >= "2015-06-01"]
    print("\n【3 逆勢抗跌股】大盤從 60 日高點跌 15%% 以上的日子（2015 年後）：%s" % "、".join(e[0] for e in ev))
    S = {}
    for _, x in U:
        r = yahoo(x["id"] + (".TWO" if x.get("mkt") == "tpex" else ".TW"))
        if len(r) > 400:
            S[x["id"]] = {z[0]: z for z in r}
    print("個股 %d 檔" % len(S))
    G = {g: {hh: [] for hh in (20, 60)} for g in range(5)}
    for de, dh in ev:
        rows_ = []
        for sid, m in S.items():
            ds = sorted(m)
            if de not in m or dh not in m:
                continue
            i = ds.index(de)
            if i + 61 >= len(ds):
                continue
            fall = m[de][4] / m[dh][4] - 1
            e = m[ds[i + 1]][1]
            rows_.append((fall, {hh: m[ds[i + 1 + hh]][4] / e - 1 for hh in (20, 60)}))
        if len(rows_) < 50:
            continue
        rows_.sort(key=lambda z: -z[0])  # 第 0 組＝跌最少（最抗跌）
        q = len(rows_) // 5
        line = []
        for g in range(5):
            part = rows_[g * q:(g + 1) * q]
            for hh in (20, 60):
                G[g][hh] += [z[1][hh] for z in part]
            line.append("%+.0f%%" % (stt.mean(z[1][60] for z in part) * 100))
        print("　%s：60 天報酬 抗跌→跌深 5 組 %s" % (de, " ".join(line)))
    names = ["最抗跌", "次抗跌", "中間", "次跌深", "跌最深"]
    for g in range(5):
        if G[g][60]:
            print("　%s：20 天平均 %+.1f%%、60 天平均 %+.1f%%、60 天賺錢 %.0f%%（%d 筆）" % (
                names[g], stt.mean(G[g][20]) * 100, stt.mean(G[g][60]) * 100, sum(x > 0 for x in G[g][60]) / len(G[g][60]) * 100, len(G[g][60])))


if __name__ == "__main__":
    main(sys.argv[1])
