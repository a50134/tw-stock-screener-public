"""
2026-11-20 錢線百分百（台股一週跌 7,641 點、17%）博傑老師的「跌深反彈」挑股法回測
股票：網頁資料（site-data）市值前 150 檔，Yahoo 約 11 年日K（還原權息、含成交量）；加權指數 ^TWII
訊號（同一檔 20 天內只算一次，隔天開盤買）：
  A 跌深：收盤比 5 日線低 10% 以上，而且比年線（240 日）低 20% 以上
  A＋大盤大跌：同時加權指數 5 天跌 6% 以上（我們的「大跌」定義）
  C A＋當天出量（成交量 ≥ 前 5 天平均 2 倍）＝節目說的「低檔出量才會像樣反彈」
  E A 但沒出量
  F A 之後 10 天內「收盤站回 5 日線」那天才買（節目說第一波彈到 5 日線有壓力）
出場：(1) 跌 8% 停損、否則抱 20 天（順勢規則） (2) 跌 15% 停損、否則抱 60 天（逆勢／抄底規則）
用法：python research/nov20_bt.py data.json
"""
import json
import os
import statistics as stt
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sepa_bt import MA, yahoo  # noqa: E402


def fwd(o, l, c, t, H, stop):
    n = len(c)
    if t + 1 + H >= n:
        return None
    e = o[t + 1]
    for k in range(t + 1, t + 2 + H):
        if l[k] <= e * (1 - stop):
            return min(o[k], e * (1 - stop)) / e - 1 - 0.006
    return c[t + 1 + H] / e - 1 - 0.006


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    U = sorted(((float(x["shares"]) * x["c"][-1], x) for x in d["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"] and x["c"][-1]), key=lambda z: -z[0])[:150]
    tw = {r[0]: r[4] for r in yahoo("%5ETWII")}
    TD = sorted(tw)
    ti = {x: i for i, x in enumerate(TD)}
    K = ["隨便買（每 20 天）", "A 跌深（5 日線 −10%＋年線 −20%）", "A＋大盤 5 天跌 6% 以上", "C A＋當天出量 2 倍", "E A 但沒出量", "F A 後站回 5 日線才買"]
    R = {(k, h): [] for k in K for h in ((20, 0.08), (60, 0.15))}
    yrs = {}
    ok = 0
    for _, x in U:
        rows = yahoo(x["id"] + (".TWO" if x.get("mkt") == "tpex" else ".TW"))
        if len(rows) < 400:
            continue
        ok += 1
        D = [r[0] for r in rows]
        o, h, l, c, v = ([r[i] for r in rows] for i in range(1, 6))
        m = MA(c)
        n = len(c)
        last = {}

        def add(k, t):
            if t - last.get(k, -99) <= 20 or t + 2 >= n:
                return
            last[k] = t
            for hh in ((20, 0.08), (60, 0.15)):
                r = fwd(o, l, c, t, *hh)
                if r is not None:
                    R[(k, hh)].append(r)
                    if hh == (60, 0.15) and k.startswith("A 跌深"):
                        yrs.setdefault(D[t][:4], []).append(r)
        for t in range(250, n - 2):
            if t % 20 == 0:
                add(K[0], t)
            if not (c[t] <= m(5, t) * 0.90 and c[t] <= m(240, t) * 0.80):
                continue
            add(K[1], t)
            i = ti.get(D[t])
            if i is not None and i >= 5 and tw[TD[i]] / tw[TD[i - 5]] - 1 <= -0.06:
                add(K[2], t)
            pv = sum(v[t - 5:t]) / 5
            add(K[3] if pv and v[t] >= 2 * pv else K[4], t)
            f = next((k for k in range(t + 1, min(t + 11, n - 2)) if c[k] > m(5, k)), None)
            if f:
                add(K[5], f)
    print("有資料 %d 檔，期間約 %s～%s\n" % (ok, TD[0], TD[-1]))
    for hh, nm in (((20, 0.08), "跌 8% 停損、否則抱 20 天"), ((60, 0.15), "跌 15% 停損、否則抱 60 天（抄底規則）")):
        print("【%s】" % nm)
        for k in K:
            L = R[(k, hh)]
            if not L:
                print("・%s：0 筆" % k)
                continue
            print("・%-26s %5d 筆｜勝率 %3.0f%%｜平均 %+5.1f%%｜中位數 %+5.1f%%｜最差 %+4.0f%%" % (
                k, len(L), 100 * sum(r > 0 for r in L) / len(L), 100 * stt.mean(L), 100 * stt.median(L), 100 * min(L)))
        print()
    print("A 跌深（抱 60 天）逐年：" + "、".join("%s %.0f%%／%+.1f%%(%d)" % (y, 100 * sum(r > 0 for r in v) / len(v), 100 * stt.mean(v), len(v)) for y, v in sorted(yrs.items())))


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if a.endswith(".json")), "data.json"))
