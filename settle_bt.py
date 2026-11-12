"""
settle_bt.py - 兩個回測（2026-11-12 使用者同意做的 A、B）

A. 月結算週：外資台指期淨空單很多時，結算前幾天大盤是不是比較容易跌？
   資料：FinMind TaiwanFuturesInstitutionalInvestors（台指期 TX，外資未平倉多空口數）、Yahoo 加權指數。
   結算日＝每月第三個星期三（遇休市往後找下一個交易日）。
   看「結算日前 3 個交易日收盤 → 結算日收盤」和「結算日 → 之後 5 天」的大盤報酬，依結算前外資淨空單分組。
B. 國安基金護盤股「先站上月線」的是不是之後比較強？
   用 rescue_study 的 9 次護盤、22 檔護盤股：進場後 10 個交易日內收盤站上月線（20 日線）的 vs 沒站上的，
   比之後 60／120 天比大盤多賺多少；也看「站上月線那天才買」的結果。
用法：FINMIND_TOKEN=… python settle_bt.py
"""
import datetime as dt
import os
import statistics as stt
import sys

import fetch_finmind
import rescue_study as rs


def pct(x):
    return "—" if x is None else "%+.1f%%" % (x * 100)


def grp(name, L):
    if not L:
        return "・%s：0 次" % name
    return "・%s：%d 次｜平均 %s｜中位數 %s｜下跌機率 %.0f%%｜最差 %s" % (
        name, len(L), pct(stt.mean(L)), pct(stt.median(L)), 100 * sum(x < 0 for x in L) / len(L), pct(min(L)))


def third_wed(y, m):
    d = dt.date(y, m, 1)
    d += dt.timedelta(days=(2 - d.weekday()) % 7)
    return d + dt.timedelta(days=14)


def part_a():
    print("=" * 60 + "\n【A】月結算週 × 外資台指期淨空單\n")
    fetch_finmind.TOKEN = (os.environ.get("FINMIND_TOKEN") or "").strip()
    rows = []
    for y in range(2015, dt.date.today().year + 1):  # 一年抓一次，避免單次資料太大
        rows += fetch_finmind.get("TaiwanFuturesInstitutionalInvestors", "TX", "%d-01-01" % y, wait=True) or []
    rows = [r for r in rows if r.get("date")]
    if not rows:
        print("抓不到期貨法人資料")
        return
    print("欄位：", sorted(rows[0].keys()))
    names = sorted({r.get("institutional_investors") or r.get("name") for r in rows})
    print("法人名稱：", names)
    fkey = next((n for n in names if n and ("外資" in n or "Foreign" in n)), None)
    net = {}
    for r in rows:
        if (r.get("institutional_investors") or r.get("name")) != fkey:
            continue
        lo = r.get("long_open_interest_balance_volume")
        sh = r.get("short_open_interest_balance_volume")
        if lo is None or sh is None:
            continue
        net[r["date"]] = lo - sh
    tw = rs.yahoo("%5ETWII")
    D = sorted(d for d in tw if d >= "2015-01-01")
    c = [tw[d] for d in D]
    idx = {d: i for i, d in enumerate(D)}
    nd = sorted(net)
    print("外資淨未平倉 %s～%s，%d 天；最新 %s：%s 口；歷史最少 %s 口" % (nd[0], nd[-1], len(nd), nd[-1], "{:+,}".format(net[nd[-1]]), "{:+,}".format(min(net.values()))))
    ev = []
    y, m = 2015, 1
    while dt.date(y, m, 1) <= dt.date.today():
        s = third_wed(y, m).isoformat()
        k = next((d for d in D if d >= s), None)
        if k and k[:7] == s[:7]:
            i = idx[k]
            if i >= 5 and i + 5 < len(D):
                pre = D[i - 3]
                nn = max((d for d in nd if d <= pre), default=None)
                if nn:
                    ev.append((k, net[nn], c[i] / c[i - 3] - 1, c[i + 5] / c[i] - 1, min(c[i - 3:i + 1]) / c[i - 3] - 1))
        m += 1
        if m > 12:
            y, m = y + 1, 1
    print("結算日共 %d 次（%s～%s）\n" % (len(ev), ev[0][0], ev[-1][0]))
    vals = sorted(e[1] for e in ev)
    q20 = vals[len(vals) // 5]
    print("淨空單（負數）分組；歷史前 20%% 最空的門檻約 %s 口" % "{:+,}".format(q20))
    for name, f in (("淨空單 7 萬口以上", lambda v: v <= -70000), ("淨空單 4～7 萬口", lambda v: -70000 < v <= -40000),
                    ("淨空單 2～4 萬口", lambda v: -40000 < v <= -20000), ("淨空單 2 萬口以下或淨多單", lambda v: v > -20000),
                    ("歷史前 20% 最空", lambda v: v <= q20), ("其他 80%", lambda v: v > q20)):
        L = [e for e in ev if f(e[1])]
        print(grp("%s｜結算前 3 天→結算日" % name, [e[2] for e in L]))
        print(grp("%s｜結算日→之後 5 天" % name, [e[3] for e in L]))
        print(grp("%s｜結算前 3 天內最多跌" % name, [e[4] for e in L]))
    print("\n淨空單 6 萬口以上的每一次：")
    for e in ev:
        if e[1] <= -60000:
            print("  %s 淨 %s 口｜結算前 3 天→結算 %s｜結算後 5 天 %s" % (e[0], "{:+,}".format(e[1]), pct(e[2]), pct(e[3])))


def part_b():
    print("\n" + "=" * 60 + "\n【B】國安基金護盤股：先站上月線的是不是比較強\n")
    tw = rs.yahoo("%5ETWII")
    P = {sid: rs.yahoo(sid + ".TW") for sid in rs.NAMES}
    TD = sorted(tw)
    early, late, on_day, base = {60: [], 120: []}, {60: [], 120: []}, {60: [], 120: []}, {60: [], 120: []}
    first5 = {60: [], 120: []}
    det = []
    for ev in rs.EVENTS[:-1]:  # 最新一次還沒有結果
        i0 = next((k for k, d in enumerate(TD) if d >= ev), None)
        if i0 is None:
            continue
        for sid, nm in rs.NAMES.items():
            px = P.get(sid) or {}
            D = sorted(px)
            j = next((k for k, d in enumerate(D) if d >= TD[i0]), None)
            if j is None or j < 25 or j + 121 >= len(D):
                continue
            c = [px[d] for d in D]
            ma = lambda k: sum(c[k - 19:k + 1]) / 20
            cross = next((k for k in range(j, j + 11) if c[k] > ma(k)), None)  # 進場後 10 天內第一次收盤站上月線

            def ex(a, h):
                ta = TD.index(D[a]) if D[a] in tw else None
                if ta is None or ta + h >= len(TD) or a + h >= len(c):
                    return None
                return (c[a + h] / c[a] - 1) - (tw[TD[ta + h]] / tw[TD[ta]] - 1)
            for h in (60, 120):
                e0 = ex(j, h)
                if e0 is None:
                    continue
                base[h].append(e0)
                (early if cross is not None else late)[h].append(e0)
                if cross is not None and cross - j <= 5:
                    first5[h].append(e0)
                if cross is not None:
                    e1 = ex(cross, h)
                    if e1 is not None:
                        on_day[h].append(e1)
            det.append((ev, nm, cross - j if cross is not None else None))
    for h in (60, 120):
        print("抱 %d 天（比加權指數多賺）" % h)
        print(grp("全部護盤股（進場日買）", base[h]).replace("下跌機率", "輸大盤機率"))
        print(grp("進場後 10 天內先站上月線（進場日買）", early[h]).replace("下跌機率", "輸大盤機率"))
        print(grp("其中 5 天內就站上", first5[h]).replace("下跌機率", "輸大盤機率"))
        print(grp("10 天內沒站上月線（進場日買）", late[h]).replace("下跌機率", "輸大盤機率"))
        print(grp("站上月線那天才買", on_day[h]).replace("下跌機率", "輸大盤機率"))
    print("\n每次護盤 10 天內先站上月線的（第幾天）：")
    for ev in rs.EVENTS[:-1]:
        L = ["%s(%d)" % (nm, k) for e, nm, k in det if e == ev and k is not None]
        print("  %s：%s" % (ev, "、".join(L) or "沒有"))


if __name__ == "__main__":
    if "--b" not in sys.argv:
        part_a()
    if "--a" not in sys.argv:
        part_b()
