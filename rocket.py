"""
rocket.py - 飆股前兆：每晚找「可能成為下一檔飆股」的股票（2026-10 研究）

研究方法（data.json 約 260 檔、2025-03～2026-10；全市場 2,358 檔、近 6 個月）：
  把「之後 40 天內最高漲 50% 以上」當作飆股，比較起漲前一天有哪些特徵比較常出現。
  - 最明顯：長紅 K（當天漲 5% 以上、收在當天高點附近）→ 變飆股機率是平常的 2.3～2.7 倍
  - 其次：營收創近 13 個月新高（1.5 倍）、突破 60 日高（1.6 倍）、爆量、投信連買 3 天以上（1.2～1.3 倍）
  - 反而比較不會：橫盤整理（20 日振幅 < 15%）、均線糾結、布林收窄（0.2～0.9 倍）；外資買超幾乎沒差
  組合（前半段、後半段時間都穩定）：
  - 長紅 K＋營收新高＋投信連買：變飆股 32%（平常 12%），之後 20 天平均 +15.8%（平常 +4.8%）
  - 長紅 K＋（營收新高或投信連買）：變飆股 27%，之後 20 天平均 +12.0%
  買賣規則回測（隔天開盤沒跳空 3% 以上才買、收盤跌破 −12% 停損、賺 15% 以上後從最高回落 12% 出場、最多抱 40 天）：
  勝率 56%、平均 +9.4%；等拉回才買反而變差（真正的飆股不太回頭，會回檔的多半是假突破）
  沒辦法回測的（資料不夠長）：新聞、千張大戶、內部人（董監）申報，只列出來給你參考
"""
import os

import analysis
import exits

DIR = os.path.dirname(os.path.abspath(__file__))
BT = {2: "回測：變飆股機率 32%（平常 12%），之後 20 天平均 +15.8%", 1: "回測：變飆股機率 27%（平常 12%），之後 20 天平均 +12.0%"}


def long_red(s, t):
    c, h, l = s["c"], s["h"], s["l"]
    return c[t - 1] and c[t] / c[t - 1] > 1.05 and (h[t] - c[t]) <= 0.25 * (h[t] - l[t] + 1e-9)


def streak(a, t):
    k = 0
    while t - k >= 0 and (a[t - k] or 0) > 0:
        k += 1
    return k


def rev_high(s):
    """最新已公布月營收是否創近 13 個月新高；回傳 (月份, 年增%) 或 None"""
    rv = {x["m"]: x["v"] for x in s.get("rev") or []}
    ks = sorted(rv)
    if len(ks) < 13 or not rv[ks[-1]] or rv[ks[-1]] <= 0 or rv[ks[-1]] < max(rv[k] for k in ks[-13:-1]):
        return None
    k = ks[-1]
    p = "%d-%s" % (int(k[:4]) - 1, k[5:])
    return k, ((rv[k] / rv[p] - 1) * 100 if rv.get(p, 0) > 0 else None)


def signal(s, t):
    """回傳 (等級, 理由清單)；等級 2＝三個都有、1＝長紅K＋一個、0＝沒有"""
    c, v = s["c"], s["v"]
    if t < 61 or not c[t] or c[t] < 10 or not long_red(s, t):
        return 0, []
    v20 = sum(v[t - 20:t]) / 20
    if v20 < 200:
        return 0, []
    rs = ["長紅 K（漲 %.1f%%，收在當天高點附近）" % ((c[t] / c[t - 1] - 1) * 100)]
    rh = rev_high(s)
    k = streak(s.get("it") or [0] * len(c), t)
    core = 0
    if rh:
        core += 1
        rs.append("%s營收創近 13 個月新高%s" % (rh[0][5:].lstrip("0") + "月", "（年增 %+.0f%%）" % rh[1] if rh[1] is not None else ""))
    if k >= 3:
        core += 1
        rs.append("投信連買 %d 天" % k)
    if not core:
        return 0, []
    if v[t] > 2 * v20:
        rs.append("爆量（%.1f 倍均量）" % (v[t] / v20))
    if c[t] > max(s["h"][t - 60:t]):
        rs.append("突破 60 日高點")
    fi5 = sum((s.get("fi") or [0] * len(c))[t - 4:t + 1])
    if fi5 > 0:
        rs.append("外資 5 日買超 %s 張" % analysis.zh(fi5))
    return core, rs


def extras(s):
    """沒辦法回測、但值得看的：千張大戶、最近新聞"""
    out = []
    hw = [x for x in (s.get("hw") or []) if x.get("big") is not None]
    if len(hw) >= 2:
        d = hw[-1]["big"] - hw[-2]["big"]
        out.append("千張大戶 %.1f%%（上週%s %.1f）" % (hw[-1]["big"], "增" if d >= 0 else "減", abs(d)))
    try:
        import insider
        x = insider.text(s.get("ins"))
        if x:
            out.append(x)
    except Exception:
        pass
    try:
        import alert
        seen, ns = set(), []
        for x in s.get("news") or []:
            k = x["title"].rsplit(" - ", 1)[0]
            if k in seen or "個股概覽" in k:
                continue
            seen.add(k)
            g = alert.tone(x["title"], alert.UP + alert.GOOD, alert.DOWN + alert.BAD)
            ns.append("%s%s %s" % ("🟢" if g > 0 else "🔴" if g < 0 else "⚪", x["d"][5:].replace("-", "/"), k[:40]))
            if len(ns) >= 2:
                break
        if ns:
            out.append("新聞：" + "｜".join(ns))
    except Exception:
        pass
    return out


def advice(s, t):
    c = s["c"][t]
    return "🟢 明早開盤 %s 以下可買（跳空超過 3%% 不追）｜收盤跌破 %s 停損｜賺 15%% 以上後，從最高點回落 12%% 就賣｜最多抱 40 天" % (
        analysis.px(exits.tick(c * 1.03)), analysis.px(exits.tick(c * 0.88)))


def scan(data, profiles, limit=10):
    """今晚出現飆股前兆的股票；回傳 Discord 文字（沒有就回傳空字串）"""
    hits = []
    for s in data["stocks"]:
        if s["id"].startswith("00"):
            continue
        t = len(s["c"]) - 1
        lv, rs = signal(s, t)
        if lv:
            hits.append((lv, (s["c"][t] / s["c"][t - 1]), s, rs, t))
    if not hits:
        return ""
    hits.sort(key=lambda x: (-x[0], -x[1]))
    L = ["🚀 飆股前兆（%s 收盤）：%d 檔" % (data["asOf"], len(hits)),
         "研究過去 1 年半：飆股起漲那天最常見「長紅 K」，再加上營收創新高或投信連買，變飆股的機率是平常的 2～3 倍。"
         "但約 4 成還是會失敗，一定要設停損。"]
    for lv, _, s, rs, t in hits[:limit]:
        p = profiles.get(s["id"]) or {}
        L.append("")
        L.append("%s %s %s　收盤 %s" % ("🚀🚀" if lv == 2 else "🚀", s["id"], s["name"], analysis.px(s["c"][t])))
        if p.get("biz"):
            L.append("・做什麼：%s" % p["biz"])
        L.append("・前兆：%s" % "、".join(rs))
        L.append("・%s" % BT[lv])
        for x in extras(s):
            L.append("・%s" % x)
        L.append("・建議：%s" % advice(s, t))
    if len(hits) > limit:
        L.append("")
        L.append("其他也有前兆的：%s" % "、".join("%s %s" % (s["id"], s["name"]) for _, _, s, _, _ in hits[limit:]))
    return "\n".join(L)


if __name__ == "__main__":
    import json
    import sys
    d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(DIR, "data.json"), encoding="utf-8"))
    print(scan(d, analysis._ld("stock_profiles.json", {})) or "今晚沒有飆股前兆")
