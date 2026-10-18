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


def cycle_alerts(data, profiles, held=()):
    """今晚出現谷底轉強的循環股（每檔附建議）"""
    t = len(data["dates"]) - 1
    out = []
    for s in data["stocks"]:
        p = profiles.get(s["id"])
        if not is_cyclical(p) or len(s["c"]) <= 240:
            continue
        why = bottom_signal(s, len(s["c"]) - 1)
        if not why:
            continue
        c = s["c"][-1]
        low10 = max(min(s["l"][-11:]), c * 0.92)  # 停損放在近 10 天谷底，但最多賠 8%
        A = exits.atr(s, len(s["c"]) - 1)
        a = len(s["c"]) - 240
        hi1y = max(s["h"][a:])
        out.append("・%s %s 收 %s：%s\n  建議：🟢 可買 %s～%s，跌破 %s 停損，目標一年高點 %s（%s）｜%s"
                   % (s["id"], s["name"], analysis.px(c), "、".join(why), analysis.px(exits.tick(c - A)), analysis.px(c),
                      analysis.px(exits.tick(low10)), analysis.px(hi1y), analysis.fmt((hi1y / c - 1) * 100),
                      "你已持有" if s["id"] in held else p["cyc"]))
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
        n, win, avg = rule_stats(data, profiles)
        L += ["🔄 循環股谷底轉強（%s）\n過去這個訊號出現 %d 次，20 天後上漲機率 %.0f%%、平均 %s" % (data["asOf"], n, win, analysis.fmt(avg))] + out
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
