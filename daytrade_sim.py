"""
daytrade_sim.py - 模擬當沖紀錄＋教學（2026-11-21 使用者要的；只記錄、不下單，結果只發 Discord、存私人專案）

為什麼是模擬：research/daytrade_bt.py 回測台股最近 60 天 5 分 K，常見當沖買法扣成本後都是賠（勝率 45%～49%），
所以先用假想交易累積 1～2 個月的真實成績，再決定要不要真的做。

每個交易日收盤後（14:20 排程）：
  1. 抓市值前 100 檔今天的 5 分 K（Yahoo）
  2. 照兩個規則重演今天（跟回測一模一樣，不偷看後面的 K 棒）：
     A 開盤區間突破＋爆量：09:00～09:15 三根 K 棒的最高價＝區間上緣；10:30 前第一根「收盤突破上緣、而且量 ≥ 前面平均 2 倍」的 K 棒收盤買；
       停損＝區間中間，目標＝買價＋（買價－停損）＝1R；13:25 前沒碰到就收盤賣
     B 跳空跌深反彈：開盤比昨收低 3% 以上，09:15 前出現「收盤高於開盤價的紅 K」就買；停損＝當天到那時的最低價；目標 1R
  3. 每筆假設買 10 萬元（零股也算），扣手續費 2.8 折來回約 0.08%＋當沖證交稅 0.15%
  4. 記到 daytrade_log.json（私人專案），發 Discord：今天每一筆怎麼進、怎麼出、賺賠多少＋累計成績＋一則當沖小知識
用法：python daytrade_sim.py data.json [--date 2026-11-20]
"""
import datetime as dt
import json
import os
import statistics as stt
import sys
import time

import requests

DIR = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(DIR, "daytrade_log.json")
OUT = os.path.join(DIR, "report_daytrade.txt")
UA = {"User-Agent": "Mozilla/5.0"}
COST = 0.0025   # 手續費 0.1425%×2×2.8 折 ≈ 0.08%＋當沖證交稅 0.15%（一般 0.3% 的一半）
BUDGET = 100000  # 每筆假想投入金額
SHOW = 4         # Discord 詳細教學最多幾筆

TIPS = [
    "當沖是什麼：同一天買進又賣出同一檔股票，不用付全額股款，只結算價差。好處是不留過夜風險，壞處是成本固定、每天都要判斷。",
    "要先有資格：開戶滿 3 個月、近一年成交 10 筆以上，還要簽「當沖風險預告書」，券商才會開放。資格開通前只能模擬。",
    "成本算法：手續費 0.1425%（買賣各一次，網路下單常打 2.8 折）＋當沖證交稅 0.15%。來回約 0.25%，所以每次要賺超過 0.25% 才打平。",
    "最大風險：當沖沒賣掉就變成要付全額交割。帳戶錢不夠會「違約交割」，信用紀錄會出問題。永遠在 13:25 前處理完。",
    "開盤區間：09:00～09:15 的最高、最低價。很多人看這個區間被突破的方向決定當天走勢，但回測顯示單看這個訊號勝率只有 45%。",
    "停損為什麼放在區間中間：股價跌回區間中間，代表剛才的突破失敗，繼續抱只是賭運氣。停損不是賠錢，是保護本金的保險費。",
    "1R 是什麼：R＝買價到停損的距離，也就是這筆最多賠多少。目標 1R＝想賺的跟可能賠的一樣多，勝率要超過 50%＋成本才會賺。",
    "爆量突破：突破那根 K 棒的成交量是前面平均 2 倍以上，代表很多人搶著買，比較不容易是假突破。回測比沒爆量好一點，但扣成本後還是小賠。",
    "跳空跌深反彈：開盤大跌 3% 以上又馬上收紅，代表恐慌賣壓被接住。停損放在當天最低點，跌破代表接手的人撐不住。",
    "先買後賣 vs 先賣後買：先賣後買（當沖空）要另外有券源、有限制，新手先別碰。我們的模擬只做先買後賣。",
    "看模擬成績的重點：不是單日賺賠，而是累積 30 筆以上後的勝率和平均每筆賺賠。扣成本後平均每筆是負的，就不要真的做。",
    "紀律：進場前先寫好停損和目標，碰到就執行，不要盤中改。模擬紀錄就是在練這個習慣。",
]


def bars5(sym, day):
    """抓今天的 5 分 K：[(分鐘, 開, 高, 低, 收, 量)]，09:00～13:25"""
    for k, host in enumerate(("query1", "query2", "query1")):
        try:
            r = requests.get("https://%s.finance.yahoo.com/v8/finance/chart/%s?range=5d&interval=5m" % (host, sym), headers=UA, timeout=30)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            off = res["meta"].get("gmtoffset", 28800)
            q = res["indicators"]["quote"][0]
            B = []
            for i, ts in enumerate(res.get("timestamp") or []):
                o, h, l, c, v = (q[x][i] for x in ("open", "high", "low", "close", "volume"))
                if None in (o, h, l, c):
                    continue
                t = dt.datetime.utcfromtimestamp(ts + off)
                m = t.hour * 60 + t.minute
                if t.strftime("%Y-%m-%d") == day and 540 <= m <= 805:
                    B.append((m, o, h, l, c, v or 0))
            return sorted(B)
        except Exception:
            time.sleep(1 + 2 * k)
    return []


def hm(m):
    return "%02d:%02d" % (m // 60, m % 60)


def px(x):
    return ("%.2f" % x).rstrip("0").rstrip(".")


def play(B, i, e, stop, tgt):
    """從第 i 根之後一根一根看：先碰停損（同一根兩邊都碰到算停損）或目標；都沒有就 13:25 收盤賣"""
    for m, o, h, l, c, v in B[i + 1:]:
        if l <= stop:
            return min(o, stop), m, "碰到停損"
        if h >= tgt:
            return max(o, tgt), m, "碰到目標"
    return B[-1][4], B[-1][0], "收盤前沒碰到，13:25 賣出"


def scan(day, U, prev):
    trades = []
    for x in U:
        sid = x["id"]
        B = bars5(sid + (".TWO" if x.get("mkt") == "tpex" else ".TW"), day)
        if len(B) < 50:
            continue
        pc = prev.get(sid)
        first = [b for b in B if b[0] < 555]
        if not pc or len(first) < 3:
            continue
        hi, lo = max(b[2] for b in first), min(b[3] for b in first)
        mid = (hi + lo) / 2
        i15 = next(i for i, b in enumerate(B) if b[0] >= 555)
        # A 開盤區間突破＋爆量
        j = next((i for i in range(i15, len(B)) if B[i][0] <= 630 and B[i][4] > hi), None)
        if j is not None and B[j][4] > mid:
            av = stt.mean(b[5] for b in B[max(0, j - 6):j])
            if av and B[j][5] >= 2 * av:
                e = B[j][4]
                xp, xm, why = play(B, j, e, mid, e + (e - mid))
                trades.append({"date": day, "id": sid, "name": x["name"], "rule": "A 開盤區間突破＋爆量",
                               "setup": "09:00～09:15 區間 %s～%s（中間 %s）；%s 這根收 %s 突破上緣，量是前面平均的 %.1f 倍" % (
                                   px(lo), px(hi), px(mid), hm(B[j][0]), px(e), B[j][5] / av),
                               "entry": e, "etime": hm(B[j][0] + 5), "stop": mid, "target": e + (e - mid),
                               "exit": xp, "xtime": hm(xm + 5), "why": why, "vx": B[j][5] / av})
        # B 跳空跌深反彈
        if B[0][1] <= pc * 0.97:
            g = next((i for i in range(0, i15) if B[i][4] > B[0][1] and B[i][4] > B[i][1]), None)
            if g is not None:
                e = B[g][4]
                lw = min(b[3] for b in B[:g + 1])
                if e > lw:
                    xp, xm, why = play(B, g, e, lw, e + (e - lw))
                    trades.append({"date": day, "id": sid, "name": x["name"], "rule": "B 跳空跌深反彈",
                                   "setup": "昨收 %s，開盤 %s（%+.1f%%）；%s 這根收紅 %s 站上開盤價" % (
                                       px(pc), px(B[0][1]), (B[0][1] / pc - 1) * 100, hm(B[g][0]), px(e)),
                                   "entry": e, "etime": hm(B[g][0] + 5), "stop": lw, "target": e + (e - lw),
                                   "exit": xp, "xtime": hm(xm + 5), "why": why, "vx": 0})
    for t in trades:
        sh = int(BUDGET // t["entry"])
        t["shares"] = sh
        t["ret"] = t["exit"] / t["entry"] - 1 - COST
        t["pnl"] = round(sh * t["entry"] * t["ret"])
    return trades


def report(day, trades, log, ndays=0):
    L = ["🧪 模擬當沖紀錄｜%s（假想交易，沒有真的下單；只發給你）" % day]
    if not log:
        L += ["", "📘 這是什麼：每天收盤後，照兩個固定規則把今天重演一遍，記下「如果照規則做會怎樣」。累積 1～2 個月看真實成績，再決定要不要真的當沖。",
              "回測提醒：最近 60 天這兩個規則扣成本後平均每筆小賠（A −0.26%、B −0.19%），所以先模擬、不要真的下單。"]
    if not trades:
        L += ["", "今天沒有符合規則的交易（沒有爆量突破、也沒有跳空跌 3% 後收紅）。沒訊號就不做，也是紀律。"]
    else:
        win = sum(t["ret"] > 0 for t in trades)
        L += ["", "今天 %d 筆：賺 %d、賠 %d，合計 %s 元（每筆假想 10 萬、已扣成本）" % (len(trades), win, len(trades) - win, "{:+,}".format(sum(t["pnl"] for t in trades)))]
        srt = sorted(trades, key=lambda t: -t["pnl"])  # 教學用：賺最多的 2 筆＋賠最多的 2 筆，看成功和失敗各長什麼樣
        show = srt[:SHOW // 2] + [t for t in srt[::-1][:SHOW // 2] if t not in srt[:SHOW // 2]]
        for n, t in enumerate(show, 1):
            R = t["entry"] - t["stop"]
            L += ["", "%s %d. %s %s｜%s" % ("✅" if t["ret"] > 0 else "❌", n, t["id"], t["name"], t["rule"]),
                  "　① 訊號：%s" % t["setup"],
                  "　② 進場：%s 以 %s 買 %d 股（約 %s 元）" % (t["etime"], px(t["entry"]), t["shares"], "{:,}".format(round(t["shares"] * t["entry"]))),
                  "　③ 停損 %s（%s，每股最多賠 %s）、目標 %s（賺跟賠一樣多＝1R）" % (
                      px(t["stop"]), "區間中間：跌回來代表突破失敗" if t["rule"].startswith("A") else "當天最低：跌破代表沒人接", px(R), px(t["target"])),
                  "　④ 出場：%s %s，價格 %s" % (t["xtime"], t["why"], px(t["exit"])),
                  "　⑤ 結果：%+.2f%%（已扣成本 0.25%%），%s 元" % (t["ret"] * 100, "{:+,}".format(t["pnl"]))]
        if len(trades) > SHOW:
            rest = [t for t in trades if t not in show]
            L.append("（另外 %d 筆只記錄不詳列：%s%s）" % (len(rest), "、".join("%s%+.1f%%" % (t["name"], t["ret"] * 100) for t in rest[:12]), "…" if len(rest) > 12 else ""))
    allt = log + trades
    if allt:
        L.append("")
        for rule in ("A 開盤區間突破＋爆量", "B 跳空跌深反彈"):
            x = [t for t in allt if t["rule"] == rule]
            if x:
                L.append("📊 累計 %s：%d 筆、勝率 %.0f%%、平均每筆 %+.2f%%、合計 %s 元（%d 個交易日）" % (
                    rule, len(x), 100 * sum(t["ret"] > 0 for t in x) / len(x), 100 * stt.mean(t["ret"] for t in x),
                    "{:+,}".format(sum(t["pnl"] for t in x)), len({t["date"] for t in x})))
        if len(allt) < 30:
            L.append("　累積不到 30 筆，成績還不準，先繼續看。")
    days = ndays + 1
    L += ["", "💡 當沖小知識 %d：%s" % ((days - 1) % len(TIPS) + 1, TIPS[(days - 1) % len(TIPS)])]
    return "\n".join(L)


def main():
    path = next((a for a in sys.argv[1:] if a.endswith(".json")), "data.json")
    day = sys.argv[sys.argv.index("--date") + 1] if "--date" in sys.argv else dt.date.today().isoformat()
    d = json.load(open(path, encoding="utf-8"))
    log = json.load(open(LOG, encoding="utf-8")) if os.path.exists(LOG) else []
    if any(t.get("date") == day for t in log):
        print("今天已記錄過，略過")
        return
    # 昨收：data.json 的最後一天要早於今天（每晚報告 20:00 才更新）
    k = len(d["dates"]) - 1
    while k > 0 and d["dates"][k] >= day:
        k -= 1
    prev = {s["id"]: s["c"][k] for s in d["stocks"] if s["c"] and s["c"][k]}
    U = [x for _, x in sorted(((float(x["shares"]) * x["c"][k], x) for x in d["stocks"]
                               if not x["id"].startswith("00") and x.get("shares") and x["c"][k]), key=lambda z: -z[0])[:100]]
    probe = bars5("2330.TW", day)
    if len(probe) < 50:
        print("今天沒有完整的 5 分 K（休市或資料還沒好），略過")
        return
    trades = scan(day, U, prev)
    open(OUT, "w", encoding="utf-8").write(report(day, trades, [t for t in log if not t.get("empty")], len({t["date"] for t in log})))
    log += trades or [{"date": day, "empty": True}]
    json.dump(log, open(LOG, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    print("模擬當沖完成：%d 筆（明細只發 Discord，不印在公開紀錄）" % len(trades))


if __name__ == "__main__":
    main()
