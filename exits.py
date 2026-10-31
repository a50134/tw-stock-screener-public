"""
exits.py - 持股賣出提醒：你告訴我買了什麼（sop_config.json 的 orders，done: true），每晚檢查該不該賣、為什麼

每檔持股算出：
  停損價   買進價 − 2 倍 ATR（最多 −8%）；漲到 +2 ATR 後拉到買進價（保本）；漲 15% 以上改用「最高收盤 − 2.5 ATR」移動停利
  第一目標 買進價 + 3 倍 ATR：到了先賣一半，剩下的用保本／移動停利抱著
  第二目標 一年高點（壓力區）；已經超過就用買進價 + 6 ATR
每晚檢查（收盤價）：
  賣出：跌破停損／移動停利、跌破季線（持有 5 天以上）
  減碼：到第一目標、短線過熱（高於月線 15% 或 RSI > 80）、到第二目標
  注意：跌破月線且月線下彎、法人連賣、營收連 2 個月年減、抱 20 天以上還沒漲 3%
結果：報告最前面的「🔔 持股賣出提醒」，以及 sell_plan.json（隔天早上開盤檢查用：開盤就跌破停損或到目標會再提醒一次）
"""
import json
import os

DIR = os.path.dirname(os.path.abspath(__file__))


def px(x):
    return ("%.2f" % x).rstrip("0").rstrip(".")


def pct(a, b):
    return (a / b - 1) * 100


def fmt(x):
    return ("+" if x > 0 else "") + "%.1f%%" % x


def tick(p):
    """台股升降單位，價格取整到可以掛單的價位"""
    for lim, t in ((10, .01), (50, .05), (100, .1), (500, .5), (1000, 1)):
        if p < lim:
            return round(round(p / t) * t, 2)
    return round(p / 5) * 5


def atr(s, t, n=14):
    c, h, l = s["c"], s["h"], s["l"]
    a = max(1, t - n + 1)
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(a, t + 1)]
    return sum(tr) / len(tr) if tr else c[t] * 0.03


def rsi(c, t, n=14):
    if t < n:
        return 50
    up = sum(max(c[i] - c[i - 1], 0) for i in range(t - n + 1, t + 1))
    dn = sum(max(c[i - 1] - c[i], 0) for i in range(t - n + 1, t + 1))
    return 100 if dn == 0 else 100 - 100 / (1 + up / dn)


def ma(c, n, t):
    return sum(c[t - n + 1:t + 1]) / n if t >= n - 1 else None


def holdings(cfg):
    """把已實際成交的買賣合併成持股：{代號: {qty, cost(均價), date(第一次買進日), lots[]}}"""
    oc = cfg.get("orders") or {}
    H = {}
    for o in sorted((oc.get("list") if isinstance(oc, dict) else oc) or [], key=lambda o: str(o.get("date", ""))):
        if not o.get("done"):
            continue
        sid, q, p = str(o["id"]), int(o.get("qty") or 1000), float(o["price"])
        h = H.setdefault(sid, {"qty": 0, "cost": 0.0, "date": o.get("date", ""), "lots": [], "sold": 0})
        if str(o.get("side", "b")).startswith("s"):
            h["sold"] += min(q, h["qty"])
            h["qty"] = max(0, h["qty"] - q)
            h["lots"].append("%s 賣出 %s × %d 股" % (o.get("date", ""), px(p), q))
        else:
            if h["qty"] == 0:
                h["date"], h["cost"], h["sold"] = o.get("date", ""), 0.0, 0
            h["cost"] = (h["cost"] * h["qty"] + p * q) / (h["qty"] + q)
            h["qty"] += q
            h["lots"].append("%s 買進 %s × %d 股" % (o.get("date", ""), px(p), q))
    for sid, v in ((oc.get("holds_stop") if isinstance(oc, dict) else None) or {}).items():  # 自訂停損 {代號: 價格}
        if str(sid) in H:
            H[str(sid)]["stop"] = float(v)
    for sid, v in ((oc.get("holds_plan") if isinstance(oc, dict) else None) or {}).items():  # 你自己決定的賣法 {代號: {sell: [低, 高], stop: 價格}}
        if str(sid) in H:
            H[str(sid)]["plan"] = v
    return {k: v for k, v in H.items() if v["qty"] > 0}


def check(s, dates, h, prof=None):
    """回傳 (等級, 動作, 理由清單, 提醒清單, 價位 dict)；等級 3 賣出、2 減碼、1 注意、0 續抱"""
    c, v = s["c"], s["v"]
    t = len(c) - 1
    E = h["cost"]
    t0 = next((i for i, d in enumerate(dates) if d >= h["date"]), t)
    held = t - t0  # 買進後經過幾個交易日
    A0, A = atr(s, max(t0 - 1, 1)), atr(s, t)  # 買進前一天的波動（定停損、目標）、今天的波動（移動停利）
    peak = max(c[t0:t + 1])
    gain, pg = pct(c[t], E), pct(peak, E)

    stop, why_stop = (tick(E - 2 * A0), "買進價 − 2 倍日波動（ATR %s）" % px(A0)) if 2 * A0 < E * 0.08 else (tick(E * 0.92), "買進價 −8%（波動大，最多賠 8%）")
    if peak >= E + 2 * A0 and E > stop:
        stop, why_stop = tick(E), "曾漲到 %s（%s），停損拉到買進價保本" % (px(peak), fmt(pg))
    if pg >= 15 and peak - 2.5 * A > stop:
        stop, why_stop = tick(peak - 2.5 * A), "移動停利：最高收盤 %s − 2.5 倍日波動" % px(peak)
    if h.get("stop") and h["stop"] > stop:  # 使用者自己設定的停損（sop_config.json 的 holds_stop），比規則高就用它
        stop, why_stop = tick(h["stop"]), "你設定的停損" + ("（成本價保本）" if abs(h["stop"] - E) < 0.01 else "")
    t1 = tick(E + 3 * A0)
    a = max(0, t - 239)
    hi1y = max(s["h"][a:t + 1])
    t2 = tick(hi1y) if hi1y > t1 * 1.02 else tick(E + 6 * A0)
    why_t2 = "一年高點（套牢賣壓）" if hi1y > t1 * 1.02 else "買進價 + 6 倍日波動"
    up = h.get("plan") or {}  # 你自己決定的賣法優先：賣價區間、停損（取代規則的保本／移動停利）
    sz = [float(x) for x in (up.get("sell") or [])]
    if up.get("stop"):
        stop, why_stop = tick(float(up["stop"])), "你設定的停損"
    if sz:
        t1, t2, why_t2 = tick(sz[0]), tick(sz[-1]), "你設定的賣價"
    hf = float(up["half"]) if up.get("half") else None  # 你設定的「先賣一半」價位
    if hf:
        t1 = tick(hf)

    sell, trim, warn = [], [], []
    if c[t] <= stop:
        sell.append("收盤 %s 跌破%s %s（%s）" % (px(c[t]), "停損" if stop < E else "保本／移動停利", px(stop), why_stop))
    m20, m20p, m60 = ma(c, 20, t), ma(c, 20, t - 5), ma(c, 60, t)
    if m60 and c[t] < m60 and held >= 5 and c[t0] >= m60 * 0.98:
        sell.append("跌破季線 %s，中期趨勢轉弱" % px(m60))
    if hf and not h.get("sold") and c[t] >= hf and not (sz and c[t] >= sz[0]):
        trim.append("漲到你設定的 %s（收 %s），照計畫先賣一半%s" % (px(hf), px(c[t]), "，剩下的等 %s～%s 再賣" % (px(sz[0]), px(sz[-1])) if sz else ""))
    if sz:  # 你設定的賣價：先照你的計畫，其他規則只當提醒
        if c[t] >= sz[-1]:
            sell.append("到你設定的賣價 %s（收 %s），照計畫賣出" % (px(sz[-1]), px(c[t])))
        elif c[t] >= sz[0]:
            trim.append(("到你設定的賣價區 %s～%s，剩下的可以開始賣，%s 全部賣完" if hf else "到你設定的賣價區 %s～%s，可以先賣一半，%s 再賣剩下的") % (px(sz[0]), px(sz[-1]), px(sz[-1])))
        warn += [x for x in sell if not x.startswith(("收盤", "到你"))]  # 跌破季線等改成提醒
        sell[:] = [x for x in sell if x.startswith(("收盤", "到你"))]
    elif peak >= t1 and not h.get("sold") and not hf:
        trim.append("已到第一目標 %s，建議先賣一半落袋，剩下的跌破 %s 再賣" % (px(t1), px(max(stop, tick(E)))))
    if c[t] >= t2 and not sz:
        trim.append("到第二目標 %s（%s），壓力大，可再賣一部分" % (px(t2), why_t2))
    import analysis
    z = analysis.cycle_zone(s, t)
    if z and z["zone"] == "high" and not sz:  # 循環股：低點買、高點賣（你有自己的賣價就照你的）
        if c[t] >= z["hi"]:
            sell.append("循環股已漲到近 %d 年平均高點 %s 以上，照「低點買、高點賣」賣出" % (z["n"], px(z["hi"])))
        else:
            trim.append("循環股接近近 %d 年平均高點 %s（還差 %s），分批賣出" % (z["n"], px(z["hi"]), fmt(pct(z["hi"], c[t]))))
    r = rsi(c, t)
    if m20 and (c[t] / m20 - 1 > 0.15 or r > 80):
        (warn if sz else trim).append("短線過熱（高於月線 %s、RSI %d），容易回檔" % (fmt(pct(c[t], m20)), r))
    if m20 and c[t] < m20 and m20 < m20p:
        warn.append("跌破月線 %s 且月線下彎，短線轉弱" % px(m20))
    fi, it = s.get("fi") or [0] * len(c), s.get("it") or [0] * len(c)
    ns = 0
    while ns <= t and fi[t - ns] + it[t - ns] < 0:
        ns += 1
    if ns >= 4:
        warn.append("外資＋投信連續 %d 天賣超（%s 張）" % (ns, "{:,}".format(round(sum(fi[t - ns + 1:t + 1]) + sum(it[t - ns + 1:t + 1])))))
    md = analysis.macd(c, t)  # MACD 在零軸之上死亡交叉＝高檔轉弱，先提醒（不叫你賣）
    if md and md["cross"] and md["cross"] < 0 and md["dif"] > 0 and md["sig"] > 0:
        warn.append("MACD 高檔死亡交叉（%s），短線動能轉弱" % ("今天" if md["cross"] == -1 else "%d 天前" % (-md["cross"] - 1)))
    hw = [x for x in (s.get("hw") or []) if x.get("big") is not None]
    if len(hw) >= 3 and hw[-1]["big"] < hw[-2]["big"] < hw[-3]["big"]:
        warn.append("千張大戶持股連 2 週減少（%.1f%% → %.1f%%），大戶在出貨" % (hw[-3]["big"], hw[-1]["big"]))
    ins = s.get("ins") or {}
    if ins.get("n30"):
        warn.append("內部人近 30 天申報要賣 %s 張（董監、經理人或大股東），留意是否高檔出貨" % "{:,}".format(ins["sell30"]))
    rv = {x["m"]: x["v"] for x in (s.get("rev") or [])}
    yo = []
    for m in sorted(rv)[-2:]:
        p = "%d-%s" % (int(m[:4]) - 1, m[5:])
        if rv.get(p, 0) > 0 and rv[m] > 0:
            yo.append((m, pct(rv[m], rv[p])))
    if len(yo) == 2 and all(y < 0 for _, y in yo):
        warn.append("營收連 2 個月年減（%s月 %s），基本面轉弱" % (yo[-1][0][5:].lstrip("0"), fmt(yo[-1][1])))
    if held >= 20 and gain < 3 and not sell:
        warn.append("已抱 %d 個交易日報酬 %s，沒有表現，資金卡住，可考慮換到名單上更強的股票" % (held, fmt(gain)))

    if sell:
        lv, act = 3, "🔴 賣出"
    elif trim:
        lv, act = 2, "🟠 減碼（賣一半）"
    elif warn:
        lv, act = 1, "🟡 注意（先不用賣）"
    else:
        lv, act = 0, "🟢 續抱"
    tips = []
    cyc = str((prof or {}).get("cyc", ""))
    if z:
        tips.append("循環股位置：" + analysis.cycle_text(z))
    if cyc.startswith("循環") and "穩定" not in cyc.split("：")[0]:
        tips.append(cyc + "。循環股要看景氣與報價：報價開始轉跌、或股價已在一年高點附近時，就算沒到停損也要先減碼")
    lv_ = dict(sz=sz, hf=hf, stop=stop, why_stop=why_stop, t1=t1, t2=t2, why_t2=why_t2, peak=peak, held=held, gain=gain, close=c[t])
    return lv, act, sell + trim + warn, tips, lv_


def build(data, cfg, profiles=None):
    """回傳 (報告文字, sell_plan dict)；沒有持股回傳 ("", None)"""
    H = holdings(cfg)
    if not H:
        return "", None
    profiles = profiles or {}
    by = {s["id"]: s for s in data["stocks"]}
    disc = float((cfg.get("orders") or {}).get("disc", 10) if isinstance(cfg.get("orders"), dict) else 10)
    blocks, plan = [], []
    for sid, h in H.items():
        s = by.get(sid)
        if not s or len(s["c"]) < 30:
            blocks.append((1, ["【%s】資料不足，今晚無法判斷" % sid]))
            continue
        lv, act, rs, tips, P = check(s, data["dates"], h, profiles.get(sid))
        fee = max(20, h["cost"] * h["qty"] * 0.001425 * disc / 10) + max(20, P["close"] * h["qty"] * 0.001425 * disc / 10)
        net = (P["close"] - h["cost"]) * h["qty"] - fee - P["close"] * h["qty"] * (0.001 if sid.startswith("00") else 0.003)
        L = ["【%s %s】%s" % (sid, s["name"], act)]
        L.append("・持有 %d 股，均價 %s，收 %s（%s），扣手續費和稅約 %s 元；買進後 %d 個交易日，最高 %s"
                 % (h["qty"], px(h["cost"]), px(P["close"]), fmt(P["gain"]), "{:+,}".format(round(net)), P["held"], px(P["peak"])))
        L.append("・原因：" + ("；".join(rs) if rs else "還在停損之上、沒到目標、趨勢和法人沒有轉壞，照計畫抱著"))
        if lv == 3:
            L.append("・建議：明天開盤就賣出，不要等反彈")
        else:
            cond = ["收盤跌破 %s 全賣（%s，%s）" % (px(P["stop"]), P["why_stop"], fmt(pct(P["stop"], P["close"])))]
            if h.get("sold"):
                cond.append("已賣過一部分，剩下的照停損／移動停利處理")
            elif P["hf"] and P["close"] < P["t1"]:
                cond.append("漲到 %s 先賣一半（你設定的，%s）" % (px(P["t1"]), fmt(pct(P["t1"], P["close"]))))
            elif P["peak"] < P["t1"]:
                cond.append("漲到 %s 先賣一半（第一目標，%s）" % (px(P["t1"]), fmt(pct(P["t1"], P["close"]))))
            if P["t2"] > P["close"]:
                cond.append(("漲到 %s～%s 賣完（你設定的賣價，%s）" % (px(P["sz"][0]), px(P["sz"][-1]), fmt(pct(P["sz"][0], P["close"])))) if P["hf"] and len(P["sz"]) > 1 else
                            "漲到 %s 再賣（%s，%s）" % (px(P["t2"]), P["why_t2"], fmt(pct(P["t2"], P["close"]))))
            L.append("・賣出條件：" + "｜".join(cond))
        for x in tips:
            L.append("・" + x)
        blocks.append((lv, L))
        plan.append({"id": sid, "name": s["name"], "qty": h["qty"], "cost": round(h["cost"], 2), "stop": P["stop"],
                     "t1": P["t1"] if not h.get("sold") and (P["peak"] < P["t1"] or (P["hf"] and P["close"] < P["t1"])) else None, "t2": P["t2"],
                     "close": P["close"], "level": lv, "action": act})
    blocks.sort(key=lambda b: -b[0])
    cnt = [sum(b[0] == k for b in blocks) for k in (3, 2, 1, 0)]
    L = ["🔔 持股賣出提醒（%s 收盤）賣出 %d、減碼 %d、注意 %d、續抱 %d" % ((data["asOf"],) + tuple(cnt))]
    for _, b in blocks:
        L += b
    L.append("停損、目標依買進價與日波動（ATR）固定規則計算，用收盤價判斷；隔天早上開盤若已跌破停損或到目標，開盤檢查會再提醒。賣出後告訴我價錢，我會記錄。")
    return "\n".join(L), {"date": data["asOf"], "holds": plan}


def main():
    ld = lambda n, d=None: json.load(open(os.path.join(DIR, n), encoding="utf-8")) if os.path.exists(os.path.join(DIR, n)) else d
    text, plan = build(ld("data.json"), ld("sop_config.json", {}), ld("stock_profiles.json", {}))
    print(text or "沒有持股")


if __name__ == "__main__":
    main()
