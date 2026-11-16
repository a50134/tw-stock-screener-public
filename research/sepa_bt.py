"""
2026-11-16 使用者貼的 Mark Minervini SEPA（趨勢樣板＋VCP 波動收縮＋帶量突破＋嚴格停損）回測
股票：網頁資料（site-data）市值前 150 檔，Yahoo 約 11 年日K（還原權息、含成交量）；加權指數 ^TWII
（現在的大公司，有倖存者偏差；看「各版本 vs 對照組」的差別比較準）

進場（訊號當天收盤確認，隔天開盤買）：
  趨勢樣板：收盤 > 50／150／200 日線、50 > 150 > 200、200 日線比 20 天前高、收盤 ≥ 52 週低 ×1.3、在 52 週高 25% 內
  VCP：近 60 天分 3 段（各 20 天），每段高低差 d1 > d2 > d3，d1 ≥ 10%、d3 ≤ 10%；樞紐＝最後一段最高價
  量縮：前一天的 10 日均量 < 50 日均量 ×0.7
  突破：收盤 > 樞紐，當日量 > 50 日均量 ×1.5
  相對強度：250 日漲幅 > 加權指數；大盤濾網：加權指數 > 50 日線
出場：停損＝min(進場 ×0.93, 最後一段低點)；賺到 1R 停損拉到成本；賺到 2R 先賣一半；剩下跌破 50 日線收盤隔天開盤賣（最多抱 250 天）
成本：來回 0.6%
用法：python research/sepa_bt.py data.json
"""
import datetime as dt
import json
import statistics as stt
import sys
import time

import requests

UA = {"User-Agent": "Mozilla/5.0"}


def yahoo(sym, years=11):
    for k, host in enumerate(("query1", "query2", "query1", "query2")):
        try:
            r = requests.get("https://%s.finance.yahoo.com/v8/finance/chart/%s?range=%dy&interval=1d&includeAdjustedClose=true" % (host, sym, years), headers=UA, timeout=30)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or q["close"]
            out = []
            for i, ts in enumerate(res.get("timestamp") or []):
                c = q["close"][i]
                if not c or not adj[i] or q["open"][i] is None or q["high"][i] is None or q["low"][i] is None:
                    continue
                f = adj[i] / c
                out.append((dt.datetime.utcfromtimestamp(ts).strftime("%Y-%m-%d"), q["open"][i] * f, q["high"][i] * f, q["low"][i] * f, adj[i], (q["volume"][i] or 0) / 1000))
            return out
        except Exception:
            time.sleep(1 + 2 * k)
    return []


def pct(x):
    return "—" if x is None else "%+.1f%%" % (x * 100)


class MA:
    def __init__(self, a):
        self.cs = [0]
        for v in a:
            self.cs.append(self.cs[-1] + v)

    def __call__(self, k, t):
        return (self.cs[t + 1] - self.cs[t + 1 - k]) / k if t >= k - 1 else None


def trade(D, o, h, l, c, ma50, t, stop):
    """t＝訊號日；回傳 (報酬, R 倍數, 抱幾天, 結果)"""
    n = len(c)
    if t + 2 >= n:
        return None
    e = o[t + 1]
    if stop >= e:  # 跳空開高太多，停損比進場高 → 改用 -7%
        stop = e * 0.93
    R = e - stop
    st, half, out, k = stop, 0.0, [], t + 1
    for k in range(t + 1, min(n, t + 252)):
        if l[k] <= st:  # 停損／保本出場
            px = min(o[k], st)
            out.append((1 - half, px))
            break
        if c[k] >= e + R and st < e:
            st = e  # 賺到 1R：停損拉到成本
        if half == 0 and h[k] >= e + 2 * R:
            out.append((0.5, e + 2 * R))  # 賺到 2R：先賣一半
            half = 0.5
        m = ma50(50, k)
        if m and c[k] < m and k + 1 < n:
            out.append((1 - half, o[k + 1]))  # 跌破 50 日線，隔天開盤賣
            k += 1
            break
    else:
        out.append((1 - half, c[k]))
    if sum(w for w, _ in out) < 0.999:
        out.append((1 - sum(w for w, _ in out), c[k]))
    ret = sum(w * (px / e - 1) for w, px in out) - 0.006
    return ret, ret * e / R, k - t, D[t]


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    U = sorted(((float(x["shares"]) * x["c"][-1], x) for x in d["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"] and x["c"][-1]), key=lambda z: -z[0])[:150]
    tw = {r[0]: r[4] for r in yahoo("%5ETWII")}
    TD = sorted(tw)
    twc = [tw[x] for x in TD]
    twma = MA(twc)
    tix = {x: i for i, x in enumerate(TD)}
    V = {k: [] for k in ("A 只看趨勢樣板＋帶量突破 20 日高", "B 趨勢樣板＋VCP＋量縮＋帶量突破（不加濾網）",
                         "C 完整 SEPA（B＋相對強度＋大盤在 50 日線上）", "D 完整 SEPA＋大盤改看 200 日線",
                         "E 對照：同樣出場法，任何一天買（每 20 天抽一次）")}
    ok = 0
    for _, x in U:
        rows = yahoo(x["id"] + (".TWO" if x.get("mkt") == "tpex" else ".TW"))
        if len(rows) < 400:
            continue
        ok += 1
        D = [r[0] for r in rows]
        o, h, l, c, v = ([r[i] for r in rows] for i in range(1, 6))
        m, mv = MA(c), MA(v)
        n = len(c)
        busy = busyA = -1
        for t in range(260, n - 2):
            if t % 20 == 0 and t > busy:
                r = trade(D, o, h, l, c, m, t, o[t + 1] * 0.93 if t + 1 < n else c[t] * 0.93)
                if r:
                    V["E 對照：同樣出場法，任何一天買（每 20 天抽一次）"].append(r)
            m50, m150, m200 = m(50, t), m(150, t), m(200, t)
            if not (c[t] > m50 > m150 > m200 and c[t] > m150 and m200 > m(200, t - 20)):
                continue
            lo52, hi52 = min(l[t - 251:t + 1]), max(h[t - 251:t + 1])
            if not (c[t] >= lo52 * 1.3 and c[t] >= hi52 * 0.75):
                continue
            v50 = mv(50, t)
            if not v50 or v[t] <= v50 * 1.5:
                continue
            if t <= busy:  # 同一檔持有中不重複進場
                continue
            hi20 = max(h[t - 20:t])
            if c[t] > hi20 and t > busyA:
                r = trade(D, o, h, l, c, m, t, min(o[t + 1] * 0.93, min(l[t - 20:t])) if t + 1 < n else 0)
                if r:
                    busyA = t + r[2]
                    V["A 只看趨勢樣板＋帶量突破 20 日高"].append(r)
            seg = [(max(h[a:a + 20]), min(l[a:a + 20])) for a in (t - 60, t - 40, t - 20)]
            dd = [1 - lo / hi for hi, lo in seg]
            if not (dd[0] >= 0.10 and dd[0] > dd[1] > dd[2] and dd[2] <= 0.10):
                continue
            pivot = seg[2][0]
            if not (c[t] > pivot and mv(10, t - 1) < mv(50, t - 1) * 0.7):
                continue
            stop = min(o[t + 1] * 0.93, seg[2][1]) if t + 1 < n else 0
            r = trade(D, o, h, l, c, m, t, stop)
            if not r:
                continue
            busy = t + r[2]
            V["B 趨勢樣板＋VCP＋量縮＋帶量突破（不加濾網）"].append(r)
            i = tix.get(D[t])
            if i is None or i < 250:
                continue
            rs = c[t] / c[t - 250] - 1 > twc[i] / twc[i - 250] - 1
            if rs and twc[i] > twma(50, i):
                V["C 完整 SEPA（B＋相對強度＋大盤在 50 日線上）"].append(r)
            if rs and twc[i] > twma(200, i):
                V["D 完整 SEPA＋大盤改看 200 日線"].append(r)
    print("有資料 %d 檔，期間約 %s～%s\n" % (ok, TD[0], TD[-1]))
    for k, L in V.items():
        if not L:
            print("・%s：0 筆" % k)
            continue
        rets = [r[0] for r in L]
        Rs = [r[1] for r in L]
        yrs = {}
        for r in L:
            yrs.setdefault(r[3][:4], []).append(r[0])
        print("・%s\n    %d 筆｜勝率 %.0f%%｜平均 %s｜中位數 %s｜平均 %.2fR｜平均抱 %d 天｜最好 %s｜最差 %s" % (
            k, len(L), 100 * sum(x > 0 for x in rets) / len(L), pct(stt.mean(rets)), pct(stt.median(rets)), stt.mean(Rs),
            stt.mean(r[2] for r in L), pct(max(rets)), pct(min(rets))))
        wins, loss = [x for x in rets if x > 0], [x for x in rets if x <= 0]
        if wins and loss:
            print("    賺的平均 %s、賠的平均 %s（賺賠比 %.1f）" % (pct(stt.mean(wins)), pct(stt.mean(loss)), stt.mean(wins) / -stt.mean(loss)))
        print("    逐年平均：" + "、".join("%s %s(%d)" % (y, pct(stt.mean(v)), len(v)) for y, v in sorted(yrs.items())))
    # 1% 風險部位模擬（完整 SEPA C）：每筆最多虧資金 1%、單筆上限 25%，依訊號日期順序、不管同時持有幾檔
    L = sorted(V["C 完整 SEPA（B＋相對強度＋大盤在 50 日線上）"], key=lambda r: r[3])
    if L:
        eq = 1.0
        for ret, R, _, _ in L:
            size = min(0.25, 0.01 / (ret / R if R else 0.07) if R and ret / R > 0 else 0.25)
            eq *= 1 + size * ret
        print("\n完整 SEPA 用「每筆最多虧 1%%、單筆最多 25%%」下注，%d 筆依序做完：資金 ×%.2f（簡化：沒算同時持有）" % (len(L), eq))


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if a.endswith(".json")), "data.json"))
