"""
2026-11-16 使用者貼的「常見技術分析價格型態（8 大類 16 種）」回測：每種型態在台股出現後的勝率
股票：網頁資料（site-data）市值前 150 檔，Yahoo 約 11 年日K（還原權息、含成交量）
（現在的大公司，有倖存者偏差；看「型態 vs 隨便買」的差別比較準）

轉折點：前後 3 天最高（最低）的那根＝高點（低點），要過 3 天才看得到（不偷看未來）。看近 60 天的轉折點。
偏多型態（收盤突破那天算訊號，隔天開盤買）：
  1 上升三角形：近 2 個高點差 2% 內（水平壓力）、低點墊高 ≥2%，收盤突破壓力
  3 對稱三角形：高點降低、低點墊高，收盤突破兩高點連線
  4 箱型向上突破：≥2 個高點差 3% 內、≥2 個低點差 3% 內、箱子高度 5～25%，收盤突破箱頂
  6／14 多頭旗形／三角旗：前 5～25 天內 15 天漲 ≥20%（旗桿），之後整理 ≤ 旗桿漲幅一半，收盤突破整理區高點
  9 下降楔形：高點、低點都降低且收斂，收盤突破兩高點連線
  10 雙底 W：近 60 天兩個低點差 3% 內、相隔 ≥10 天，收盤突破中間高點（頸線）
  12 頭肩底：三個低點、中間最低（比兩肩低 ≥3%）、兩肩差 5% 內，收盤突破頸線
  16a 下降趨勢線突破：兩個高點降低，收盤由下往上穿過連線
偏空型態（跌破那天算訊號，看之後會不會跌）：2 下降三角形、5 箱型跌破、7／15 空頭旗形／三角旗、8 上升楔形、11 雙頂 M、13 頭肩頂、16b 上升趨勢線跌破
出場：跌 8% 停損，否則抱 20 天（我們每晚策略的回測方式）；也看抱 60 天；成本來回 0.6%
「＋量」：突破當天成交量 > 50 日均量 ×1.5
用法：python research/pattern_bt.py data.json
"""
import json
import os
import statistics as stt
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sepa_bt import MA, yahoo  # 同一支 Yahoo 抓法（含成交量）

K = 3
LB = 60


def pct(x):
    return "—" if x is None else "%+.1f%%" % (x * 100)


def fwd(o, l, c, t, H, stop=0.08):
    n = len(c)
    if t + 1 + H >= n:
        return None
    e = o[t + 1]
    for u in range(t + 1, t + 2 + H):
        if l[u] <= e * (1 - stop):
            return min(o[u], e * (1 - stop)) / e - 1 - 0.006
    return c[t + 1 + H] / e - 1 - 0.006


def raw(c, t, H):
    return c[t + H] / c[t] - 1 if t + H < len(c) else None


def line(p1, p2, t):
    (i1, y1), (i2, y2) = p1, p2
    return y1 + (y2 - y1) * (t - i1) / (i2 - i1)


def detect(o, h, l, c, v, ph, pl, mv, t):
    """回傳今天出現的型態代號集合"""
    out = set()
    H = [(i, h[i]) for i in range(t - LB, t - K + 1) if ph[i]]
    L = [(i, l[i]) for i in range(t - LB, t - K + 1) if pl[i]]
    up = lambda lv: c[t] > lv * 1.005 and c[t - 1] <= lv * 1.005
    dn = lambda lv: c[t] < lv * 0.995 and c[t - 1] >= lv * 0.995
    if len(H) >= 2 and len(L) >= 2:
        (a, ha), (b, hb) = H[-2], H[-1]
        (x, la), (y, lb) = L[-2], L[-1]
        R, S = max(ha, hb), min(la, lb)
        flatH, flatL = abs(ha / hb - 1) <= 0.02, abs(la / lb - 1) <= 0.02
        riseL, fallH = lb >= la * 1.02, hb <= ha * 0.98
        fallL, riseH = lb <= la * 0.98, hb >= ha * 1.02
        hl, ll = line(H[-2], H[-1], t), line(L[-2], L[-1], t)
        if flatH and riseL and up(R):
            out.add("1")
        if fallH and riseL and hl > ll and up(hl):
            out.add("3")
        if fallH and fallL and (ha - hb) / (b - a) > (la - lb) / (y - x) and hl > ll and up(hl):
            out.add("9")
        if flatL and fallH and dn(S):
            out.add("2")
        if riseH and riseL and (lb - la) / (y - x) > (hb - ha) / (b - a) and hl > ll and dn(ll):
            out.add("8")
        boxH = [p for _, p in H if p >= R * 0.97]
        boxL = [p for _, p in L if p <= S * 1.03]
        if len(boxH) >= 2 and len(boxL) >= 2 and 0.05 <= R / S - 1 <= 0.25 and min(i for i, _ in H + L) < t - 20:
            if up(R):
                out.add("4")
            if dn(S):
                out.add("5")
        if fallH and up(hl):
            out.add("16a")
        if riseL and dn(ll):
            out.add("16b")
    # 雙底／雙頂、頭肩
    if len(L) >= 2:
        (x, la), (y, lb) = L[-2], L[-1]
        if abs(la / lb - 1) <= 0.03 and y - x >= 10:
            neck = max(h[x:y + 1])
            if neck >= max(la, lb) * 1.05 and up(neck):
                out.add("10")
    if len(H) >= 2:
        (a, ha), (b, hb) = H[-2], H[-1]
        if abs(ha / hb - 1) <= 0.03 and b - a >= 10:
            neck = min(l[a:b + 1])
            if neck <= min(ha, hb) * 0.95 and dn(neck):
                out.add("11")
    if len(L) >= 3:
        (p, l1), (q, l2), (r, l3) = L[-3:]
        if l2 <= min(l1, l3) * 0.97 and abs(l1 / l3 - 1) <= 0.05:
            neck = max(max(h[p:q + 1]), max(h[q:r + 1]))
            if up(neck):
                out.add("12")
    if len(H) >= 3:
        (p, h1), (q, h2), (r, h3) = H[-3:]
        if h2 >= max(h1, h3) * 1.03 and abs(h1 / h3 - 1) <= 0.05:
            neck = min(min(l[p:q + 1]), min(l[q:r + 1]))
            if dn(neck):
                out.add("13")
    # 旗形／三角旗：旗桿在 5～25 天前結束
    for g in range(5, 26):
        e = t - g
        s = e - 15
        if s < 0:
            break
        pole = c[e] / c[s] - 1
        if pole >= 0.20 and h[e] >= max(h[s:t]) * 0.999:
            top, bot = max(h[e:t]), min(l[e:t])
            if (c[e] - bot) <= 0.5 * (c[e] - c[s]) and up(top):
                out.add("6")
            break
        if pole <= -0.20 and l[e] <= min(l[s:t]) * 1.001:
            top, bot = max(h[e:t]), min(l[e:t])
            if (top - c[e]) <= 0.5 * (c[s] - c[e]) and dn(bot):
                out.add("7")
            break
    return out


NAMES = {"1": "1 上升三角形", "3": "3 對稱三角形（向上突破）", "4": "4 箱型向上突破", "6": "6／14 多頭旗形／三角旗", "9": "9 下降楔形",
         "10": "10 雙底 W", "12": "12 頭肩底", "16a": "16 下降趨勢線向上突破",
         "2": "2 下降三角形", "5": "5 箱型向下跌破", "7": "7／15 空頭旗形／三角旗", "8": "8 上升楔形", "11": "11 雙頂 M",
         "13": "13 頭肩頂", "16b": "16 上升趨勢線向下跌破"}
BULL = ["1", "3", "4", "6", "9", "10", "12", "16a"]
BEAR = ["2", "5", "7", "8", "11", "13", "16b"]


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    U = sorted(((float(x["shares"]) * x["c"][-1], x) for x in d["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"] and x["c"][-1]), key=lambda z: -z[0])[:150]
    R = {}
    ok = 0
    for _, x in U:
        rows = yahoo(x["id"] + (".TWO" if x.get("mkt") == "tpex" else ".TW"))
        if len(rows) < 400:
            continue
        ok += 1
        D = [r[0] for r in rows]
        o, h, l, c, v = ([r[i] for r in rows] for i in range(1, 6))
        n = len(c)
        mv = MA(v)
        ph = [K <= i < n - K and h[i] == max(h[i - K:i + K + 1]) for i in range(n)]
        pl = [K <= i < n - K and l[i] == min(l[i - K:i + K + 1]) for i in range(n)]
        last = {}
        for t in range(LB + 10, n - 2):
            if t % 10 == 0:
                for H_ in (20, 60):
                    R.setdefault(("隨便買", H_, ""), []).append((D[t], fwd(o, l, c, t, H_)))
                R.setdefault(("隨便", 20, "raw"), []).append((D[t], raw(c, t, 20)))
            pats = detect(o, h, l, c, v, ph, pl, mv, t)
            vol = mv(50, t) and v[t] > mv(50, t) * 1.5
            for p in pats:
                if t - last.get(p, -99) <= 20:
                    continue
                last[p] = t
                if p in BULL:
                    for H_ in (20, 60):
                        R.setdefault((p, H_, ""), []).append((D[t], fwd(o, l, c, t, H_)))
                        if vol:
                            R.setdefault((p, H_, "量"), []).append((D[t], fwd(o, l, c, t, H_)))
                else:
                    R.setdefault((p, 20, "raw"), []).append((D[t], raw(c, t, 20)))
                    if vol:
                        R.setdefault((p, 20, "rawv"), []).append((D[t], raw(c, t, 20)))

    def show(name, L, bear=False):
        L = [(dd, r) for dd, r in L if r is not None]
        if not L:
            print("・%-30s 0 筆" % name)
            return
        x = [r for _, r in L]
        yrs = {}
        for dd, r in L:
            yrs.setdefault(dd[:4], []).append(r)
        good = sum((r < 0) if bear else (r > 0) for r in x) / len(x)
        stable = sum((stt.mean(v) < 0) if bear else (stt.mean(v) > 0) for v in yrs.values() if len(v) >= 5)
        tot = sum(len(v) >= 5 for v in yrs.values())
        print("・%-30s %5d 筆｜%s %3.0f%%｜平均 %s｜中位數 %s｜%d/%d 年%s" % (
            name, len(x), "之後下跌" if bear else "勝率", 100 * good, pct(stt.mean(x)), pct(stt.median(x)), stable, tot, "平均是跌的" if bear else "平均賺"))

    print("有資料 %d 檔\n" % ok)
    for H_ in (20, 60):
        print("=" * 60 + "\n【偏多型態】突破隔天開盤買，跌 8%% 停損，否則抱 %d 天\n" % H_)
        show("隨便買（每 10 天抽一次）", R.get(("隨便買", H_, ""), []))
        for p in BULL:
            show(NAMES[p], R.get((p, H_, ""), []))
            show("　└ 突破當天量 >1.5 倍", R.get((p, H_, "量"), []))
        print()
    print("=" * 60 + "\n【偏空型態】跌破後 20 天股價漲跌（沒停損；看會不會真的跌）\n")
    show("隨便一天（之後 20 天）", R.get(("隨便", 20, "raw"), []), True)
    for p in BEAR:
        show(NAMES[p], R.get((p, 20, "raw"), []), True)
        show("　└ 跌破當天量 >1.5 倍", R.get((p, 20, "rawv"), []), True)


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if a.endswith(".json")), "data.json"))
