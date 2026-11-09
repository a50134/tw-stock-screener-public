"""
crash_hist.py - 台股歷史大跌研究：哪些是「系統性衰退」（撿了還會一直跌）、哪些是「暫時性大跌」（撿了很快漲回來）

資料：Yahoo Finance 加權指數 ^TWII（1997 年起）、標普 500、美國 10 年與 3 個月公債殖利率、VIX（不用金鑰；GitHub Actions 上跑）
大跌事件：加權指數 5 日跌 6% 以上（連續大跌算同一波；中間 5 天沒大跌才算新的一波）
結果：大跌隔天買進加權指數，之後 120 個交易日內「又再跌 15% 以上」或「120 天後還在賠」＝撿了會套（系統性）
看哪些指標在大跌當下就分得出來：大跌前在年線（240 日）上嗎、年線往上嗎、美股在 200 日線上嗎、
美債殖利率曲線近一年有沒有倒掛、VIX 多高、離一年高點跌多少

用法：python crash_hist.py   # 印出每次事件與各指標的分辨能力；同時存 crash_hist.json
"""
import datetime as dt
import json
import sys

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}


def yahoo(sym):
    for host in ("query1", "query2"):
        try:
            r = requests.get("https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=852076800&period2=%d&interval=1d" % (host, sym, int(dt.datetime.now().timestamp())), headers=UA, timeout=40)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            q = res["indicators"]["quote"][0]
            out = {}
            for i, ts in enumerate(res.get("timestamp") or []):
                if q["close"][i]:
                    out[dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d")] = (q["low"][i] or q["close"][i], q["close"][i])
            return out
        except Exception as e:
            print("  ! %s 抓取失敗（%s）：%s" % (sym, host, e), file=sys.stderr)
    return {}


def ma(c, n, t):
    return sum(c[t - n + 1:t + 1]) / n if t >= n - 1 else None


def asof(series, day):
    """day 當天或之前最近的值"""
    ks = [k for k in series if k <= day]
    return series[max(ks)][1] if ks else None


def main():
    tw = yahoo("%5ETWII")
    if not tw:
        print("加權指數抓不到")
        return
    spx, tnx, irx, vix = yahoo("%5EGSPC"), yahoo("%5ETNX"), yahoo("%5EIRX"), yahoo("%5EVIX")
    D = sorted(tw)
    c = [tw[d][1] for d in D]
    spx_d = sorted(spx)
    spx_c = [spx[d][1] for d in spx_d]
    print("加權指數 %s～%s，%d 天" % (D[0], D[-1], len(D)))

    ev, last = [], -99
    for t in range(5, len(D)):
        r = c[t] / c[t - 5] - 1
        if r <= -0.06:
            if t - last > 5:
                ev.append(t)
            last = t
    rows = []
    for t in ev:
        if t < 260:
            continue
        pre = t - 6
        e = c[t + 1] if t + 1 < len(c) else None
        f120 = c[t + 121] / e - 1 if t + 121 < len(c) else None
        f60 = c[t + 61] / e - 1 if t + 61 < len(c) else None
        f250 = c[t + 251] / e - 1 if t + 251 < len(c) else None
        dd = min(c[t + 1:t + 122]) / e - 1 if t + 2 < len(c) else None
        m240, m240p = ma(c, 240, pre), ma(c, 240, pre - 20)
        hi = max(c[t - 250:t + 1])
        # 美股 200 日線（大跌前）
        si = max(i for i, d in enumerate(spx_d) if d <= D[pre]) if spx_d and spx_d[0] <= D[pre] else None
        spx_up = spx_c[si] > ma(spx_c, 200, si) if si and si >= 200 else None
        # 殖利率曲線：近 250 個交易日 10 年 − 3 個月 最低值
        curve = None
        if tnx and irx:
            ds = [d for d in sorted(tnx) if D[max(0, t - 250)] <= d <= D[t] and d in irx]
            if ds:
                curve = min(tnx[d][1] - irx[d][1] for d in ds)
        v = asof(vix, D[t]) if vix else None
        bad = None if f120 is None else (dd <= -0.15 or f120 < 0)
        rows.append(dict(d=D[t], r5=c[t] / c[t - 5] - 1, f60=f60, f120=f120, f250=f250, dd=dd, bad=bad,
                         above240=c[pre] > m240, up240=m240 > m240p, spx_up=spx_up, curve=curve, inverted=curve is not None and curve < 0,
                         vix=v, off_hi=c[t] / hi - 1))
    fmt = lambda x: "—" if x is None else "%+.0f%%" % (x * 100)
    print("\n日期        5日跌  60天後 120天後 250天後 之後最多再跌 結果  年線上 年線上揚 美股200日上 殖利率倒掛 VIX 離高點")
    for r in rows:
        print("%s %6s %7s %7s %7s %8s   %s   %s   %s   %s   %s   %4s %6s" % (
            r["d"], fmt(r["r5"]), fmt(r["f60"]), fmt(r["f120"]), fmt(r["f250"]), fmt(r["dd"]),
            "—" if r["bad"] is None else ("套" if r["bad"] else "賺"),
            "是" if r["above240"] else "否", "是" if r["up240"] else "否", "—" if r["spx_up"] is None else ("是" if r["spx_up"] else "否"),
            "—" if r["curve"] is None else ("是" if r["inverted"] else "否"), "—" if r["vix"] is None else "%.0f" % r["vix"], fmt(r["off_hi"])))
    done = [r for r in rows if r["bad"] is not None]
    print("\n共 %d 次大跌（有 120 天後結果的 %d 次），撿了會套的 %d 次" % (len(rows), len(done), sum(r["bad"] for r in done)))
    tests = [
        ("大跌前在年線上", lambda r: r["above240"]),
        ("年線往上", lambda r: r["up240"]),
        ("在年線上且年線往上", lambda r: r["above240"] and r["up240"]),
        ("美股在 200 日線上", lambda r: r["spx_up"]),
        ("近一年殖利率沒倒掛", lambda r: not r["inverted"]),
        ("離一年高點跌不到 20%", lambda r: r["off_hi"] > -0.20),
        ("年線上揚＋美股 200 日上", lambda r: r["up240"] and r["spx_up"]),
        ("年線上揚＋沒倒掛", lambda r: r["up240"] and not r["inverted"]),
        ("美股 200 日上＋沒倒掛", lambda r: r["spx_up"] and not r["inverted"]),
        ("美股 200 日上或沒倒掛", lambda r: r["spx_up"] or not r["inverted"]),
        ("美股 200 日下＋倒掛（系統性警訊）", lambda r: not r["spx_up"] and r["inverted"]),
        ("VIX ≥ 30", lambda r: (r["vix"] or 0) >= 30),
    ]
    print("\n指標成立時 vs 不成立時：撿了會套的比例、120 天後平均報酬")
    for name, f in tests:
        a = [r for r in done if f(r)]
        b = [r for r in done if not f(r)]
        s = lambda L: "%d 次，套 %d 次（%.0f%%），120 天平均 %+.1f%%" % (len(L), sum(r["bad"] for r in L), 100 * sum(r["bad"] for r in L) / len(L), 100 * sum(r["f120"] for r in L) / len(L)) if L else "0 次"
        print("・%s：成立 %s｜不成立 %s" % (name, s(a), s(b)))
    print("\n更嚴格的「系統性」：之後最多再跌 25% 以上")
    for name, f in tests:
        a = [r for r in done if f(r)]
        b = [r for r in done if not f(r)]
        s = lambda L: "%d 次，再跌 25%% 以上 %d 次（%.0f%%）" % (len(L), sum(r["dd"] <= -0.25 for r in L), 100 * sum(r["dd"] <= -0.25 for r in L) / len(L)) if L else "0 次"
        print("・%s：成立 %s｜不成立 %s" % (name, s(a), s(b)))
    json.dump(rows, open("crash_hist.json", "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
