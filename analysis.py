"""
analysis.py - 重點個股解析：每晚報告後面，逐檔說明為何入選、為何可能上漲、業務與上下游、循環股與否、目標價推估

資料來源：
  stock_profiles.json  公司固定資料（主要業務、上下游、優勢、上漲動能、循環股、風險）
  data.json            當晚的價格、法人、營收、財報（每晚重算）
  sop_plan.json        最後名單與交易計畫（參考買進區間、停損、第一目標）
  sop_config.json      模擬下單裡「已實際成交」的持股也會一起解析
沒有 profile 的股票只顯示數據部分，並註明「公司資料待補」。
"""
import json
import os

DIR = os.path.dirname(os.path.abspath(__file__))
_CACHE = {}


def _ld(name, dft):
    if name not in _CACHE:
        p = os.path.join(DIR, name)
        try:
            _CACHE[name] = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else dft
        except Exception:
            _CACHE[name] = dft
    return _CACHE[name]


# 原料新聞（fetch_finmind.MACRO_Q 的關鍵字 → 跟公司業務、上下游比對用的字）
RAW = {"鋼價 調漲": ["鋼"], "銅價": ["銅", "電線", "電纜"], "貨櫃 運價 SCFI": ["貨櫃"], "散裝 BDI": ["散裝", "大宗物資"],
       "塑化 報價": ["塑", "石化", "PVC", "乙烯"], "水泥 價格": ["水泥"], "面板 報價": ["面板"], "記憶體 報價": ["記憶體", "DRAM"],
       "紙價": ["紙"], "油價 OPEC": ["原油", "燃油", "油價"]}
MOVE = ("大漲", "大跌", "暴漲", "暴跌", "飆", "崩", "創高", "創低", "新高", "新低", "急漲", "急跌", "調漲", "調降", "減產", "停產", "漲價", "跌價")


def is_cyc(prof):
    return str((prof or {}).get("cyc", "")).startswith(("循環股", "偏循環"))


def cycle_zone(s, t=None):
    """循環股在「近 5 年平均低點～平均高點」的位置；不是循環股或沒有資料回傳 None
    zone：low（平均低點 +10% 以內）、high（平均高點 −10% 以內）、mid（中間）"""
    prof = _ld("stock_profiles.json", {}).get(s["id"])
    b = (_ld("cycle_bands.json", {}).get("bands") or {}).get(s["id"])
    if not is_cyc(prof) or not b:
        return None
    lo, hi = b["avg_lo"], b["avg_hi"]
    if hi <= lo * 1.15:  # 高低差不到 15%，沒有循環可以做
        return None
    c = s["c"][len(s["c"]) - 1 if t is None else t]
    zone = "low" if c <= lo * 1.10 else "high" if c >= hi * 0.90 else "mid"
    return {"lo": lo, "hi": hi, "c": c, "zone": zone, "pos": (c - lo) / (hi - lo) * 100, "n": b["to"] - b["from"] + 1,
            "news": raw_news(prof)}


def raw_news(prof):
    """跟這家公司原料／報價有關、而且是大漲大跌的新聞（最多 2 則）"""
    text = "".join(str((prof or {}).get(k, "")) for k in ("biz", "up", "down"))
    qs = [q for q, kw in RAW.items() if any(k in text for k in kw)]
    out = []
    for m in _ld("macro.json", {}).get("macro") or []:
        kw = RAW.get(m.get("q"), [])
        if m.get("q") in qs and any(w in m.get("title", "") for w in MOVE) and any(k in m.get("title", "") for k in kw):  # 標題要真的提到這個原料
            out.append(m["title"].rsplit(" - ", 1)[0])
        if len(out) >= 2:
            break
    return out


def cycle_text(z):
    """循環股位置說明（一句）"""
    where = {"low": "低檔區，可以分批買", "high": "高檔區，該分批賣、不要追", "mid": "中間位置"}[z["zone"]]
    at = "比平均低點還低" if z["c"] < z["lo"] else "比平均高點還高" if z["c"] > z["hi"] else "在 %d%% 位置" % round(z["pos"])
    s = "近 %d 年平均低點 %s、平均高點 %s，目前 %s %s（%s）" % (z["n"], px(z["lo"]), px(z["hi"]), px(z["c"]), at, where)
    if z["news"]:
        s += "；⚠️ 原料新聞：%s，價位可能要調整" % "／".join(z["news"])
    return s


def pct(a, b):
    return (a / b - 1) * 100 if b else float("nan")


def fmt(x, nd=1):
    return ("+" if x > 0 else "") + ("%.*f" % (nd, x)) + "%"


def px(x):
    """價格：去掉浮點誤差，最多 2 位小數"""
    return ("%.2f" % x).rstrip("0").rstrip(".")


def zh(n):
    n = round(n)
    return ("+" if n > 0 else "") + "{:,}".format(n)


def ma(c, n, t):
    return sum(c[t - n + 1:t + 1]) / n if t >= n - 1 else float("nan")


def macd(c, t=None):
    """MACD（12,26,9），算法和網頁版一樣：回傳 {dif, sig, cross: 幾天前交叉（正＝黃金、負＝死亡、None＝近 10 天沒交叉）}"""
    t = len(c) - 1 if t is None else t
    if t < 35:
        return None
    def ema(a, n):
        k, o, e = 2 / (n + 1), [], a[0]
        for i, x in enumerate(a):
            e = x * k + e * (1 - k) if i else a[0]
            o.append(e)
        return o
    a = c[:t + 1]
    e12, e26 = ema(a, 12), ema(a, 26)
    dif = [x - y for x, y in zip(e12, e26)]
    sig = ema(dif, 9)
    cross = None
    for j in range(t, max(t - 10, 1), -1):
        if dif[j] > sig[j] and dif[j - 1] <= sig[j - 1]:
            cross = t - j + 1
            break
        if dif[j] < sig[j] and dif[j - 1] >= sig[j - 1]:
            cross = -(t - j + 1)
            break
    return {"dif": dif[t], "sig": sig[t], "cross": cross, "hist": dif[t] - sig[t], "hist_prev": dif[t - 1] - sig[t - 1]}


def macd_text(m):
    """MACD 狀態一句話"""
    if not m:
        return ""
    zero = "零軸之上" if m["dif"] > 0 and m["sig"] > 0 else "零軸之下" if m["dif"] < 0 and m["sig"] < 0 else "在零軸附近"
    if m["cross"]:
        d = abs(m["cross"]) - 1
        when = "今天" if d == 0 else "%d 天前" % d
        if m["cross"] > 0:
            return "MACD %s黃金交叉、%s（%s）" % (when, zero, "偏多" if zero == "零軸之上" else "低檔轉強訊號")
        return "MACD %s死亡交叉、%s（%s）" % (when, zero, "高檔轉弱，留意" if zero == "零軸之上" else "偏弱")
    side = "DIF 在訊號線之上" if m["hist"] > 0 else "DIF 在訊號線之下"
    trend = "，紅柱變長" if m["hist"] > 0 and m["hist"] > m["hist_prev"] else "，紅柱縮短" if m["hist"] > 0 else \
        "，綠柱縮短（跌勢減緩）" if m["hist"] > m["hist_prev"] else "，綠柱變長"
    return "MACD %s、%s%s" % (side, zero, trend)


def facts(s, t):
    """從當晚資料算出數字與「可能上漲的理由」"""
    c, h, l, v = s["c"], s["h"], s["l"], s["v"]
    f = {"close": c[t], "chg1": pct(c[t], c[t - 1]), "chg5": pct(c[t], c[t - 5]),
         "chg20": pct(c[t], c[t - 20]), "chg60": pct(c[t], c[t - 60])}
    a = max(0, t - 239)
    hi, lo = max(h[a:t + 1]), min(l[a:t + 1])
    f.update(hi=hi, lo=lo, pos=(c[t] - lo) / (hi - lo) * 100 if hi > lo else 50)
    fi, it = s.get("fi") or [0] * len(c), s.get("it") or [0] * len(c)
    f["fi10"], f["it10"] = sum(fi[t - 9:t + 1]), sum(it[t - 9:t + 1])
    st = 0
    while st <= t and it[t - st] > 0:
        st += 1
    f["it_streak"] = st
    st = 0
    while st <= t and fi[t - st] > 0:
        st += 1
    f["fi_streak"] = st
    rev = s.get("rev") or []
    rv = {x["m"]: x["v"] for x in rev}
    yo = []
    for m in sorted(rv)[-3:]:
        y, mm = m.split("-")
        p = "%d-%s" % (int(y) - 1, mm)
        if rv.get(p, 0) > 0 and rv[m] > 0:  # 證券業等月營收可能是負的，算年增沒意義
            yo.append((m, pct(rv[m], rv[p])))
    f["rev_yoy"] = yo
    q = s.get("q") or []
    eps = [x.get("eps") for x in q[-4:] if x.get("eps") is not None]
    f["eps4"] = sum(eps) if len(eps) == 4 else None
    f["pe"] = c[t] / f["eps4"] if f["eps4"] and f["eps4"] > 0 else None
    f["yield"] = s.get("yield")
    m20, m20p, m60 = ma(c, 20, t), ma(c, 20, t - 5), ma(c, 60, t)
    hi20 = max(h[t - 20:t]) if t >= 20 else float("inf")
    v20 = sum(v[t - 20:t]) / 20 if t >= 20 else 0

    why = []  # 數據面「為何可能上漲」
    if len(yo) == 3 and all(y > 10 for _, y in yo):
        why.append("營收連 3 個月年增 10%% 以上（最新 %s 年增 %s）" % (yo[-1][0][5:].lstrip("0") + "月", fmt(yo[-1][1])))
    elif yo and yo[-1][1] > 20:
        why.append("最新月營收年增 %s" % fmt(yo[-1][1]))
    if f["it_streak"] >= 3:
        why.append("投信連買 %d 天（近 10 日 %s 張）" % (f["it_streak"], zh(f["it10"])))
    elif f["it10"] > 0 and f["it10"] > v20 * 0.2:
        why.append("投信近 10 日買超 %s 張" % zh(f["it10"]))
    if f["fi_streak"] >= 3:
        why.append("外資連買 %d 天（近 10 日 %s 張）" % (f["fi_streak"], zh(f["fi10"])))
    elif f["fi10"] > 0 and f["fi10"] > v20 * 0.3:
        why.append("外資近 10 日買超 %s 張" % zh(f["fi10"]))
    if c[t] > m20 and m20 > m20p:
        why.append("站上月線且月線上揚")
    if c[t] > hi20:
        why.append("突破近 20 日高點" + ("（帶量）" if v20 and v[t] > v20 * 1.5 else ""))
    if f["pos"] < 40:
        why.append("股價在一年區間的 %d%%，位階還低" % f["pos"])
    if f["pe"] and f["pe"] < 12:
        why.append("本益比 %.1f 倍，偏便宜" % f["pe"])
    if f["yield"] and f["yield"] >= 5:
        why.append("殖利率 %.1f%%" % f["yield"])
    # 集保大戶（每週）：千張大戶持股 %、50 張以下散戶持股 %
    hw = [x for x in (s.get("hw") or []) if x.get("big") is not None]
    f["hw"] = hw[-5:]
    if len(hw) >= 3 and hw[-1]["big"] > hw[-2]["big"] > hw[-3]["big"]:
        why.append("千張大戶持股連 2 週增加（%.1f%%）" % hw[-1]["big"])
    f["why"] = why
    f["m60"] = m60
    f["macd"] = macd(c, t)
    # 營收細節：最新月營收（億）、月增、年增、今年累計年增、創近幾個月新高
    ms = sorted(rv)
    if ms and rv[ms[-1]] > 0:
        m = ms[-1]
        y, mm = m.split("-")
        prev = ms[-2] if len(ms) >= 2 else None
        ytd = sum(rv[x] for x in ms if x[:4] == y)
        ytd0 = sum(rv.get("%d-%s" % (int(y) - 1, x[5:]), 0) for x in ms if x[:4] == y)
        nh = 0
        for x in reversed(ms[:-1]):
            if rv[x] >= rv[m]:
                break
            nh += 1
        f["rev"] = {"m": m, "v": rv[m] / 1e5, "mom": pct(rv[m], rv[prev]) if prev and rv[prev] > 0 else None,
                    "yoy": yo[-1][1] if yo and yo[-1][0] == m else None, "ytd": pct(ytd, ytd0) if ytd0 > 0 else None,
                    "high": nh if nh == len(ms) - 1 else nh, "all": nh == len(ms) - 1 and nh >= 12}
    # 籌碼細節
    f["fi5"], f["it5"] = sum(fi[t - 4:t + 1]), sum(it[t - 4:t + 1])
    f["fi20"], f["it20"] = sum(fi[t - 19:t + 1]), sum(it[t - 19:t + 1])
    mg, sh = s.get("mg") or [], s.get("sh") or []
    f["mg5"] = (mg[t] - mg[t - 5]) if len(mg) > t and mg[t] is not None and mg[t - 5] is not None else None
    f["ssr"] = sh[t] / mg[t] * 100 if len(sh) > t and sh[t] is not None and mg[t] else None
    # 技術面：均線排列、支撐、壓力
    m5 = ma(c, 5, t)
    f["ma"] = (m5, m20, m60)
    f["hi60"] = max(h[t - 59:t + 1]) if t >= 59 else hi
    return f


BREAKOUT = "量價突破"


def market_weak(plan, hist_path=None):
    """大盤是否偏弱：國際風險高，或 0050 收盤跌破 60 日均線（季線）。回傳原因（空字串＝不弱）"""
    why = []
    if plan.get("risk") == "高":
        why.append("國際風險高")
    try:
        import os
        hp = hist_path or os.path.join(os.path.dirname(os.path.abspath(__file__)), "market_hist.json")
        hist = json.load(open(hp, encoding="utf-8"))["hist"]
        c = [hist[d]["0050"][3] for d in sorted(hist) if hist[d].get("0050") and hist[d]["0050"][3]]
        if len(c) >= 60 and c[-1] < sum(c[-60:]) / 60:
            why.append("大盤（0050）跌破季線")
    except Exception:
        pass
    return "、".join(why)


def guard_breakout(plan, weak):
    """大盤偏弱或國際風險高時，只因「量價突破」入選的股票改成先觀望（回測：盤整偏弱時追突破平均 -7%）。回傳改了幾檔"""
    n = 0
    if not weak:
        return 0
    for r in plan.get("rows", []):
        st = r.get("strategies") or []
        if st and all(x == BREAKOUT for x in st) and r.get("state") != "hold":
            r["state"], r["hold_why"] = "hold", weak
            n += 1
    return n


def guard_cycle(plan, data):
    """循環股已在近幾年平均高點附近：改成先觀望（低點買、高點賣，不追高）。回傳改了幾檔"""
    by = {x["id"]: x for x in data.get("stocks", [])}
    n = 0
    for r in plan.get("rows", []):
        s = by.get(r.get("id"))
        z = cycle_zone(s) if s else None
        if z and z["zone"] == "high" and r.get("state") != "hold":
            r["state"], r["hold_why"] = "hold", "循環股已到近 %d 年平均高點 %s 附近" % (z["n"], px(z["hi"]))
            n += 1
    return n


def advise(s, t, row=None):
    """每一檔都要有的買賣建議（一行）。有交易計畫（sop_plan）就照計畫；沒有就依趨勢、過熱程度、波動自己算"""
    import exits
    tk = exits.tick
    z = cycle_zone(s, t)
    if z:  # 循環股：照近幾年平均低點買、平均高點賣（原料有大新聞時另外提醒）
        warn = "；⚠️ 原料新聞：%s，價位可能要調整" % "／".join(z["news"]) if z["news"] else ""
        if z["zone"] == "low":
            stop = tk(min(z["lo"], z["c"]) * 0.9)
            return "🟢 循環股低檔可買：接近近 %d 年平均低點 %s，分批買；目標平均高點 %s（%s）；跌破 %s 停損（比平均低點再低 10%%）%s" % (
                z["n"], px(z["lo"]), px(z["hi"]), fmt(pct(z["hi"], z["c"])), px(stop), warn)
        if z["zone"] == "high":
            return "🔴 循環股高檔：已到近 %d 年平均高點 %s 附近，不要買；有持股分批賣出%s" % (z["n"], px(z["hi"]), warn)
        base = advise(dict(s, id=""), t, row)  # 中間位置：照原本規則，再補上循環股價位
        return base + "｜循環股：最好等跌近平均低點 %s～%s 再買，漲到平均高點 %s 附近就賣%s" % (
            px(z["lo"]), px(tk(z["lo"] * 1.1)), px(z["hi"]), warn)
    if row and row.get("lo") and row.get("stop"):
        z = "%s～%s" % (px(row["lo"]), px(row["hi"]))
        tg = "，目標 %s" % px(row["t1"]) if row.get("t1") else ""
        if row.get("state") == "hold":
            return "⚪ 先觀望：%s，量價突破這時容易追高被套；等大盤轉強再考慮（參考 %s，跌破 %s 停損）" % (row.get("hold_why") or "大盤偏弱", z, px(row["stop"]))
        if row.get("state") == "ok":
            return "🟢 可買：%s 分批買，跌破 %s 停損%s" % (z, px(row["stop"]), tg)
        return "🟡 等拉回：跌到 %s 再買，跌破 %s 停損%s" % (z, px(row["stop"]), tg)
    c = s["c"]
    A, r = exits.atr(s, t), exits.rsi(c, t)
    m20, m20p, m10 = ma(c, 20, t), ma(c, 20, t - 5), ma(c, 10, t)
    a = max(0, t - 239)
    hi1y = max(s["h"][a:t + 1])
    if c[t] < m20 and m20 < m20p:
        return "⚪ 觀望：還在下跌趨勢（月線 %s 往下），收盤站回月線再考慮" % px(tk(m20))
    if r > 75 or c[t] / m20 - 1 > 0.12:
        return "🟡 不追高：等拉回月線 %s 附近再買，跌破 %s 停損" % (px(tk(m20)), px(tk(m20 - 2 * A)))
    lo, stop = tk(max(c[t] - A, m10)), tk(c[t] - 2 * A)
    tgt = tk(c[t] + 3 * A)
    tg = "目標 %s" % px(tgt) + ("、一年高點 %s" % px(hi1y) if hi1y > tgt * 1.02 else "")
    return "🟢 可買：%s～%s 分批買，跌破 %s 停損，%s" % (px(lo), px(c[t]), px(stop), tg)


def block(s, f, prof, row=None, hold=None):
    sid, name = s["id"], s["name"]
    L = ["【%s %s】收 %s（今日 %s）" % (sid, name, px(f["close"]), fmt(f["chg1"]))]
    if row:
        L.append("・入選策略：%s｜健檢 %s %s 分" % ("、".join(row.get("strategies") or []), row.get("grade"), row.get("score")))
    if hold:
        L.append("・你的持股：%s" % hold)
    if prof:
        L.append("・主要業務：" + prof["biz"])
        L.append("・上游：%s；下游：%s" % (prof["up"], prof["down"]))
        L.append("・優勢：" + prof["edge"])
    else:
        L.append("・產業：%s（公司資料待補）" % s.get("industry", ""))
    rs = list(f["why"])
    if prof:
        rs.append("題材：" + prof["drv"])
    L.append("・為何可能上漲：" + ("；".join(rs) if rs else "數據面沒有明顯訊號"))
    L.append("・最近走勢：5 日 %s、20 日 %s、60 日 %s；一年區間 %s～%s，目前在 %d%% 位置%s"
             % (fmt(f["chg5"]), fmt(f["chg20"]), fmt(f["chg60"]), px(f["lo"]), px(f["hi"]), f["pos"],
                "（接近一年高點，已漲一段）" if f["pos"] >= 90 else "（低檔）" if f["pos"] <= 30 else ""))
    z = cycle_zone(s)
    if z:
        L.append("・循環位置：" + cycle_text(z))
    r = f.get("rev")
    if r:
        x = ["%s月營收 %.1f 億" % (r["m"][5:].lstrip("0"), r["v"])]
        if r["mom"] is not None:
            x.append("月增 " + fmt(r["mom"]))
        if r["yoy"] is not None:
            x.append("年增 " + fmt(r["yoy"]))
        if r["ytd"] is not None:
            x.append("今年累計年增 " + fmt(r["ytd"]))
        if r["all"]:
            x.append("創有資料以來新高")
        elif r["high"] >= 6:
            x.append("創近 %d 個月新高" % (r["high"] + 1))
        L.append("・營收：" + "、".join(x))
    ch = []
    for nm, st, a5, a20 in (("外資", f["fi_streak"], f["fi5"], f["fi20"]), ("投信", f["it_streak"], f["it5"], f["it20"])):
        ch.append("%s%s（近 5 日 %s、20 日 %s 張）" % (nm, "連買 %d 天" % st if st >= 2 else "買超" if a5 > 0 else "賣超", zh(a5), zh(a20)))
    if f["mg5"] is not None:
        ch.append("融資 5 日%s %s 張%s" % ("增" if f["mg5"] >= 0 else "減", "{:,}".format(round(abs(f["mg5"]))),
                                         "（散戶退場、籌碼變乾淨）" if f["mg5"] < 0 and f["fi5"] + f["it5"] > 0 else
                                         "（散戶追進，留意）" if f["mg5"] > 0 and f["fi5"] + f["it5"] < 0 else ""))
    if f["ssr"] and f["ssr"] >= 10:
        ch.append("券資比 %.0f%%" % f["ssr"])
    hw = f.get("hw") or []
    if hw:
        x = hw[-1]
        t = "千張大戶持股 %.1f%%" % x["big"]
        if len(hw) >= 2:
            db, dr = x["big"] - hw[-2]["big"], x["ret"] - hw[-2]["ret"]
            t += "（比上週 %+.2f 個百分點）、散戶 %.1f%%（%+.2f）" % (db, x["ret"], dr)
            if db > 0 and dr < 0:
                t += "，大戶買、散戶賣，籌碼集中"
            elif db < 0 and dr > 0:
                t += "，大戶賣、散戶接，籌碼變亂"
        else:
            t += "、散戶 %.1f%%（%s 集保）" % (x["ret"], x["d"][5:].replace("-", "/"))
        ch.append(t)
    L.append("・籌碼：" + "；".join(ch))
    m5, m20, m60 = f["ma"]
    tech = []
    if m5 and m20 and m60:
        tech.append("均線多頭排列（5日>月線>季線）" if m5 > m20 > m60 else "均線空頭排列（5日<月線<季線）" if m5 < m20 < m60 else
                    "站上月線" if f["close"] > m20 else "在月線之下")
        if f["close"] < m60:
            tech.append("收盤 %s 已跌破季線 %s" % (px(f["close"]), px(m60)))
        if f.get("macd"):
            tech.append(macd_text(f["macd"]))
        sup = [("月線", m20), ("季線", m60)]
        sup = [(n, v) for n, v in sup if v < f["close"]]
        if sup:
            tech.append("支撐 " + "、".join("%s %s" % (n, px(v)) for n, v in sup))
        res = f["hi60"] if f["hi60"] > f["close"] * 1.01 else f["hi"] if f["hi"] > f["close"] * 1.01 else None
        if res:
            tech.append("壓力 %s（%s）" % (px(res), "近 3 個月高點" if res == f["hi60"] else "一年高點"))
        else:
            tech.append("在近期高點附近，上方沒有明顯壓力")
    if tech:
        L.append("・技術面：" + "；".join(tech))
    fund = []
    if f["eps4"] is not None:
        fund.append("近四季 EPS %.2f 元" % f["eps4"] + ("、本益比 %.1f 倍" % f["pe"] if f["pe"] else ""))
    if fund:
        L.append("・基本面：" + "；".join(fund))
    if prof:
        L.append("・是循環股嗎：" + prof["cyc"])
    tg = []
    if row and row.get("t1"):
        tg.append("第一目標 %s（%s）" % (px(row["t1"]), fmt(pct(row["t1"], f["close"]))))
    if f["hi"] > f["close"]:
        tg.append("一年高點 %s（%s）是下一道壓力" % (px(f["hi"]), fmt(pct(f["hi"], f["close"]))))
    if row and row.get("stop"):
        tg.append("跌破 %s（%s）停損" % (px(row["stop"]), fmt(pct(row["stop"], f["close"]))))
    if tg:
        L.append("・推估目標：" + "；".join(tg))
    if prof:
        L.append("・風險：" + prof["risk"])
    if hold:
        L.append("・建議：見最上方「持股賣出提醒」（續抱／減碼／賣出與停損）")
    else:
        L.append("・建議：" + advise(s, len(s["c"]) - 1, row))
    return "\n".join(L)


def build(data, cfg, plan, profiles, top=6):
    by = {s["id"]: s for s in data["stocks"]}
    t = len(data["dates"]) - 1
    out = []
    # 已實際成交的持股
    oc = cfg.get("orders") or {}
    held = {}
    for o in (oc.get("list") if isinstance(oc, dict) else oc) or []:
        if o.get("done") and not str(o.get("side", "b")).startswith("s"):
            held.setdefault(str(o["id"]), []).append("%s 買進 %s × %s 股" % (o.get("date", ""), o.get("price"), o.get("qty")))
    rows = [r for r in plan.get("rows", []) if not str(r["id"]).startswith("00")]
    rows.sort(key=lambda r: (r.get("state") != "ok", -(r.get("score") or 0)))
    pick = rows[:top]
    rmap = {r["id"]: r for r in plan.get("rows", [])}
    ids = list(dict.fromkeys(list(held) + [r["id"] for r in pick]))
    for sid in ids:
        s = by.get(sid)
        if not s or t < 60:
            continue
        out.append(block(s, facts(s, t), profiles.get(sid), rmap.get(sid), "、".join(held.get(sid, [])) or None))
    if not out:
        return ""
    who = "持股" if not pick else ("持股與名單前 %d 檔" % top if held else "名單前 %d 檔" % top)
    head = "📌 重點個股解析（%s 收盤，%s）" % (data["dates"][t], who)
    tail = "目標價是依近期高點與波動（ATR）算的參考價，不是保證；公司資料為整理的公開資訊，不是投資建議。"
    return "\n\n".join([head] + out + [tail])


def main():
    load = lambda n, d=None: json.load(open(os.path.join(DIR, n), encoding="utf-8")) if os.path.exists(os.path.join(DIR, n)) else d
    text = build(load("data.json"), load("sop_config.json", {}), load("sop_plan.json", {}), load("stock_profiles.json", {}))
    open(os.path.join(DIR, "report_analysis.txt"), "w", encoding="utf-8").write(text)
    print(text)


if __name__ == "__main__":
    main()
