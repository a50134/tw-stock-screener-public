"""
lookup.py - 查個股：輸入代號或名稱，馬上從 FinMind 抓資料分析（不用等早晚的排程）

內容跟晚上報告的個股分析一樣：主要業務、上下游、為何可能上漲、最近走勢、營收、籌碼（外資／投信／融資）、
技術面（均線、支撐、壓力）、基本面、是否循環股（低點買、高點賣的價位）、推估目標、買賣建議，再加最近新聞（利多／利空）
你有持股的話，Discord 版會多一段「持股賣出提醒」（只發 Discord，不印在公開的執行紀錄）

用法：python lookup.py 1605 台積電 2603      # 代號或名稱都可以，空白或逗號分隔
      python lookup.py 1605 --dry           # 只印在畫面，不發 Discord
結果：lookup.txt（公開版，不含持股）、Discord（含持股提醒）
"""
import json
import os
import re
import subprocess
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
DRY = "--dry" in sys.argv


def resolve(words):
    """名稱 → 代號；回傳 (代號清單, 找不到的字)"""
    import fetch_finmind
    fetch_finmind.TOKEN = (os.environ.get("FINMIND_TOKEN") or "").strip()
    ids, miss, info = [], [], None
    for w in words:
        if re.fullmatch(r"\d{4,6}[A-Z]?", w):
            ids.append(w)
            continue
        if info is None:
            info = fetch_finmind.get("TaiwanStockInfo")
        hit = [d["stock_id"] for d in info if d.get("stock_name") == w] or \
              [d["stock_id"] for d in info if w in str(d.get("stock_name", "")) and re.fullmatch(r"\d{4}", d["stock_id"])]
        if hit:
            ids.append(hit[0])
        else:
            miss.append(w)
    return list(dict.fromkeys(ids)), miss


def add_band(sid):
    """循環股但還沒有「近 5 年平均高低點」：現在算一份（只放在這次執行，不存檔）"""
    import analysis
    import cycle
    import datetime as dt
    bands = analysis._ld("cycle_bands.json", {}).setdefault("bands", {})
    if sid in bands or not analysis.is_cyc(analysis._ld("stock_profiles.json", {}).get(sid)):
        return
    y = dt.date.today().year
    try:
        ys = cycle.twse_years(sid)
    except Exception:
        ys = {}
    if len(ys) < 4:
        try:
            ys = cycle.finmind_years(sid, y - cycle.YEARS - 1)
        except Exception:
            ys = {}
    b = cycle.band(ys, y)
    if b:
        bands[sid] = b


def news_lines(s, n=5):
    import alert
    out = []
    seen = set()
    for x in s.get("news") or []:
        k = x["title"].rsplit(" - ", 1)[0]
        if k in seen or "個股概覽" in k:  # 重複的、沒內容的股價頁不算新聞
            continue
        seen.add(k)
        if len(out) >= n:
            break
        g = alert.tone(x["title"], alert.UP + alert.GOOD, alert.DOWN + alert.BAD)
        out.append("　%s %s %s" % (x["d"][5:].replace("-", "/"), "🟢利多" if g > 0 else "🔴利空" if g < 0 else "⚪", x["title"].rsplit(" - ", 1)[0]))
    return out


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if "--event" in sys.argv:  # GitHub 手動執行：從事件檔讀輸入，不經過環境變數（執行紀錄不會顯示查了什麼）
        args = [str((json.load(open(os.environ["GITHUB_EVENT_PATH"], encoding="utf-8")).get("inputs") or {}).get("ids", ""))]
    words = [w for a in args for w in re.split(r"[\s,，、]+", a) if w]
    if not words:
        print("請輸入股票代號或名稱，例如：python lookup.py 1605 台積電")
        return
    ids, miss = resolve(words)
    if miss:
        print("有 %d 個找不到（名稱打錯或已下市）" % len(miss))  # 不印查了什麼（公開執行紀錄）
    if not ids:
        sys.exit(1)
    # 抓一年多的日K、法人、融資、營收、財報、新聞，以及國際／原料新聞
    r = subprocess.run([sys.executable, os.path.join(DIR, "fetch_finmind.py")] + ids + ["--days", "260", "--out", "lookup.json"], cwd=DIR)
    if r.returncode or not os.path.exists(os.path.join(DIR, "lookup.json")):
        print("FinMind 資料抓取失敗")
        sys.exit(1)
    try:  # 集保大戶持股：用每晚存的歷史（沒有就現在抓最新一週）
        import tdcc
        if not os.path.exists(tdcc.HIST):
            tdcc.update()
        tdcc.merge(os.path.join(DIR, "lookup.json"))
    except Exception as e:
        print("集保大戶資料失敗，略過：", type(e).__name__)
    data = json.load(open(os.path.join(DIR, "lookup.json"), encoding="utf-8"))
    json.dump({"macro": data.get("macro") or []}, open(os.path.join(DIR, "macro.json"), "w", encoding="utf-8"), ensure_ascii=False)
    import analysis
    import exits
    prof = analysis._ld("stock_profiles.json", {})
    cfg = json.load(open(os.path.join(DIR, "sop_config.json"), encoding="utf-8")) if os.path.exists(os.path.join(DIR, "sop_config.json")) else {}
    H = exits.holdings(cfg)
    live = {}
    try:  # 證交所即時報價（盤中約 5 秒更新；收盤後就是今天收盤價）
        import datetime as dt
        from morning_check import quotes
        live = quotes([x["id"] for x in data["stocks"]])
        live_t = dt.datetime.now().strftime("%m/%d %H:%M")
    except Exception as e:
        print("即時報價抓取失敗，只用收盤資料：", type(e).__name__)
    pub, priv = [], []
    for s in data["stocks"]:
        t = len(s["c"]) - 1
        if t < 60:
            pub.append("【%s %s】上市不到 3 個月，資料太少，先不分析" % (s["id"], s["name"]))
            priv.append(pub[-1])
            continue
        add_band(s["id"])
        L = [analysis.block(s, analysis.facts(s, t), prof.get(s["id"]))]
        o, z, y = live.get(s["id"], (None, None, None))
        if z or o:
            p_ = z or o
            L.append("・即時價（%s 證交所）：%s%s，開盤 %s%s" % (
                live_t, exits.px(p_), "（%+.2f%%）" % ((p_ / y - 1) * 100) if y else "", exits.px(o) if o else "—",
                "" if z else "（收盤集合競價中，最新價用開盤價）"))
        nl = news_lines(s)
        if nl:
            L.append("・最近新聞：\n" + "\n".join(nl))
        pub.append("\n".join(L))
        if s["id"] in H:  # 你的持股：加上賣出提醒（只發 Discord）
            lv, act, rs, tips, P = exits.check(s, data["dates"], H[s["id"]], prof.get(s["id"]))
            L.append("・你的持股：%s｜%s｜收盤跌破 %s 停損%s" % (act, "；".join(rs) if rs else "照計畫抱著", exits.px(P["stop"]),
                                                       "，%s 先賣一半" % exits.px(P["t1"]) if P.get("hf") and P["close"] < P["t1"] else ""))
        priv.append("\n".join(L))
    head = "🔍 查個股（%s 收盤資料）" % data["asOf"]
    tail = "依 FinMind 公開資料與固定規則整理，不是投資建議。"
    text_pub = "\n\n".join([head] + pub + [tail])
    open(os.path.join(DIR, "lookup.txt"), "w", encoding="utf-8").write(text_pub)
    open(os.path.join(DIR, "lookup_full.txt"), "w", encoding="utf-8").write("\n\n".join([head] + priv + [tail]))  # 完整版（存回私人專案給 Claude 讀）
    if DRY:
        print("\n\n".join([head] + priv + [tail]))
        return
    url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    if url:
        import send_report
        send_report.send_discord(url, "\n\n".join([head] + priv + [tail]))
        print("已發到 Discord：%d 檔" % len(priv))
    else:
        print("沒有設定 DISCORD_WEBHOOK_URL，只存成 lookup.txt")


if __name__ == "__main__":
    main()
