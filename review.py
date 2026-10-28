"""
review.py - 復盤：檢討每一筆買賣，找出「更好的買點／賣點」與當時出現的訊號，把學到的規則記下來

1. 循環股谷底轉強訊號（從復盤學到的）：
   循環股（stock_profiles.json 的 cyc 以「循環」開頭）＋近 10 天曾在一年區間下方 30% 以內（谷底區）
   ＋今天剛站回月線或帶量大漲 5%＋外資近 5 天至少 3 天買超
   → 每晚掃描，出現就在報告提醒（cycle_alerts）
2. 復盤每筆實際買賣（sop_config.json 的 orders，done: true）：
   買進：前 90 個交易日的最低點在哪、有沒有更早出現谷底轉強訊號、照訊號買會差多少
   賣出：賣掉後 20 天的最高、最低，判斷賣早了還是賣對了
   賺錢、賠錢都記到 lessons.json，每週日晚上發一次（只給自己）
"""
import json
import os

import analysis
import exits

DIR = os.path.dirname(os.path.abspath(__file__))
LESSONS = os.path.join(DIR, "lessons.json")


def ma(c, n, t):
    return sum(c[t - n + 1:t + 1]) / n


def is_cyclical(prof):
    cyc = str((prof or {}).get("cyc", ""))
    return cyc.startswith("循環") and "穩定" not in cyc.split("：")[0]


def bottom_signal(s, t):
    """循環股谷底轉強；回傳理由清單或 None"""
    c, h, l, v = s["c"], s["h"], s["l"], s["v"]
    fi = s.get("fi") or [0] * len(c)
    if t < 240:
        return None
    a = t - 239
    hi, lo = max(h[a:t + 1]), min(l[a:t + 1])
    if hi <= lo:
        return None
    low10 = min(c[t - 10:t + 1])
    pos10 = (low10 - lo) / (hi - lo) * 100
    if pos10 > 30:
        return None
    up = c[t] > ma(c, 20, t) and c[t - 1] <= ma(c, 20, t - 1)
    big = c[t] / c[t - 1] - 1 >= 0.05 and v[t] > sum(v[t - 20:t]) / 20 * 1.5
    fib = sum(1 for x in fi[t - 4:t + 1] if x > 0)
    if not ((up or big) and fib >= 3):
        return None
    why = ["近 10 天低點在一年區間的 %d%%（谷底區）" % pos10]
    why.append("今天站回月線 %s" % analysis.px(exits.tick(ma(c, 20, t))) if up else "帶量大漲 %s" % analysis.fmt((c[t] / c[t - 1] - 1) * 100))
    why.append("外資近 5 天有 %d 天買超" % fib)
    return why


def rule_stats(data, profiles, hold=20):
    """回測谷底轉強訊號：同一檔 20 天內只算一次；回傳 (次數, 勝率, 平均報酬)"""
    n = w = 0
    tot = 0.0
    for s in data["stocks"]:
        if not is_cyclical(profiles.get(s["id"])):
            continue
        last = -99
        for t in range(240, len(s["c"]) - 1):
            if t - last < 20 or not bottom_signal(s, t):
                continue
            last = t
            e = min(len(s["c"]) - 1, t + hold)
            r = (s["c"][e] / s["c"][t] - 1) * 100
            n += 1
            w += r > 0
            tot += r
    return n, (w / n * 100 if n else 0), (tot / n if n else 0)


FLOW = ("外資連買", "投信買超", "帶量大漲")  # 籌碼／量價：回測（抱 60 天）最能分出好壞的理由


def _rev_yoy(s, t, back=0):
    """第 t 天已經公布的月營收年增率（每月 10 日前公布上個月）"""
    D = s.get("_dates") or []
    rv = {x["m"]: x["v"] for x in s.get("rev") or []}
    ym = D[t][:7] if D else ""
    ms = [m for m in sorted(rv) if m < ym]
    if D and int(D[t][8:10]) <= 10:
        ms = ms[:-1]
    if len(ms) <= back:
        return None
    m = ms[-1 - back]
    p = "%d-%s" % (int(m[:4]) - 1, m[5:])
    return (rv[m] / rv[p] - 1) * 100 if rv.get(p, 0) > 0 and rv[m] > 0 else None


def in_bottom(s, t):
    """谷底區：近 10 天低點在一年區間下方 35% 以內，或股價在近 5 年平均低點 +15% 以內"""
    if t < 240:
        return False
    a = t - 239
    hi, lo = max(s["h"][a:t + 1]), min(s["l"][a:t + 1])
    pos = (min(s["c"][t - 10:t + 1]) - lo) / (hi - lo) * 100 if hi > lo else 50
    b = (analysis._ld("cycle_bands.json", {}).get("bands") or {}).get(s["id"])
    return pos <= 35 or bool(b and s["c"][t] <= b["avg_lo"] * 1.15)


def rise_reasons(s, t):
    """循環股起漲的理由（今天成立的）"""
    c, v = s["c"], s["v"]
    fi, it = s.get("fi") or [0] * len(c), s.get("it") or [0] * len(c)
    R = []
    if sum(1 for x in fi[t - 4:t + 1] if x > 0) >= 3:
        R.append("外資連買")
    if sum(it[t - 9:t + 1]) > 0 and sum(1 for x in it[t - 4:t + 1] if x > 0) >= 2:
        R.append("投信買超")
    if c[t] / c[t - 1] - 1 >= 0.04 and v[t] > 1.5 * sum(v[t - 20:t]) / 20:
        R.append("帶量大漲")
    if c[t] > ma(c, 20, t) and c[t - 1] <= ma(c, 20, t - 1):
        R.append("站回月線")
    if ma(c, 20, t) > ma(c, 20, t - 5) and ma(c, 20, t - 5) <= ma(c, 20, t - 10):
        R.append("月線翻揚")
    y0, y1 = _rev_yoy(s, t), _rev_yoy(s, t, 1)
    if y0 is not None and y1 is not None and (y0 > 0 >= y1 or (y0 > y1 + 10 and y0 > -5)):
        R.append("營收年增回升")
    return R


def rise_level(s, t):
    """大漲訊號等級：2＝強（谷底區＋2 種籌碼／量價）、1＝起漲（谷底區＋1 種）、0＝沒有；回傳 (等級, 理由)"""
    if not in_bottom(s, t):
        return 0, []
    R = rise_reasons(s, t)
    f = sum(1 for x in R if x in FLOW)
    return (2 if f >= 2 else 1 if f == 1 else 0), R


def rise_stats(data, hold=60):
    """回測大漲訊號（同一檔 hold 天內只算一次，隔天開盤買、抱 hold 天）；回傳 {等級: (次數, 勝率, 平均)}"""
    bands = analysis._ld("cycle_bands.json", {}).get("bands") or {}
    st = {1: [], 2: [], 0: []}
    for s in data["stocks"]:
        if s["id"] not in bands:
            continue
        s["_dates"] = data["dates"]
        last = -999
        for t in range(245, len(s["c"]) - hold - 1):
            e = s["o"][t + 1] or s["c"][t + 1]
            st[0].append((s["c"][t + hold] / e - 1) * 100)
            if t - last < hold:
                continue
            lv, _ = rise_level(s, t)
            if lv:
                last = t
                r = (s["c"][t + hold] / e - 1) * 100 - 0.6
                st[1].append(r)
                if lv == 2:
                    st[2].append(r)
    return {k: (len(v), sum(x > 0 for x in v) / len(v) * 100 if v else 0, sum(v) / len(v) if v else 0) for k, v in st.items()}


def history_text(sid, prof):
    """這檔過去 5 年的規律＋產業大漲原因（cycle_study.json、cycle_reasons.json）"""
    stu = (analysis._ld("cycle_study.json", {}).get("stocks") or {}).get(sid)
    rs = analysis._ld("cycle_reasons.json", {})
    L = []
    import cycle_study
    g = (stu or {}).get("group") or cycle_study.group_of(prof)
    if stu:
        ls, hs = stu.get("low_season"), stu.get("high_season")
        if ls:
            L.append("過去 %d 年低點%s %d 月附近（%d 年）" % (ls["of"], "常在" if ls["fixed"] else "沒有固定月份，最多在", ls["month"], ls["years"]))
        if hs and hs["fixed"]:
            L.append("高點常在 %d 月附近" % hs["month"])
        ups = [x for x in stu.get("swings", []) if x["pct"] > 0]
        if ups:
            u = ups[-1]
            L.append("上一次大漲：%s～%s %+.0f%%%s" % (u["from"], u["to"], u["pct"], "（起漲時營收年增已先轉強）" if u.get("rev_leads") else ""))
    r = rs.get(g) or {}
    if r.get("up"):
        L.append("這個產業過去大漲的原因：" + "；".join(r["up"][-2:]))
    if r.get("signals"):
        L.append("接下來要盯：" + "、".join(r["signals"]))
    if r.get("timing"):
        L.append("時間規律：" + r["timing"])
    return L


def cycle_alerts(data, profiles, held=()):
    """今晚出現大漲訊號的循環股（谷底區＋籌碼／量價），每檔附過去 5 年規律、產業原因與建議"""
    t = len(data["dates"]) - 1
    out = []
    bands = analysis._ld("cycle_bands.json", {}).get("bands") or {}
    sig = []
    for s in data["stocks"]:
        p = profiles.get(s["id"]) or {}
        if s["id"] not in bands or len(s["c"]) <= 245:
            continue
        s["_dates"] = data["dates"]
        lv, R = rise_level(s, len(s["c"]) - 1)
        if lv:
            sig.append((lv, s, p, R))
    sig.sort(key=lambda x: -x[0])
    short = []
    for lv, s, p, R in sig:
        c = s["c"][-1]
        A = exits.atr(s, len(s["c"]) - 1)
        buy_lo = exits.tick(c - A)
        low10 = max(min(min(s["l"][-11:]), c - 1.5 * A, buy_lo * 0.98), c * 0.92)  # 停損：近 10 天谷底，且一定低於買進區，最多賠 8%
        hi1y = max(s["h"][len(s["c"]) - 240:])
        b = bands.get(s["id"]) or {}
        tgt = b.get("avg_hi") if b.get("avg_hi", 0) > c * 1.05 else hi1y
        if lv == 1 and len(out) + len(short) >= 3:  # 起漲訊號太多時，後面的只寫一行
            short.append("・%s %s 收 %s：%s（停損 %s）" % (s["id"], s["name"], analysis.px(c), "、".join(R), analysis.px(exits.tick(low10))))
            continue
        L = ["%s %s %s 收 %s" % ("🚀 強訊號" if lv == 2 else "🟢 起漲訊號", s["id"], s["name"], analysis.px(c)),
             "  今天的訊號：谷底區（股價在一年低檔或接近近 5 年平均低點）＋" + "、".join(R)]
        L += ["  " + x for x in history_text(s["id"], p)]
        L.append("  建議：可分批買 %s～%s，跌破 %s 停損，目標 %s（%s，%s）｜抱 1～3 個月看%s" % (
            analysis.px(buy_lo), analysis.px(c), analysis.px(exits.tick(low10)), analysis.px(tgt),
            analysis.fmt((tgt / c - 1) * 100), "近 5 年平均高點" if tgt != hi1y else "一年高點", "（你已持有）" if s["id"] in held else ""))
        out.append("\n".join(L))
    if short:
        out.append("其他起漲訊號（訊號比較弱，先觀察）：\n" + "\n".join(short))
    low = []  # 到了近幾年平均低點附近的循環股（低點買、高點賣）
    for s in data["stocks"]:
        z = analysis.cycle_zone(s)
        if z and z["zone"] == "low":
            low.append("・%s %s 收 %s：%s\n  建議：%s" % (s["id"], s["name"], analysis.px(z["c"]), analysis.cycle_text(z),
                                                   analysis.advise(s, len(s["c"]) - 1)))
    if not out and not low:
        return ""
    L = []
    if out:
        stt = rise_stats(data)
        n1, w1, a1 = stt[1]
        n2, w2, a2 = stt[2]
        n0, w0, a0 = stt[0]
        L += ["🔔 循環股大漲訊號（%s）\n回測（抱 60 天）：強訊號 %d 次、上漲機率 %.0f%%、平均 %s（次數少，參考就好）；全部訊號 %d 次、%.0f%%、平均 %s（循環股隨便買 %.0f%%、%s）"
              % (data["asOf"], n2, w2, analysis.fmt(a2), n1, w1, analysis.fmt(a1), w0, analysis.fmt(a0))] + out
    if low:
        L += ["🔻 循環股到了近幾年平均低點附近（%s，可以開始分批買）" % data["asOf"]] + low
    return "\n".join(L)


def _idx(dates, d):
    return next((i for i, x in enumerate(dates) if x >= d), len(dates) - 1)


def review_trades(data, cfg, profiles):
    """復盤每一筆實際買賣；回傳 (文字, 教訓清單)"""
    oc = cfg.get("orders") or {}
    orders = [o for o in ((oc.get("list") if isinstance(oc, dict) else oc) or []) if o.get("done")]
    if not orders:
        return "", []
    by = {s["id"]: s for s in data["stocks"]}
    D = data["dates"]
    L, lessons = ["🧭 復盤（%s）：檢討每筆買賣，賺的賠的都學起來" % data["asOf"]], []
    for o in sorted(orders, key=lambda x: str(x.get("date", ""))):
        sid, p, q, d = str(o["id"]), float(o["price"]), int(o.get("qty") or 1000), str(o.get("date", ""))
        s = by.get(sid)
        if not s:
            continue
        t0, tN = _idx(D, d), len(D) - 1
        c = s["c"]
        name, prof = s["name"], profiles.get(sid)
        sell = str(o.get("side", "b")).startswith("s")
        if not sell:
            a = max(0, t0 - 90)
            lo_t = min(range(a, t0 + 1), key=lambda i: c[i])
            sig_t = next((i for i in range(lo_t, t0 + 1) if is_cyclical(prof) and bottom_signal(s, i)), None)
            now = c[tN]
            L.append("【%s %s】%s 買 %s × %d 股，現在 %s（%s）" % (sid, name, d[5:], analysis.px(p), q, analysis.px(now), analysis.fmt((now / p - 1) * 100)))
            L.append("・買之前 90 天最低：%s 收 %s，你買在低點之上 %s" % (D[lo_t][5:], analysis.px(c[lo_t]), analysis.fmt((p / c[lo_t] - 1) * 100)))
            if sig_t is not None and sig_t < t0:
                gain = (now - c[sig_t]) * q
                L.append("・更好的買點：%s 出現「循環股谷底轉強」（%s），當時收 %s；照訊號買到現在 %s，比你多賺約 %s 元"
                         % (D[sig_t][5:], "、".join(bottom_signal(s, sig_t)), analysis.px(c[sig_t]), analysis.fmt((now / c[sig_t] - 1) * 100),
                            "{:,}".format(round(gain - (now - p) * q))))
                les = "循環股在一年低檔、站回月線且外資連買時是好買點（%s %s：%s 訊號價 %s，你 %s 才買 %s）" % (sid, name, D[sig_t][5:], analysis.px(c[sig_t]), d[5:], analysis.px(p))
                L.append("・學到：" + les + "；已加入每晚「循環股谷底轉強」提醒")
                lessons.append({"date": data["asOf"], "id": sid, "type": "買點", "lesson": les})
            elif is_cyclical(prof):
                L.append("・買點：買之前沒有出現谷底轉強訊號，買在%s" % ("回升途中" if p > c[lo_t] * 1.1 else "低檔附近，買點不錯"))
            if now < p * 0.95:
                les = "%s %s 買進後下跌 %s：檢查買進理由是否還在，跌破停損就照紀律賣" % (sid, name, analysis.fmt((now / p - 1) * 100))
                L.append("・注意：" + les)
                lessons.append({"date": data["asOf"], "id": sid, "type": "虧損", "lesson": les})
        else:
            e = min(tN, t0 + 20)
            after = c[t0 + 1:e + 1] if t0 < tN else []
            L.append("【%s %s】%s 賣 %s × %d 股" % (sid, name, d[5:], analysis.px(p), q))
            if after:
                mx, mn = max(after), min(after)
                if mx > p * 1.05:
                    les = "%s %s 賣早了：賣後 20 天最高 %s（%s）；下次到第一目標先賣一半、剩下用移動停利" % (sid, name, analysis.px(mx), analysis.fmt((mx / p - 1) * 100))
                    L.append("・" + les)
                    lessons.append({"date": data["asOf"], "id": sid, "type": "賣點", "lesson": les})
                elif mn < p * 0.95:
                    L.append("・賣對了：賣後最低跌到 %s（%s）" % (analysis.px(mn), analysis.fmt((mn / p - 1) * 100)))
                else:
                    L.append("・賣後走勢平平，賣點合理")
            else:
                L.append("・剛賣出，之後幾天再檢討")
    return "\n".join(L), lessons


def save_lessons(new):
    """把新學到的記到 lessons.json（同一檔、同一類只記一次）"""
    old = json.load(open(LESSONS, encoding="utf-8")) if os.path.exists(LESSONS) else []
    keys = {(x["id"], x["type"]) for x in old}
    add = [x for x in new if (x["id"], x["type"]) not in keys]
    if add:
        json.dump(old + add, open(LESSONS, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return add


def main():
    ld = lambda n, d=None: json.load(open(os.path.join(DIR, n), encoding="utf-8")) if os.path.exists(os.path.join(DIR, n)) else d
    data, cfg, prof = ld("data.json"), ld("sop_config.json", {}), ld("stock_profiles.json", {})
    text, les = review_trades(data, cfg, prof)
    print(text)
    print(cycle_alerts(data, prof) or "今晚沒有循環股谷底轉強訊號")


if __name__ == "__main__":
    main()
