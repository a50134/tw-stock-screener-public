"""
us_timing.py - 美股大盤擇時回測（每月看一次，決定抱股票還是躲到債券）；us_bt.py 最後會呼叫，結果只存私人專案

E. 10 個月均線擇時（Meb Faber）：月底 SPY 在 10 個月均線上 → 下個月抱 SPY；跌破 → 換短期美債（SHY）
   另外用標普 500 指數（^GSPC，1950 年起、不含股利，現金用 3 個月國庫券利率）看更長的歷史
F. 雙動能 GEM（Antonacci）：月底比過去 12 個月報酬，SPY 贏國庫券 → 抱 SPY 與 EFA（美國以外已開發國家）裡比較強的；輸 → 抱 AGG（綜合債券）
資料：Yahoo Finance 月線還原價（含股利）。每次換手扣 0.1% 成本
"""
import datetime as dt
import sys

import requests

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
COST = 0.001


def monthly(sym):
    """{YYYY-MM: 月底還原收盤}"""
    for host in ("query1", "query2"):
        try:
            r = requests.get("https://%s.finance.yahoo.com/v8/finance/chart/%s?period1=-630000000&period2=%d&interval=1mo&includeAdjustedClose=true"
                             % (host, sym, int(dt.datetime.now().timestamp())), headers=UA, timeout=40)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            adj = res["indicators"].get("adjclose", [{}])[0].get("adjclose") or res["indicators"]["quote"][0]["close"]
            return {dt.datetime.fromtimestamp(ts, dt.timezone.utc).strftime("%Y-%m"): a for ts, a in zip(res["timestamp"], adj) if a}
        except Exception as e:
            print("  ! %s（%s）：%s" % (sym, host, type(e).__name__), file=sys.stderr)
    return {}


def stats(rets, months):
    """rets：每月報酬（小數）。回傳 年化、最大跌幅、最差一年、各年報酬"""
    eq, peak, mdd, yr = 1.0, 1.0, 0.0, {}
    for r, m in zip(rets, months):
        eq *= 1 + r
        peak = max(peak, eq)
        mdd = min(mdd, eq / peak - 1)
        yr[m[:4]] = (1 + yr.get(m[:4], 0)) * (1 + r) - 1
    cagr = eq ** (12 / len(rets)) - 1 if rets else 0
    return cagr, mdd, min(yr.values()) if yr else 0, yr


def line(name, rets, months):
    c, d, w, _ = stats(rets, months)
    return "　%s：年化 %+.1f%%、最大跌幅 %.0f%%、最差一年 %+.0f%%" % (name, c * 100, d * 100, w * 100)


def run_e(px, cash_ret, months):
    """px：{月: 價}；cash_ret(m)：躲開時那個月的報酬。回傳 (策略月報酬, 買進抱著月報酬, 月份, 換手次數, 現在抱股票嗎)"""
    out, bh, ms, sw, prev = [], [], [], 0, None
    for i in range(10, len(months) - 1):
        m, nx = months[i], months[i + 1]
        win = [px[k] for k in months[i - 9:i + 1]]
        inn = px[m] > sum(win) / 10
        r_stock = px[nx] / px[m] - 1
        r = r_stock if inn else cash_ret(m, nx)
        if prev is not None and inn != prev:
            r -= COST
            sw += 1
        prev = inn
        out.append(r)
        bh.append(r_stock)
        ms.append(nx)
    last = months[-1]
    now = px[last] > sum(px[k] for k in months[-10:]) / 10
    return out, bh, ms, sw, now


def report():
    P = {s: monthly(s) for s in ("SPY", "EFA", "AGG", "SHY", "%5EGSPC", "%5EIRX")}
    spy, efa, agg, shy, gspc, irx = (P[k] for k in ("SPY", "EFA", "AGG", "SHY", "%5EGSPC", "%5EIRX"))
    L = ["", "🧭 大盤擇時（每月看一次；含股利、每次換手扣 0.1%）"]
    if not spy or not shy:
        return "\n".join(L + ["　資料抓不到"])
    tb = lambda m: (irx.get(m) or 0) / 100 / 12  # 3 個月國庫券：年利率 → 一個月
    # E：SPY／SHY（2003 年起）
    ms = sorted(set(spy) & set(shy))
    r, bh, mm, sw, now = run_e(spy, lambda a, b: shy[b] / shy[a] - 1, ms)
    L.append("・E. 10 個月均線擇時（SPY 跌破 10 個月均線就換短期美債 SHY）｜%s～%s，換手 %d 次（平均一年 %.1f 次）" % (mm[0], mm[-1], sw, sw / (len(mm) / 12)))
    L.append(line("照策略", r, mm))
    L.append(line("一直抱 SPY", bh, mm))
    k = max(0, len(mm) - 60)
    L.append(line("近 5 年 照策略", r[k:], mm[k:]))
    L.append(line("近 5 年 一直抱", bh[k:], mm[k:]))
    _, _, _, ys = stats(r, mm)
    _, _, _, yb = stats(bh, mm)
    L.append("　大跌的年份（策略／一直抱）：" + "、".join("%s %+.0f%%／%+.0f%%" % (y, ys[y] * 100, yb[y] * 100) for y in sorted(yb) if yb[y] < -0.05))
    L.append("　現在：%s" % ("SPY 在 10 個月均線上 → 抱股票" if now else "SPY 跌破 10 個月均線 → 該躲到短期美債"))
    # E 長期：標普 500 指數（不含股利）
    if gspc and irx:
        ms2 = sorted(m for m in gspc if m >= "1960-01")
        r2, bh2, mm2, sw2, _ = run_e(gspc, lambda a, b: tb(a), ms2)
        L.append("・E（長期）標普 500 指數 %s～%s（不含股利；躲開時拿 3 個月國庫券利息），換手 %d 次" % (mm2[0], mm2[-1], sw2))
        L.append(line("照策略", r2, mm2))
        L.append(line("一直抱", bh2, mm2))
        _, _, _, ys2 = stats(r2, mm2)
        _, _, _, yb2 = stats(bh2, mm2)
        L.append("　跌 10% 以上的年份（策略／一直抱）：" + "、".join("%s %+.0f%%／%+.0f%%" % (y, ys2[y] * 100, yb2[y] * 100) for y in sorted(yb2) if yb2[y] < -0.10))
    # F：GEM
    if efa and agg:
        ms3 = sorted(set(spy) & set(efa) & set(agg))
        out, bh3, mm3, sw3, prev, hold = [], [], [], 0, None, ""
        for i in range(12, len(ms3) - 1):
            m, nx, m0 = ms3[i], ms3[i + 1], ms3[i - 12]
            rs, re_ = spy[m] / spy[m0] - 1, efa[m] / efa[m0] - 1
            rt = sum(tb(k) for k in ms3[i - 11:i + 1])
            pick = ("SPY" if rs >= re_ else "EFA") if rs > rt else "AGG"
            px = {"SPY": spy, "EFA": efa, "AGG": agg}[pick]
            rr = px[nx] / px[m] - 1
            if prev and pick != prev:
                rr -= COST
                sw3 += 1
            prev = pick
            out.append(rr)
            bh3.append(spy[nx] / spy[m] - 1)
            mm3.append(nx)
        i = len(ms3) - 1
        rs, re_ = spy[ms3[i]] / spy[ms3[i - 12]] - 1, efa[ms3[i]] / efa[ms3[i - 12]] - 1
        rt = sum(tb(k) for k in ms3[i - 11:i + 1])
        hold = ("美股 SPY" if rs >= re_ else "國際股 EFA") if rs > rt else "債券 AGG"
        L.append("・F. 雙動能 GEM（美股／國際股／債券，看過去 12 個月誰強）｜%s～%s，換手 %d 次（平均一年 %.1f 次）" % (mm3[0], mm3[-1], sw3, sw3 / (len(mm3) / 12)))
        L.append(line("照策略", out, mm3))
        L.append(line("一直抱 SPY", bh3, mm3))
        k = max(0, len(mm3) - 60)
        L.append(line("近 5 年 照策略", out[k:], mm3[k:]))
        L.append(line("近 5 年 一直抱", bh3[k:], mm3[k:]))
        _, _, _, ys3 = stats(out, mm3)
        _, _, _, yb3 = stats(bh3, mm3)
        L.append("　大跌的年份（策略／一直抱）：" + "、".join("%s %+.0f%%／%+.0f%%" % (y, ys3[y] * 100, yb3[y] * 100) for y in sorted(yb3) if yb3[y] < -0.05))
        L.append("　現在該抱：%s（近 12 個月 SPY %+.0f%%、EFA %+.0f%%、國庫券 %+.1f%%）" % (hold, rs * 100, re_ * 100, rt * 100))
    return "\n".join(L)


if __name__ == "__main__":
    print(report())
