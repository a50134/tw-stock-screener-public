"""
2026-11-26 使用者同意：期貨、選擇權的大戶動向能不能預測大盤（加強判斷、讓名單更準）
資料（2014 年起）：
  外資台指期淨未平倉（多單 − 空單口數）：FinMind TaiwanFuturesInstitutionalInvestors（TX）
  小台散戶多空比：−（三大法人小台淨未平倉）÷ 小台全市場未平倉，FinMind TaiwanFuturesInstitutionalInvestors（MTX）＋ TaiwanFuturesDaily（MTX）
  選擇權未平倉買賣權比（Put/Call ratio）：期交所 pcRatioDown（每月一段）
  加權指數：Yahoo ^TWII
看法：每天收盤後的數字，對比之後 5 天、20 天大盤漲跌。數字的高低用「過去 250 天裡排第幾 %」（避免口數大小隨年份改變）
另外看：大盤 5 天跌 3% 以上（已加的「急跌先觀望」）時，這些數字能不能分出「之後會反彈」的情況
用法：FINMIND_TOKEN=… python research/futopt_bt.py
"""
import csv
import datetime as dt
import io
import os
import statistics as stt
import sys
import time
import urllib.request

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import fetch_finmind  # noqa: E402
import rescue_study as rs  # noqa: E402

START = 2014
UA = {"User-Agent": "Mozilla/5.0"}


def finmind(dataset, sid):
    """從 START 年抓到今天（FinMind 只給 start_date 時會回傳到最新）"""
    rows = fetch_finmind.get(dataset, sid, "%d-01-01" % START, wait=True) or []
    print("%s %s：%d 筆%s" % (dataset, sid, len(rows), "，欄位 " + str(sorted(rows[0].keys())) if rows else ""), flush=True)
    return rows


def foreign_net(rows, who=("外資",)):
    net = {}
    for r in rows:
        n = r.get("institutional_investors") or ""
        if not any(w in n for w in who):
            continue
        lo, sh = r.get("long_open_interest_balance_volume"), r.get("short_open_interest_balance_volume")
        if lo is None or sh is None:
            continue
        net[r["date"]] = net.get(r["date"], 0) + lo - sh
    return net


def mtx_total_oi(rows):
    """小台全市場未平倉：一般盤（position），各月份契約加總"""
    oi = {}
    for r in rows:
        if r.get("trading_session") not in (None, "position", "一般"):
            continue
        cd = str(r.get("contract_date") or "")
        if "/" in cd:  # 價差單
            continue
        v = r.get("open_interest")
        if v:
            oi[r["date"]] = oi.get(r["date"], 0) + v
    return oi


def pcr():
    """期交所選擇權買賣權比（每月一段 CSV）→ {日期: 未平倉 P/C 比}"""
    out = {}
    d = dt.date(START, 1, 1)
    first = True
    while d <= dt.date.today():
        e = min((d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1), dt.date.today())
        url = "https://www.taifex.com.tw/cht/3/pcRatioDown?queryStartDate=%s&queryEndDate=%s" % (d.strftime("%Y/%m/%d"), e.strftime("%Y/%m/%d"))
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                raw = r.read()
            txt = raw.decode("big5", "replace") if b"," in raw else ""
            rows = list(csv.reader(io.StringIO(txt)))
            if first:
                print("P/C 比欄位：", rows[0] if rows else txt[:200], flush=True)
                first = False
            head = rows[0] if rows else []
            ic = next((i for i, x in enumerate(head) if "未平倉" in x and "比" in x), None)
            for row in rows[1:]:
                if ic is None or len(row) <= ic:
                    continue
                ds = row[0].strip().replace("/", "-")
                try:
                    out[dt.date.fromisoformat(ds).isoformat()] = float(row[ic].replace(",", "")) / 100
                except ValueError:
                    pass
        except Exception as ex:
            print("P/C 比", d, "抓取失敗：", str(ex)[:100], flush=True)
        d = e + dt.timedelta(days=1)
        time.sleep(1.5)
    return out


def pctile(series, D, t, look=250):
    """第 t 天的值在過去 look 天裡排第幾（0～1）"""
    x = series.get(D[t])
    w = [series[D[k]] for k in range(max(0, t - look), t) if D[k] in series]
    if x is None or len(w) < look * 0.8:
        return None
    return sum(1 for v in w if v < x) / len(w)


def ret(c, t, h):
    return c[t + h] / c[t] - 1 if t + h < len(c) else None


def show(name, rows):
    """rows: [(r5, r20)]"""
    r5 = [x[0] for x in rows if x[0] is not None]
    r20 = [x[1] for x in rows if x[1] is not None]
    if len(r20) < 15:
        return "  %-28s %d 次（太少）" % (name, len(rows))
    return "  %-28s %4d 次｜5 天後漲 %3d%%、平均 %+.1f%%｜20 天後漲 %3d%%、平均 %+.1f%%" % (
        name, len(rows), round(100 * sum(x > 0 for x in r5) / len(r5)), stt.mean(r5) * 100,
        round(100 * sum(x > 0 for x in r20) / len(r20)), stt.mean(r20) * 100)


def main():
    fetch_finmind.TOKEN = (os.environ.get("FINMIND_TOKEN") or "").strip()
    tw = rs.yahoo("%5ETWII")
    D = sorted(d for d in tw if d >= "%d-01-01" % START)
    c = [tw[d] for d in D]
    print("加權指數 %s～%s，%d 天" % (D[0], D[-1], len(D)))
    tx = finmind("TaiwanFuturesInstitutionalInvestors", "TX")
    fnet = foreign_net(tx)
    mtx_inst = foreign_net(finmind("TaiwanFuturesInstitutionalInvestors", "MTX"), who=("外資", "投信", "自營"))
    mtx_oi = mtx_total_oi(finmind("TaiwanFuturesDaily", "MTX"))
    retail = {d: -mtx_inst[d] / mtx_oi[d] for d in mtx_inst if mtx_oi.get(d)}
    pc = pcr()
    print("外資台指期 %d 天、小台散戶多空比 %d 天、P/C 比 %d 天" % (len(fnet), len(retail), len(pc)))
    if fnet:
        k = max(fnet)
        print("最新 %s：外資淨未平倉 %+d 口；散戶多空比 %s；P/C 比 %s" % (
            k, fnet[k], "%+.1f%%" % (retail[k] * 100) if k in retail else "—", "%.2f" % pc[k] if k in pc else "—"))
    # 5 天變化
    fd5 = {}
    for t in range(5, len(D)):
        if D[t] in fnet and D[t - 5] in fnet:
            fd5[D[t]] = fnet[D[t]] - fnet[D[t - 5]]
    base = [(ret(c, t, 5), ret(c, t, 20)) for t in range(250, len(D) - 20)]
    print("\n隨便哪一天：\n" + show("全部", base))
    for name, ser in (("外資台指期淨未平倉", fnet), ("外資 5 天加減碼", fd5), ("小台散戶多空比", retail), ("選擇權 P/C 比（未平倉）", pc)):
        print("\n【%s】（數字在過去 250 天排名）" % name)
        groups = {"最低 10%": [], "低 10～30%": [], "中間 30～70%": [], "高 70～90%": [], "最高 10%": []}
        halves = {"最低 10%": ([], []), "最高 10%": ([], [])}
        for t in range(250, len(D) - 20):
            p = pctile(ser, D, t)
            if p is None:
                continue
            g = "最低 10%" if p < 0.1 else "低 10～30%" if p < 0.3 else "中間 30～70%" if p < 0.7 else "高 70～90%" if p < 0.9 else "最高 10%"
            r = (ret(c, t, 5), ret(c, t, 20))
            groups[g].append(r)
            if g in halves:
                halves[g][0 if D[t] < "2020-07-01" else 1].append(r)
        for g, rows in groups.items():
            print(show(g, rows))
        for g, (a, b) in halves.items():
            print("  　%s 分兩段：2020 年中以前 %s；之後 %s" % (g, show("", a).strip(), show("", b).strip()))
    # 急跌當下（加權指數 5 天跌 3% 以上）
    print("\n【大盤 5 天跌 3% 以上的日子（急跌先觀望）】")
    drops = [t for t in range(250, len(D) - 20) if c[t] / c[t - 5] - 1 <= -0.03]
    print(show("全部急跌日", [(ret(c, t, 5), ret(c, t, 20)) for t in drops]))
    for name, ser in (("外資 5 天加減碼", fd5), ("小台散戶多空比", retail), ("選擇權 P/C 比", pc)):
        lo = [(ret(c, t, 5), ret(c, t, 20)) for t in drops if (pctile(ser, D, t) or 0.5) < 0.3]
        hi = [(ret(c, t, 5), ret(c, t, 20)) for t in drops if (pctile(ser, D, t) or 0.5) >= 0.7]
        print(show(name + " 低（後 30%）", lo))
        print(show(name + " 高（前 30%）", hi))
    print("\n說明：5／20 天後的漲跌從當天收盤算，加權指數不含股利；口數換算的排名只用當天以前 250 天，不偷看未來。")


if __name__ == "__main__":
    main()
