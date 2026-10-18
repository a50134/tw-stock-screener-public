"""
morning_check.py - 早上開盤檢查（每日 SOP 步驟 ④）：抓開盤價，判斷可買／等待／不要買，發到 LINE 與 Discord

用法：
  python morning_check.py            # 等到 09:01 開盤後抓價、判斷並發送（雲端每天 08:35 啟動）
  python morning_check.py --now      # 不等待，立刻用目前的價格判斷
  python morning_check.py --dry-run  # 只印出結果，不發送

名單來自前一晚 daily_report.js 產生的 sop_plan.json（參考買進區間、不追價、停損、健檢）。
判斷規則與網頁「每日 SOP」步驟 ④ 相同。報價來源：證交所基本市況報導（mis.twse.com.tw）。
開頭附「開盤前觀察」（premarket.py）：台指期夜盤、美股收盤、美股期貨，評估開高或開低（同一則發送，早上只發一次）。
持股（前一晚 exits.py 產生的 sell_plan.json）也一起檢查：開盤就跌破停損提醒賣出、到目標提醒減碼。
"""
import datetime as dt
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.parse
import urllib.request

from daily_run import twse_holidays, is_trading, sent_today, mark_sent  # 共用休市日判斷與防重複

DIR = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0"}


def quotes(ids):
    """回傳 {代號: (開盤價, 最新價, 昨收)}；還沒成交的價格是 None"""
    out = {}
    for i in range(0, len(ids), 20):  # 上市、上櫃都查（只有其中一個會有資料）
        ch = "|".join("%s_%s.tw" % (m, x) for x in ids[i:i + 20] for m in ("tse", "otc"))
        url = "https://mis.twse.com.tw/stock/api/getStockInfo.jsp?json=1&delay=0&ex_ch=" + urllib.parse.quote(ch)
        with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=20, context=ssl.create_default_context()) as r:
            for x in json.loads(r.read().decode("utf-8")).get("msgArray", []):
                num = lambda v: float(v) if v not in (None, "", "-") else None
                if x.get("c") and (num(x.get("o")) or num(x.get("z")) or num(x.get("y"))):
                    out[x.get("c")] = (num(x.get("o")), num(x.get("z")), num(x.get("y")))
        time.sleep(0.5)
    return out


def verdict(r, px, P):
    """與網頁步驟 ④ 相同的判斷；回傳 (代號, 文字, 理由)"""
    prev, lo, chase, stop = r["prev"], r["lo"], r["chase"], r["stop"]
    g = (px / prev - 1) * 100
    if r.get("grade") == "D":
        return "no", "不要買", "健檢 D 級"
    if px <= stop:
        return "no", "不要買", "已跌破停損價 %s" % fmt(stop)
    if g >= P["gapNo"]:
        return "no", "不要買", "跳空大漲 %+.1f%%，追高風險大" % g
    if px > chase:
        return "wait", "等待", "高於不追價 %s，掛單在 %s 以下等回檔" % (fmt(chase), fmt(chase))
    if px < lo:
        if g <= -P["gapDown"]:
            return "no", "不要買", "開低 %+.1f%% 又跌破區間下緣 %s，走勢轉弱" % (g, fmt(lo))
        return "wait", "等待", "低於區間下緣 %s，等止跌收紅再買" % fmt(lo)
    risk = P.get("risk")
    return "buy", "可買（減半）" if risk == "高" else "可買", "在買進區間內" + ("，國際風險高只買一半" if risk == "高" else "，國際風險中分兩批買" if risk == "中" else "")


def hold_verdict(h, px, y):
    """持股開盤提醒；回傳 (群組, 文字)"""
    g = (px / y - 1) * 100 if y else 0
    head = "%s %s　開 %s（%+.1f%%）　成本 %s × %d 股" % (h["id"], h["name"], fmt(px), g, fmt(h["cost"]), h["qty"])
    if px <= h["stop"]:
        return "sell", head + "\n　🔴 賣出：開盤就跌破停損 %s，照計畫賣出，不要等反彈" % fmt(h["stop"])
    if px >= h["t2"]:
        return "trim", head + "\n　🟠 減碼：開盤到第二目標 %s，可再賣一部分" % fmt(h["t2"])
    if h.get("t1") and px >= h["t1"]:
        return "trim", head + "\n　🟠 減碼：開盤到第一目標 %s，先賣一半，剩下的跌破 %s 再賣" % (fmt(h["t1"]), fmt(max(h["stop"], h["cost"])))
    if g <= -4:
        return "warn", head + "\n　🟡 開低 %+.1f%%，離停損 %s 還有 %.1f%%，盤中留意" % (g, fmt(h["stop"]), (px / h["stop"] - 1) * 100)
    return "keep", head + "\n　🟢 續抱：停損 %s%s" % (fmt(h["stop"]), "、第一目標 %s" % fmt(h["t1"]) if h.get("t1") else "")


def fmt(v):
    return ("%.2f" % v) if v < 100 else ("%.1f" % v)


def send_morning(imgs):
    """Discord：文字＋圖卡附檔（同時拿到圖片網址）；LINE 群發：只發圖卡（拿不到網址才發文字），同一次發送只算 1 則"""
    py, lp = sys.executable, os.path.join(DIR, "discord_files.json")
    if os.path.exists(lp):
        os.remove(lp)
    cmd = [py, "send_report.py", "morning_report.txt", "--discord-only"]
    for a in imgs:
        cmd += ["--attach", os.path.relpath(a, DIR)]
    ok = subprocess.run(cmd, cwd=DIR).returncode == 0
    links = json.load(open(lp, encoding="utf-8")) if os.path.exists(lp) else {}
    pics = [{"type": "image", "originalContentUrl": links[os.path.basename(x)], "previewImageUrl": links[os.path.basename(x)]}
            for x in imgs if os.path.basename(x) in links][:4]
    print("LINE 附加：圖卡 %d 張" % len(pics), flush=True)
    cmd = [py, "send_report.py", "morning_report.txt", "--line-only"]
    if pics:
        with open(os.path.join(DIR, "morning_extra.json"), "w", encoding="utf-8") as f:
            json.dump(pics, f, ensure_ascii=False)
        cmd += ["--images-only", "--extra", "morning_extra.json"]
    elif imgs:
        print("⚠️ 圖卡有產生但拿不到 Discord 檔案網址，LINE 改發文字；Discord 回傳：", list(links), flush=True)
    ok = subprocess.run(cmd, cwd=DIR).returncode == 0 or ok
    if not ok:
        raise RuntimeError("Discord 與 LINE 都發送失敗")


def main():
    now_mode, dry, force = "--now" in sys.argv, "--dry-run" in sys.argv, "--force" in sys.argv
    today = dt.date.today()
    hol = twse_holidays()
    if not is_trading(today, hol) and not force:
        print("今天休市，不做開盤檢查。")
        return
    if sent_today("morning") and not (force or dry):
        print("今天的開盤檢查已經發送過，不重複發送。")
        return
    if dt.datetime.now().time() > dt.time(13, 30) and not (now_mode or force):
        print("已經收盤（排程延遲太久），今天不發送開盤檢查。")
        return
    path = os.path.join(DIR, "sop_plan.json")
    if not os.path.exists(path):
        print("找不到 sop_plan.json（前一晚沒有產生名單），不做開盤檢查。")
        return
    P = json.load(open(path, encoding="utf-8"))
    prev_day = today - dt.timedelta(days=1)
    while not is_trading(prev_day, hol):
        prev_day -= dt.timedelta(days=1)
    if P.get("date") != prev_day.isoformat() and not force:
        print("名單日期 %s 不是前一個交易日 %s，可能前一晚沒有執行，不發送。" % (P.get("date"), prev_day))
        return
    import brief  # 只檢查前一晚精簡報告推薦的那幾檔（其餘前一晚已說先不建議）
    ok, wait, rest = brief.pick(P)
    rows = [r for r in ok + wait if r.get("lo") and r.get("chase") and r.get("stop")]
    sp = os.path.join(DIR, "sell_plan.json")  # 持股的停損與目標（前一晚 exits.py 產生）
    SP = json.load(open(sp, encoding="utf-8")) if os.path.exists(sp) else {}
    holds = SP.get("holds", []) if SP.get("date") == prev_day.isoformat() or force else []

    # 開盤前觀察：台指期夜盤、美股、美股期貨（併在開盤檢查同一則，LINE 每天只發早晚兩次、省免費則數）
    pre = ""
    try:
        import premarket
        pre = premarket.overview()[0]
    except Exception as e:
        print("開盤前觀察失敗，略過：", e, flush=True)
    if not rows and not holds:  # 沒有名單也沒有持股：只發開盤前觀察
        print(pre or "昨晚名單沒有股票、也沒有持股，不發送。", flush=True)
        if pre and not dry:
            with open(os.path.join(DIR, "morning_report.txt"), "w", encoding="utf-8") as f:
                f.write("☀️ 條件選股室｜%s\n%s" % (today.isoformat(), pre))
            subprocess.run([sys.executable, "send_report.py", "morning_report.txt"], cwd=DIR, check=True)
            mark_sent("morning")
        return

    # 等到 09:01 開盤後（開盤價在 09:00 集合競價產生），最晚 09:04 前一定發送
    if not now_mode:
        start = dt.datetime.combine(today, dt.time(9, 1, 0))
        wait = (start - dt.datetime.now()).total_seconds()
        if wait > 0:
            print("等待開盤，%.0f 秒後抓價" % wait, flush=True)
            time.sleep(wait)
    deadline = dt.datetime.now() + dt.timedelta(minutes=3)
    ids = list(dict.fromkeys([r["id"] for r in rows] + [h["id"] for h in holds]))
    q = {}
    while True:
        try:
            q = quotes(ids)
        except Exception as e:
            print("抓報價失敗：", e, flush=True)
        missing = [x for x in ids if not q.get(x) or (q[x][0] is None and q[x][1] is None)]
        if not missing or dt.datetime.now() >= deadline:
            break
        time.sleep(20)

    groups = {"buy": [], "wait": [], "no": [], "none": []}
    for r in rows:
        o, z, y = q.get(r["id"], (None, None, None))
        px = o or z
        if px is None:
            groups["none"].append((0, "・%s %s：還沒有開盤價，等開盤後自己看區間 %s～%s" % (r["id"], r["name"], fmt(r["lo"]), fmt(r["hi"]))))
            continue
        r = dict(r, prev=y or r["prev"])  # 漲跌幅用證交所的昨收
        k, t, why = verdict(r, px, P)
        g = (px / r["prev"] - 1) * 100
        groups[k].append((-(r.get("score") or 0), "・%s %s 開 %s（%+.1f%%）｜%s：%s｜停損 %s" % (
            r["id"], r["name"], fmt(px), g, t, why, fmt(r["stop"]))))
    L = ["☀️ 條件選股室｜開盤檢查 %s %s" % (today.isoformat(), dt.datetime.now().strftime("%H:%M")), ""]
    try:  # 開盤後重抓一次，用最新的美股期貨與台指期
        import premarket
        pre = premarket.overview()[0] or pre
    except Exception:
        pass
    if pre:
        L += pre.splitlines() + [""]
    priv = ""
    if holds:
        hg = {"sell": [], "trim": [], "warn": [], "keep": []}
        for h in holds:
            o, z, y = q.get(h["id"], (None, None, None))
            if (o or z) is None:
                hg["warn"].append("%s %s：還沒有開盤價，停損 %s" % (h["id"], h["name"], fmt(h["stop"])))
                continue
            k, txt = hold_verdict(h, o or z, y or h["close"])
            hg[k].append(txt)
        # 持股只推給自己（不放進群發）；全部續抱的日子不另外發，省 LINE 則數
        if hg["sell"] or hg["trim"] or hg["warn"]:
            H = ["🔒 只給你｜持股開盤檢查 %s %s" % (today.isoformat(), dt.datetime.now().strftime("%H:%M"))]
            for k in ("sell", "trim", "warn", "keep"):
                H += hg[k]
            priv = "\n".join(H)
    L += ["檢查昨晚推薦的 %d 檔（%s 收盤篩選，國際風險：%s）；其餘 %d 檔昨晚已說先不建議" % (len(rows), P.get("date"), P.get("risk"), len(rest)), ""]
    # 精簡：每組只列分數最高的幾檔（一檔一行、都有建議），其餘只列名字並說明一律照該組建議
    for k, title, top in (("buy", "🟢 可買", 8), ("wait", "🟡 等待", 4), ("no", "🔴 不要買", 4), ("none", "⚪ 沒有報價", 4)):
        g = [x[1] for x in sorted(groups[k], key=lambda x: x[0])]
        if g:
            L += ["%s（%d 檔）" % (title, len(g))] + g[:top]
            if len(g) > top:
                L.append("　其餘 %d 檔同樣%s：%s" % (len(g) - top, {"buy": "可買（在區間內分批）", "wait": "先等待、掛單在區間內", "no": "今天不要買", "none": "等開盤再看"}[k],
                                                  "、".join(x.split(" ")[1] for x in g[top:])))
            L.append("")
    L.append("依開盤價與固定規則判斷，不是投資建議。")
    text = "\n".join(L)
    print(text)
    with open(os.path.join(DIR, "morning_report.txt"), "w", encoding="utf-8") as f:
        f.write(text)
    if priv:
        print("\n（持股開盤檢查只發 Discord，不印在公開的執行紀錄）")
        with open(os.path.join(DIR, "morning_private.txt"), "w", encoding="utf-8") as f:
            f.write(priv)
    imgs = []
    try:  # 圖卡：開盤前觀察＋每一檔的開盤價與建議（LINE 只發圖，跟晚上一樣）
        import glob
        import morning_img
        for x in glob.glob(os.path.join(DIR, "開盤_*.*")):
            os.remove(x)
        secs = [(k, "%s（%d 檔）" % (t, len(groups[k])), [x[1] for x in sorted(groups[k], key=lambda x: x[0])])
                for k, t in (("buy", "可買"), ("wait", "等待"), ("no", "不要買"), ("none", "沒有報價"))]
        imgs = morning_img.build(L[0], "檢查昨晚推薦的 %d 檔（%s 收盤篩選，國際風險：%s）" % (len(rows), P.get("date"), P.get("risk")), pre, secs)
        print("開盤圖卡：", "、".join(os.path.basename(x) for x in imgs), flush=True)
    except Exception as e:
        print("開盤圖卡產生失敗，LINE 改發文字：", e, flush=True)
    if dry:
        return
    send_morning(imgs)
    if priv:
        subprocess.run([sys.executable, "send_report.py", "morning_private.txt", "--discord-only"], cwd=DIR, check=False)  # 持股提醒只給自己：發 Discord，不佔 LINE 額度
    mark_sent("morning")


if __name__ == "__main__":
    main()
