"""
D：國安基金進場後的買點比較（2026-11-13 使用者同意做回測）
錢線 11/11：拉回到「國安基金進場那天的高點」（這次 42,349）長線一定會過 → 拉回到那裡就是買點。
我們現在用：從反彈高點回跌 6%（0050 約 97 元）。比較 9 次國安基金（2000～2025）：
  甲. 進場日收盤就買
  乙. 現在的規則：進場後反彈的最高點回跌 6% 才買（沒破進場前低點）
  丙. 拉回到進場日的盤中高點才買（之前要先漲上去過）
  丁. 乙、丙哪個先到就買
看 40 個交易日內有沒有買到、買到後 60／120 天的報酬、之後最多再跌多少、跟進場日收盤買比。
資料：Yahoo 加權指數（含盤中高低），GitHub Actions 上跑。用法：python research/rescue_entry_bt.py
"""
import datetime as dt
import os
import statistics as st
import sys

import requests

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import rescue_study as rs

UA = {"User-Agent": "Mozilla/5.0"}


def ohlc(sym):
    for host in ("query1", "query2"):
        try:
            r = requests.get("https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=946684800&period2=%d&interval=1d"
                             % (host, sym, int(dt.datetime.now().timestamp())), headers=UA, timeout=40)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            out = []
            for i, ts in enumerate(res["timestamp"]):
                if q["close"][i]:
                    out.append((dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d"), q["high"][i] or q["close"][i], q["low"][i] or q["close"][i], q["close"][i]))
            return out
        except Exception as e:
            print("  !", sym, host, e, file=sys.stderr)
    return []


def main():
    tw = ohlc("%5ETWII")
    D = [x[0] for x in tw]
    H = [x[1] for x in tw]
    L = [x[2] for x in tw]
    C = [x[3] for x in tw]
    pct = lambda x: "—" if x is None else "%+.1f%%" % (x * 100)
    res = {k: [] for k in "甲乙丙丁"}
    print("每次國安基金：進場日｜進場日收盤｜進場日高點｜之前低點｜甲 60 天｜乙 何時買到、價位、60 天｜丙 何時買到、價位、60 天")
    for ev in rs.EVENTS[:-1]:
        i = next((k for k, d in enumerate(D) if d >= ev), None)
        if i is None or i < 10 or i + 130 >= len(D):
            continue
        lo0 = min(C[i - 10:i + 1])
        hi_e = H[i]
        buys = {"甲": (i, C[i])}
        pk, b, c_ = C[i], None, None
        above = False
        for t in range(i + 1, min(i + 41, len(C))):
            if C[t] < lo0:  # 第二隻腳：乙、丙都不買
                break
            pk = max(pk, C[t])
            if b is None and C[t] <= pk * 0.94:
                b = (t, C[t])
            if C[t] > hi_e * 1.02:
                above = True
            if c_ is None and above and L[t] <= hi_e:
                c_ = (t, min(hi_e, H[t]))
        if b:
            buys["乙"] = b
        if c_:
            buys["丙"] = c_
        if b or c_:
            buys["丁"] = min((x for x in (b, c_) if x), key=lambda x: x[0])
        row = []
        for k in "甲乙丙丁":
            if k not in buys:
                res[k].append(None)
                row.append("%s 沒買到" % k)
                continue
            t, p = buys[k]
            r60 = C[t + 60] / p - 1 if t + 60 < len(C) else None
            r120 = C[t + 120] / p - 1 if t + 120 < len(C) else None
            dd = min(L[t:t + 61]) / p - 1
            vs = p / C[i] - 1
            res[k].append((r60, r120, dd, vs, t - i))
            row.append("%s 第 %d 天 %.0f（比進場日收盤 %s）60 天 %s" % (k, t - i, p, pct(vs), pct(r60)))
        print("・%s｜收 %.0f｜高 %.0f｜前低 %.0f｜%s" % (ev, C[i], hi_e, lo0, "｜".join(row)))
    print("\n彙總（9 次）")
    for k, nm in (("甲", "進場日收盤就買"), ("乙", "反彈高點回跌 6%（現在的規則）"), ("丙", "拉回到進場日高點"), ("丁", "乙丙先到的")):
        got = [x for x in res[k] if x]
        if not got:
            print("・%s：都沒買到" % nm)
            continue
        print("・%s：買到 %d/%d 次｜平均第 %.0f 天買｜買價比進場日收盤 %s｜60 天平均 %s（賺 %d 次）｜120 天平均 %s｜買後 60 天內最多再跌平均 %s、最慘 %s" % (
            nm, len(got), len(res[k]), st.mean(x[4] for x in got), pct(st.mean(x[3] for x in got)),
            pct(st.mean(x[0] for x in got if x[0] is not None)), sum(1 for x in got if x[0] and x[0] > 0),
            pct(st.mean(x[1] for x in got if x[1] is not None)), pct(st.mean(x[2] for x in got)), pct(min(x[2] for x in got))))


if __name__ == "__main__":
    main()
