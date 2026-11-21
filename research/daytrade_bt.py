"""
2026-11-21 使用者要的「當沖」：先回測台股 5 分 K（Yahoo 最多 60 天），看常見當沖買法有沒有優勢，再決定要不要做盤中掃描／進場／出場提醒
股票：網頁資料（site-data）市值前 100 檔；只做多；成本：手續費約 2.8 折來回 0.08%＋當沖證交稅 0.15% ≈ 0.25%
台股時間 09:00～13:30（最後一根 13:25），收盤前 13:25 一定賣掉（當沖）
買法：
  ORB15 開盤 15 分鐘區間（09:00～09:15）的高點，10:30 前第一根 5 分 K 收盤突破 → 那根收盤價買；停損＝區間中間；目標 1R（或 2R）
  ORB15＋日線多頭：昨天收盤在月線上、月線往上
  ORB15＋爆量：突破那根量 ≥ 前面幾根平均 2 倍
  跳空跌深反彈：開盤比昨收低 3% 以上，09:15 前出現收盤站上開盤價的紅 K → 買；停損當天目前最低；目標 1R
  對照：每天 09:15 隨便買、停損 1%、目標 1%
用法：python research/daytrade_bt.py data.json
"""
import datetime as dt
import json
import statistics as stt
import sys
import time

import requests

UA = {"User-Agent": "Mozilla/5.0"}
COST = 0.0025


def bars5(sym):
    for k, host in enumerate(("query1", "query2", "query1")):
        try:
            r = requests.get("https://%s.finance.yahoo.com/v8/finance/chart/%s?range=60d&interval=5m" % (host, sym), headers=UA, timeout=30)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            off = res["meta"].get("gmtoffset", 28800)
            q = res["indicators"]["quote"][0]
            days = {}
            for i, ts in enumerate(res.get("timestamp") or []):
                o, h, l, c, v = (q[x][i] for x in ("open", "high", "low", "close", "volume"))
                if None in (o, h, l, c):
                    continue
                t = dt.datetime.utcfromtimestamp(ts + off)
                m = t.hour * 60 + t.minute
                if 540 <= m <= 805:  # 09:00～13:25
                    days.setdefault(t.strftime("%Y-%m-%d"), []).append((m, o, h, l, c, v or 0))
            return {d: sorted(b) for d, b in days.items() if len(b) >= 50}
        except Exception:
            time.sleep(1 + 2 * k)
    return {}


def daily(sym):
    try:
        r = requests.get("https://query1.finance.yahoo.com/v8/finance/chart/%s?range=1y&interval=1d" % sym, headers=UA, timeout=30)
        res = r.json()["chart"]["result"][0]
        off = res["meta"].get("gmtoffset", 28800)
        c = res["indicators"]["quote"][0]["close"]
        return {dt.datetime.utcfromtimestamp(ts + off).strftime("%Y-%m-%d"): x for ts, x in zip(res["timestamp"], c) if x}
    except Exception:
        return {}


def run_trade(B, i, e, stop, tgt):
    """從第 i 根之後開始看；同一根兩邊都碰到算停損；13:25 那根收盤賣"""
    risk = e - stop
    for m, o, h, l, c, v in B[i + 1:]:
        if l <= stop:
            px = min(o, stop)
            return px / e - 1 - COST, (px - e) / risk
        if h >= tgt:
            px = max(o, tgt)
            return px / e - 1 - COST, (px - e) / risk
    c = B[-1][4]
    return c / e - 1 - COST, (c - e) / risk


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    U = sorted(((float(x["shares"]) * x["c"][-1], x) for x in d["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"] and x["c"][-1]), key=lambda z: -z[0])[:100]
    K = ["ORB15 1R", "ORB15 2R", "ORB15＋日線多頭 1R", "ORB15＋爆量 1R", "跳空跌 3% 後收紅 1R", "對照：09:15 隨便買 ±1%"]
    R = {k: [] for k in K}
    ok = 0
    for _, x in U:
        sym = x["id"] + (".TWO" if x.get("mkt") == "tpex" else ".TW")
        days = bars5(sym)
        if len(days) < 20:
            continue
        ok += 1
        dc = daily(sym)
        dd = sorted(dc)
        for day, B in sorted(days.items()):
            prev = [k for k in dd if k < day]
            if len(prev) < 21:
                continue
            pc = dc[prev[-1]]
            m20 = sum(dc[k] for k in prev[-20:]) / 20
            m20y = sum(dc[k] for k in prev[-21:-1]) / 20
            up = pc > m20 and m20 > m20y
            first = [b for b in B if b[0] < 555]
            if len(first) < 3:
                continue
            hi, lo = max(b[2] for b in first), min(b[3] for b in first)
            mid = (hi + lo) / 2
            i15 = next(i for i, b in enumerate(B) if b[0] >= 555)
            # 對照
            e = B[i15][1]
            R[K[5]].append(run_trade(B, i15 - 1, e, e * 0.99, e * 1.01))
            # ORB
            j = next((i for i in range(i15, len(B)) if B[i][0] <= 630 and B[i][4] > hi), None)
            if j is not None and B[j][4] > mid:
                e = B[j][4]
                r1 = run_trade(B, j, e, mid, e + (e - mid))
                R[K[0]].append(r1)
                R[K[1]].append(run_trade(B, j, e, mid, e + 2 * (e - mid)))
                if up:
                    R[K[2]].append(r1)
                av = stt.mean(b[5] for b in B[max(0, j - 6):j]) if j else 0
                if av and B[j][5] >= 2 * av:
                    R[K[3]].append(r1)
            # 跳空跌深反彈
            if B[0][1] <= pc * 0.97:
                g = next((i for i in range(0, i15) if B[i][4] > B[0][1] and B[i][4] > B[i][1]), None)
                if g is not None:
                    e = B[g][4]
                    lw = min(b[3] for b in B[:g + 1])
                    if e > lw:
                        R[K[4]].append(run_trade(B, g, e, lw, e + (e - lw)))
    print("有 5 分 K 資料 %d 檔（Yahoo 最多 60 天）\n" % ok)
    for k in K:
        L = R[k]
        if not L:
            print("・%s：0 筆" % k)
            continue
        ret = [a for a, _ in L]
        rr = [b for _, b in L]
        print("・%-22s %5d 筆｜勝率 %3.0f%%｜每筆平均 %+.2f%%（已扣成本 0.25%%）｜平均 %+.2fR｜最差 %+.1f%%" % (
            k, len(L), 100 * sum(a > 0 for a in ret) / len(ret), 100 * stt.mean(ret), stt.mean(rr), 100 * min(ret)))


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if a.endswith(".json")), "data.json"))
