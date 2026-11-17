"""
2026-11-17 使用者貼的脆友策略回測：MACD 柱狀體翻正＋布林通道開口放大＋站上上揚 20 日線（三個同時成立）
股票：網頁資料（site-data）市值前 100 檔，Yahoo 約 11 年日K（還原權息、含成交量）
進場（訊號當天收盤確認，隔天開盤買）：
  MACD(12,26,9)，價格用加權收盤價 (H+L+2C)/4；柱狀體今天 > 0、昨天 <= 0
  布林(20, 2 倍標準差)：帶寬 (上−下)/中 比昨天大，且上軌比昨天高、下軌比昨天低
  收盤 > 20 日線，且 20 日線比昨天高；成交量 >= 500 張
出場（比較 3 種）：
  A 使用者的：收盤跌破 20 日線、連 3 天站不回，第 3 天收盤後隔天開盤賣（最多抱 250 天）
  B 我們每晚策略的回測方式：跌 8% 停損，否則抱 20 天
  C A＋跌 8% 停損
成本：來回 0.6%；同一檔持有中不重複進場
用法：python research/macd_boll_bt.py data.json
"""
import json
import os
import statistics as stt
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sepa_bt import MA, yahoo  # noqa: E402


def ema(a, k):
    out, e = [], None
    for x in a:
        e = x if e is None else x * 2 / (k + 1) + e * (1 - 2 / (k + 1))
        out.append(e)
    return out


def signals(o, h, l, c, v):
    n = len(c)
    wc = [(h[i] + l[i] + 2 * c[i]) / 4 for i in range(n)]
    dif = [a - b for a, b in zip(ema(wc, 12), ema(wc, 26))]
    hist = [a - b for a, b in zip(dif, ema(dif, 9))]
    m = MA(c)
    up, lo, bw = [None] * n, [None] * n, [None] * n
    for t in range(19, n):
        w = c[t - 19:t + 1]
        mu = sum(w) / 20
        sd = (sum((x - mu) ** 2 for x in w) / 20) ** 0.5
        up[t], lo[t], bw[t] = mu + 2 * sd, mu - 2 * sd, 4 * sd / mu
    S = []
    for t in range(40, n - 1):
        if (hist[t] > 0 >= hist[t - 1] and bw[t] > bw[t - 1] and up[t] > up[t - 1] and lo[t] < lo[t - 1]
                and c[t] > m(20, t) and m(20, t) > m(20, t - 1) and v[t] >= 500):
            S.append(t)
    return S, m


def exit_user(o, l, c, m, t, stop=None):
    n = len(c)
    e, below = o[t + 1], 0
    for k in range(t + 1, min(n, t + 251)):
        if stop and l[k] <= e * (1 - stop):
            return min(o[k], e * (1 - stop)) / e - 1 - 0.006, k - t
        below = below + 1 if c[k] < m(20, k) else 0
        if below >= 3 and k + 1 < n:
            return o[k + 1] / e - 1 - 0.006, k + 1 - t
    k = min(n - 1, t + 250)
    return c[k] / e - 1 - 0.006, k - t


def exit_20(o, l, c, t, H=20, stop=0.08):
    if t + 1 + H >= len(c):
        return None
    e = o[t + 1]
    for k in range(t + 1, t + 2 + H):
        if l[k] <= e * (1 - stop):
            return min(o[k], e * (1 - stop)) / e - 1 - 0.006, k - t
    return c[t + 1 + H] / e - 1 - 0.006, H


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    U = sorted(((float(x["shares"]) * x["c"][-1], x) for x in d["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"] and x["c"][-1]), key=lambda z: -z[0])[:100]
    R = {k: [] for k in ("A 使用者出場：跌破月線 3 天站不回", "B 跌 8% 停損、否則抱 20 天", "C A＋跌 8% 停損", "對照：隨便買（A 出場法，每 20 天抽一次）", "對照：隨便買（B 出場法）")}
    ok = 0
    for _, x in U:
        rows = yahoo(x["id"] + (".TWO" if x.get("mkt") == "tpex" else ".TW"))
        if len(rows) < 300:
            continue
        ok += 1
        D = [r[0] for r in rows]
        o, h, l, c, v = ([r[i] for r in rows] for i in range(1, 6))
        S, m = signals(o, h, l, c, v)
        n = len(c)
        busy = -1
        for t in S:
            if t <= busy or t + 2 >= n:
                continue
            a = exit_user(o, l, c, m, t)
            busy = t + a[1]
            R["A 使用者出場：跌破月線 3 天站不回"].append((D[t], *a))
            R["C A＋跌 8% 停損"].append((D[t], *exit_user(o, l, c, m, t, 0.08)))
            b = exit_20(o, l, c, t)
            if b:
                R["B 跌 8% 停損、否則抱 20 天"].append((D[t], *b))
        for t in range(40, n - 2, 20):
            R["對照：隨便買（A 出場法，每 20 天抽一次）"].append((D[t], *exit_user(o, l, c, m, t)))
            b = exit_20(o, l, c, t)
            if b:
                R["對照：隨便買（B 出場法）"].append((D[t], *b))
    print("有資料 %d 檔（市值前 100）\n" % ok)
    for k, L in R.items():
        if not L:
            print("・%s：0 筆" % k)
            continue
        x = [r[1] for r in L]
        w, lo_ = [r for r in x if r > 0], [r for r in x if r <= 0]
        yrs = {}
        for dd, r, _ in L:
            yrs.setdefault(dd[:4], []).append(r)
        print("・%s\n    %d 筆｜勝率 %.0f%%｜平均 %+.1f%%｜中位數 %+.1f%%｜平均抱 %d 天｜賺的平均 %+.1f%%、賠的平均 %+.1f%%｜獲利因子 %.2f" % (
            k, len(x), 100 * len(w) / len(x), 100 * stt.mean(x), 100 * stt.median(x), stt.mean(r[2] for r in L),
            100 * stt.mean(w) if w else 0, 100 * stt.mean(lo_) if lo_ else 0, (sum(w) / -sum(lo_)) if lo_ else 99))
        print("    逐年勝率／平均：" + "、".join("%s %.0f%%／%+.1f%%(%d)" % (y, 100 * sum(r > 0 for r in v) / len(v), 100 * stt.mean(v), len(v)) for y, v in sorted(yrs.items())))


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if a.endswith(".json")), "data.json"))
