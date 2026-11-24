"""
錢線百分百 2026-11-23（下集）「低波動＋高成交量 低 Beta 神股」回測
低 Beta＝股價跟大盤連動小（大盤跌 1%，它平均跌不到 1%）
做法：2016 年起每 20 個交易日，市值前 150 檔用過去 250 天算 Beta（對加權指數）與平均成交量，
  A 低 Beta 組（Beta 最低 1/5）  B 低 Beta＋高成交量（Beta 最低 1/3 且成交量前一半）  C 高 Beta 組（最高 1/5）  全部＝150 檔平均
  每組同金額買進抱 20 天，算：平均報酬、賺錢機率、整段累計、最大跌幅；另外只看「大跌中」（加權指數離 60 日高點 −10% 以上）買進的成績
用法：python research/tv_20261123_bt.py data.json
"""
import json
import os
import statistics as stt
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sepa_bt import yahoo  # noqa: E402

HOLD = 20


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    U = sorted(((float(x["shares"]) * x["c"][-1], x) for x in d["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"] and x["c"][-1]), key=lambda z: -z[0])[:150]
    tw = {r[0]: r[4] for r in yahoo("%5ETWII", 12)}
    D = sorted(tw)
    S = {}
    for _, x in U:
        r = yahoo(x["id"] + (".TWO" if x.get("mkt") == "tpex" else ".TW"))
        if len(r) > 300:
            S[x["id"]] = {z[0]: (z[4], z[5]) for z in r}
    print("個股 %d 檔，加權指數 %s～%s" % (len(S), D[0], D[-1]))
    G = {k: [] for k in ("A 低 Beta", "B 低 Beta＋高成交量", "C 高 Beta", "全部")}
    crash = {k: [] for k in G}
    start = next(i for i, x in enumerate(D) if x >= "2016-01-01")
    for t in range(start, len(D) - HOLD, HOLD):
        win = D[t - 250:t + 1]
        mr = [tw[win[i]] / tw[win[i - 1]] - 1 for i in range(1, len(win))]
        mv = stt.pvariance(mr)
        rows = []
        for sid, m in S.items():
            if not all(x in m for x in win) or D[t + HOLD] not in m:
                continue
            sr = [m[win[i]][0] / m[win[i - 1]][0] - 1 for i in range(1, len(win))]
            mm, sm = stt.mean(mr), stt.mean(sr)
            beta = sum((a - mm) * (b - sm) for a, b in zip(mr, sr)) / len(mr) / mv
            vol = stt.mean(m[x][1] * m[x][0] for x in win[-60:])  # 成交金額
            rows.append((beta, vol, m[D[t + HOLD]][0] / m[D[t]][0] - 1))
        if len(rows) < 60:
            continue
        rows.sort()
        n = len(rows)
        vmed = stt.median(r[1] for r in rows)
        grp = {"A 低 Beta": rows[:n // 5], "B 低 Beta＋高成交量": [r for r in rows[:n // 3] if r[1] >= vmed],
               "C 高 Beta": rows[-n // 5:], "全部": rows}
        hi = max(tw[x] for x in D[t - 59:t + 1])
        in_crash = tw[D[t]] / hi - 1 <= -0.10
        for k, g in grp.items():
            if g:
                r = stt.mean(z[2] for z in g)
                G[k].append(r)
                if in_crash:
                    crash[k].append(r)
    for k, rs in G.items():
        eq, peak, mdd = 1.0, 1.0, 0.0
        for r in rs:
            eq *= 1 + r
            peak = max(peak, eq)
            mdd = min(mdd, eq / peak - 1)
        print("%s：%d 期，每期平均 %+.2f%%、賺錢 %.0f%%、累計 %+.0f%%、最大跌幅 %.0f%%、最差一期 %+.1f%%" % (
            k, len(rs), stt.mean(rs) * 100, sum(r > 0 for r in rs) / len(rs) * 100, (eq - 1) * 100, mdd * 100, min(rs) * 100))
    print("\n大跌中買進（加權指數離 60 日高點 −10% 以上）：")
    for k, rs in crash.items():
        if rs:
            print("　%s：%d 次，20 天平均 %+.1f%%、賺錢 %.0f%%" % (k, len(rs), stt.mean(rs) * 100, sum(r > 0 for r in rs) / len(rs) * 100))


if __name__ == "__main__":
    main(sys.argv[1])
