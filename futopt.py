"""
futopt.py - 每晚報告的「期貨籌碼燈號」（2026-11-26 使用者同意加入）
看兩個回測（research/futopt_bt.py）前後都穩定的指標，排名用過去 250 個交易日：
  外資台指期 5 天加減碼（淨未平倉口數 5 天變化）：前 10%（大加碼）→ 之後 20 天大盤上漲 71%、平均 +3.0%（平常 62%、+1.2%）
  選擇權未平倉賣權／買權比（P/C 比）：前 10%（偏高）→ 72%、+2.6%；後 10%（偏低）只有 56%、+0.3%
大盤急跌（0050 5 天跌 3% 以上）時：外資 5 天加碼（前 30%）→ 59 次 20 天後漲 83%、+5.5%；減碼（後 30%）→ 53%、−0.9%
  → 提醒「可以開始小量分批買」，但名單的「急跌先觀望」先不解除（還沒用策略選股驗證，等 10 年歷史補完）
資料：FinMind TaiwanFuturesInstitutionalInvestors（TX）、期交所 pcRatioDown（每月一段）
用法：FINMIND_TOKEN=… python futopt.py
"""
import csv
import datetime as dt
import io
import os
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0"}
LOOK = 250


def foreign_net(rows):
    net = {}
    for r in rows:
        if "外資" not in (r.get("institutional_investors") or ""):
            continue
        lo, sh = r.get("long_open_interest_balance_volume"), r.get("short_open_interest_balance_volume")
        if lo is not None and sh is not None and r.get("date"):
            net[r["date"]] = net.get(r["date"], 0) + lo - sh
    return net


def taifex_fut(start, cid="TXF"):
    """期交所「三大法人－區分各期貨契約」（每月一段 CSV）→ {日期: 外資淨未平倉口數}
    2026-11-26 加：FinMind 每小時有請求上限，抓不到時直接從期交所抓"""
    out = {}
    d = start.replace(day=1)
    first = True
    while d <= dt.date.today():
        e = min((d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1), dt.date.today())
        body = ("queryStartDate=%s&queryEndDate=%s&commodityId=%s" % (d.strftime("%Y/%m/%d"), e.strftime("%Y/%m/%d"), cid)).encode()
        for k in range(2):
            try:
                req = urllib.request.Request("https://www.taifex.com.tw/cht/3/futContractsDateDown", data=body,
                                             headers=dict(UA, **{"Content-Type": "application/x-www-form-urlencoded"}))
                with urllib.request.urlopen(req, timeout=40) as r:
                    rows = list(csv.reader(io.StringIO(r.read().decode("big5", "replace"))))
                head = [x.strip() for x in rows[0]] if rows else []
                if first:
                    print("期交所期貨法人欄位：", head[:15], flush=True)
                    first = False
                iw = next((i for i, x in enumerate(head) if "身份" in x), None)
                inet = next((i for i, x in enumerate(head) if "未平倉" in x and "口數" in x and "淨額" in x), None)
                for row in rows[1:]:
                    if iw is None or inet is None or len(row) <= max(iw, inet) or "外資" not in row[iw]:
                        continue
                    try:
                        out[dt.date.fromisoformat(row[0].strip().replace("/", "-")).isoformat()] = int(float(row[inet].replace(",", "")))
                    except ValueError:
                        pass
                break
            except Exception:
                time.sleep(3)
        d = e + dt.timedelta(days=1)
        time.sleep(1)
    return out


SRC = []  # 這次外資期貨資料來源（給執行紀錄看）


def pcr(start):
    """期交所選擇權買賣權比 → {日期: 未平倉 P/C 比}；抓不到的月份略過"""
    out = {}
    d = start.replace(day=1)
    while d <= dt.date.today():
        e = min((d.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1), dt.date.today())
        url = "https://www.taifex.com.tw/cht/3/pcRatioDown?queryStartDate=%s&queryEndDate=%s" % (d.strftime("%Y/%m/%d"), e.strftime("%Y/%m/%d"))
        for k in range(2):
            try:
                with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                    rows = list(csv.reader(io.StringIO(r.read().decode("big5", "replace"))))
                head = rows[0] if rows else []
                ic = next((i for i, x in enumerate(head) if "未平倉" in x and "比" in x), None)
                for row in rows[1:]:
                    if ic is not None and len(row) > ic:
                        try:
                            out[dt.date.fromisoformat(row[0].strip().replace("/", "-")).isoformat()] = float(row[ic].replace(",", "")) / 100
                        except ValueError:
                            pass
                break
            except Exception:
                time.sleep(3)
        d = e + dt.timedelta(days=1)
        time.sleep(1)
    return out


def rank(vals, x):
    """x 在 vals 裡排第幾（0～1）"""
    return sum(1 for v in vals if v < x) / len(vals) if vals else None


def state(fnet, pc):
    """回傳 dict：最新日期、淨未平倉、5 天加減碼與排名、P/C 比與排名"""
    D = sorted(fnet)
    if len(D) < LOOK + 6:
        return None
    fd = {D[t]: fnet[D[t]] - fnet[D[t - 5]] for t in range(5, len(D))}
    k = D[-1]
    hist = [fd[D[t]] for t in range(len(D) - 1 - LOOK, len(D) - 1) if D[t] in fd]
    out = {"date": k, "net": fnet[k], "fd5": fd[k], "fd_p": rank(hist, fd[k])}
    P = sorted(pc)
    if len(P) > LOOK:
        out.update(pc=pc[P[-1]], pc_date=P[-1], pc_p=rank([pc[x] for x in P[-1 - LOOK:-1]], pc[P[-1]]))
    return out


def text(s, drop=None):
    """燈號文字；drop＝0050 近 5 天漲跌幅（急跌時加一行提醒）"""
    if not s:
        return ""
    fp, pp = s.get("fd_p"), s.get("pc_p")
    hi = (fp is not None and fp >= 0.9) or (pp is not None and pp >= 0.9)
    lo = (fp is not None and fp < 0.1) or (pp is not None and pp < 0.1)
    parts = ["外資台指期淨%s %s 口，5 天%s %s 口（一年來%s）" % (
        "多單" if s["net"] >= 0 else "空單", "{:,}".format(abs(s["net"])), "加碼" if s["fd5"] >= 0 else "減碼", "{:,}".format(abs(s["fd5"])),
        "前 %d%%" % max(1, round((1 - fp) * 100)) if fp >= 0.5 else "後 %d%%" % max(1, round(fp * 100)))]
    if s.get("pc") is not None:
        parts.append("選擇權賣權／買權比 %.2f（一年來%s）" % (s["pc"], "前 %d%%，偏高" % max(1, round((1 - pp) * 100)) if pp >= 0.9 else
                                                     "後 %d%%，偏低" % max(1, round(pp * 100)) if pp < 0.1 else "中間"))
    if hi and not lo:
        head, why = "🟢 偏多", "回測（外資 2018 年起、賣權／買權比 2014 年起，前後兩半都成立）：外資 5 天大加碼或賣權／買權比偏高之後，20 天大盤上漲約 7 成、平均 +2.6%（平常約 6 成、+1%）"
    elif lo and not hi:
        head, why = "🔴 偏弱", "外資 5 天大減碼或賣權／買權比偏低：之後 20 天上漲只有 5～6 成（平常約 6 成），追高要小心"
    elif hi and lo:
        head, why = "⚪ 訊號互相矛盾", "外資和選擇權方向不一致，先不看這一項"
    else:
        head, why = "⚪ 普通", "沒有明顯方向"
    L = ["📊 期貨籌碼燈號：%s｜%s" % (head, "；".join(parts)), "・" + why]
    if drop is not None and drop <= -0.03 and fp is not None:
        if fp >= 0.7:
            L.append("・👉 大盤急跌中（0050 5 天 %.1f%%），但外資在期貨加碼：回測 18 波之後 20 天上漲 85%%、平均 +5.4%%，"
                     "可以開始小量分批買大型好股" % (drop * 100))
        elif fp < 0.3:
            L.append("・⏳ 大盤急跌中（0050 5 天 %.1f%%），外資還在期貨減碼（回測 25 波之後 20 天只有 38%% 上漲、平均 −1.9%%）：繼續等" % (drop * 100))
    return "\n".join(L)


def line(data=None):
    """每晚報告用；抓不到資料回傳空字串"""
    import fetch_finmind
    fetch_finmind.TOKEN = fetch_finmind.TOKEN or (os.environ.get("FINMIND_TOKEN") or "").strip()
    start = dt.date.today() - dt.timedelta(days=420)
    rows = fetch_finmind.get("TaiwanFuturesInstitutionalInvestors", "TX", start.isoformat(), wait=False)
    fnet = foreign_net(rows or [])
    SRC[:] = ["FinMind"]
    if len(fnet) < LOOK + 6:  # FinMind 抓不到或不夠（每小時上限）：直接抓期交所
        fnet = taifex_fut(start)
        SRC[:] = ["期交所"]
    try:
        pc = pcr(start)
    except Exception:
        pc = {}
    drop = None
    if data:
        try:
            import analysis
            drop = analysis.drop5(data)
        except Exception:
            pass
    return text(state(fnet, pc), drop)


if __name__ == "__main__":
    print(line() or "抓不到資料")
    print("外資期貨資料來源：", SRC)
