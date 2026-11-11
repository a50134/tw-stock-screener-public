"""
rescue_study.py - 國安基金護盤股研究：護盤前跌多少、護盤後漲多少、哪幾檔最值得在下次護盤時買

名單（財政部公布＋媒體整理）：
  2020-03（第 7 次）19 檔、2022-07（第 8 次）15 檔、2025-04（第 9 次）8 檔；台積電、鴻海、台達電、廣達、台塑、富邦金 三次都有
護盤日期（進場日，早期幾次是約略日期）：2000-03-16、2000-10-02、2004-05-19、2008-09-19、2011-12-20、2015-08-25、2020-03-20、2022-07-13、2025-04-09、2026-11-09
資料：Yahoo Finance 還原股價（含配息），GitHub Actions 上跑
算法：進場日收盤買，看 20／60／120／250 個交易日後的報酬、和加權指數比（超額報酬）；進場前 20 天跌多少；進場後 60 天內最多再跌多少
用法：python rescue_study.py
"""
import datetime as dt
import statistics as st
import sys

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
EVENTS = ["2000-03-16", "2000-10-02", "2004-05-19", "2008-09-19", "2011-12-20", "2015-08-25", "2020-03-20", "2022-07-13", "2025-04-09", "2026-11-09"]
NAMES = {
    "2330": "台積電", "2317": "鴻海", "2308": "台達電", "2382": "廣達", "1301": "台塑", "2881": "富邦金",  # 三次都有
    "2454": "聯發科", "3711": "日月光投控", "2882": "國泰金", "2884": "玉山金", "2891": "中信金", "1216": "統一",
    "1303": "南亞", "1326": "台化", "6505": "台塑化", "2474": "可成", "2801": "彰銀", "2880": "華南金",
    "2885": "元大金", "2886": "兆豐金", "2892": "第一金", "1101": "台泥",
}
CORE = ["2330", "2317", "2308", "2382", "1301", "2881"]
BOUGHT = {"2020-03-20": "2330 2308 2317 2382 2474 2801 2880 2881 2882 2884 2885 2886 2891 2892 1101 1301 1303 1326 1216",
          "2022-07-13": "2330 2454 2308 2382 2317 3711 2881 2882 2884 2891 1216 1301 1303 1326 6505",
          "2025-04-09": "1301 2308 2317 2330 2382 2454 2881 3711"}


def yahoo(sym):
    for host in ("query1", "query2"):
        try:
            r = requests.get("https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=946684800&period2=%d&interval=1d&includeAdjustedClose=true"
                             % (host, sym, int(dt.datetime.now().timestamp())), headers=UA, timeout=40)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or res["indicators"]["quote"][0]["close"]
            return {dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m-%d"): a for ts, a in zip(res["timestamp"], adj) if a}
        except Exception as e:
            print("  ! %s（%s）：%s" % (sym, host, e), file=sys.stderr)
    return {}


def stats(px, ev):
    D = sorted(px)
    i = next((k for k, d in enumerate(D) if d >= ev), None)
    if i is None or i < 20:
        return None
    c = [px[d] for d in D]
    out = {"pre20": c[i] / c[i - 20] - 1}
    for h in (20, 60, 120, 250):
        out[h] = c[i + h] / c[i] - 1 if i + h < len(c) else None
    out["dd60"] = min(c[i:i + 61]) / c[i] - 1 if i + 1 < len(c) else None
    return out


def path_study(tw, pct):
    """進場後每一天的走勢：先彈多少、第幾天最高、之後回跌多少、有沒有跌破進場前的低點（第二隻腳）、最後第幾天見底"""
    D = sorted(tw)
    c = [tw[d] for d in D]
    print("\n【進場後的路徑：先彈再跌？】（收盤價；第 0 天＝進場日）")
    print("進場日      進場前低點→進場日 | 前 20 天最高（第幾天、從進場前低點彈多少）| 之後 60 天回跌多少（第幾天最低）| 跌破進場前低點？| 120 天內最低在第幾天 | 各天累積：5／10／20／40／60 天")
    R = []
    for ev in EVENTS:
        i = next((k for k, d in enumerate(D) if d >= ev), None)
        if i is None or i < 10:
            continue
        j0 = min(range(i - 10, i + 1), key=lambda k: c[k])  # 進場前 10 天（含進場日）的最低收盤
        lo0 = c[j0]
        n = len(c)
        if i + 5 >= n:
            print("・%s：進場前低點 %.0f，到現在第 %d 天 %s（還太新，沒有後面的資料）" % (ev, lo0, n - 1 - i, pct(c[-1] / lo0 - 1)))
            continue
        e20 = min(n - 1, i + 20)
        pk = max(range(i, e20 + 1), key=lambda k: c[k])
        e60 = min(n - 1, pk + 60)
        tr = min(range(pk, e60 + 1), key=lambda k: c[k])
        e120 = min(n - 1, i + 120)
        bot = min(range(i, e120 + 1), key=lambda k: c[k])
        broke = c[tr] < lo0
        cum = [pct(c[i + h] / c[i] - 1) if i + h < n else "—" for h in (5, 10, 20, 40, 60)]
        R.append(dict(bounce=c[pk] / lo0 - 1, pkday=pk - i, drop=c[tr] / c[pk] - 1, trday=tr - i, broke=broke, botday=bot - i,
                      c10=c[i + 10] / c[i] - 1 if i + 10 < n else None))
        print("・%s %.0f→%.0f | 第 %d 天最高、彈 %s | 回跌 %s（第 %d 天）| %s | 第 %d 天 | %s" % (
            ev, lo0, c[i], pk - i, pct(c[pk] / lo0 - 1), pct(c[tr] / c[pk] - 1), tr - i, "有跌破（再跌 %s）" % pct(c[tr] / lo0 - 1) if broke else "沒破", bot - i, "／".join(cum)))
    if R:
        md = lambda L: sorted(L)[len(L) // 2]
        print("小結（%d 次）：前 20 天從進場前低點平均彈 %s（中位 %s）、最高點平均在第 %.0f 天；之後平均回跌 %s（中位 %s）；%d 次跌破進場前低點；120 天內的最低點有 %d 次在進場 5 天內、%d 次在 20 天以後" % (
            len(R), pct(st.mean(x["bounce"] for x in R)), pct(md([x["bounce"] for x in R])), st.mean(x["pkday"] for x in R),
            pct(st.mean(x["drop"] for x in R)), pct(md([x["drop"] for x in R])), sum(x["broke"] for x in R),
            sum(x["botday"] <= 5 for x in R), sum(x["botday"] > 20 for x in R)))
        # 反彈幅度大小 vs 之後回跌
        big = [x for x in R if x["bounce"] >= 0.10]
        if big:
            print("　其中前 20 天彈 10%% 以上的 %d 次：之後平均回跌 %s、%d 次跌破進場前低點" % (len(big), pct(st.mean(x["drop"] for x in big)), sum(x["broke"] for x in big)))


def main():
    tw = yahoo("%5ETWII")
    P = {sid: yahoo(sid + ".TW") for sid in NAMES}
    pct = lambda x: "—" if x is None else "%+.0f%%" % (x * 100)
    print("國安基金護盤股研究（進場日收盤買；超額＝比加權指數多賺幾 %）\n")
    print("【每次護盤：加權指數】")
    for ev in EVENTS:
        s = stats(tw, ev)
        if s:
            print("・%s：護盤前 20 天 %s｜之後最多再跌 %s｜20 天 %s、60 天 %s、120 天 %s、250 天 %s" % (
                ev, pct(s["pre20"]), pct(s["dd60"]), pct(s[20]), pct(s[60]), pct(s[120]), pct(s[250])))
    path_study(tw, pct)
    rows = []
    for sid, nm in NAMES.items():
        px = P.get(sid) or {}
        ex = {h: [] for h in (20, 60, 120, 250)}
        raw = {h: [] for h in (20, 60, 120, 250)}
        pre, dd, beat = [], [], 0
        n = 0
        for ev in EVENTS:
            s, m = stats(px, ev), stats(tw, ev)
            if not s or not m:
                continue
            n += 1
            pre.append(s["pre20"] - m["pre20"])
            if s["dd60"] is not None:
                dd.append(s["dd60"])
            for h in ex:
                if s[h] is not None and m[h] is not None:
                    ex[h].append(s[h] - m[h])
                    raw[h].append(s[h])
            if s[120] is not None and m[120] is not None and s[120] > m[120]:
                beat += 1
        if not n:
            print("・%s %s：抓不到股價" % (sid, nm))
            continue
        avg = lambda L: st.mean(L) if L else None
        rows.append((avg(ex[120]) if ex[120] else -9, sid, nm, n, avg(pre), avg(dd), {h: avg(raw[h]) for h in raw}, {h: avg(ex[h]) for h in ex},
                     beat, len(ex[120]), sum(1 for e in BOUGHT if sid in BOUGHT[e].split())))
    rows.sort(reverse=True)
    print("\n【每檔股票（依 120 天超額報酬排序）】")
    print("代號 名稱       次數 被買次數 護盤前比大盤多跌 之後最多再跌 | 20天 60天 120天 250天（平均報酬）| 120天超額 250天超額 贏大盤次數")
    for _, sid, nm, n, pre, dd, raw, ex, beat, nb, bought in rows:
        print("%s %-6s %s %d 次  %d 次  %s  %s | %s %s %s %s | %s %s %d/%d%s" % (
            sid, nm, "⭐" if sid in CORE else "  ", n, bought, pct(pre), pct(dd), pct(raw[20]), pct(raw[60]), pct(raw[120]), pct(raw[250]),
            pct(ex[120]), pct(ex[250]), beat, nb, ""))
    print("\n⭐＝近 3 次護盤都有買（台積電、鴻海、台達電、廣達、台塑、富邦金）")


if __name__ == "__main__":
    main()
