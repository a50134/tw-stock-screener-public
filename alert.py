"""
alert.py - 盤中持股即時提醒（只發 Discord，不發 LINE；持股是私人資料）

開盤前到收盤（alert.yml 每 30 分鐘跑一次）檢查每一檔持股：
  1. 價位：到你設定的「先賣一半」、賣價區、停損，或盤中大漲大跌 4% 以上
  2. 新聞：公司本身的新聞，以及它的原料／報價新聞（例如華新看銅價、鎳價、不銹鋼）
     每則新聞判斷是利多還是利空、對你這檔的影響，再配合現價和你的計畫給建議
同一則新聞、同一個價位提醒一天只發一次（記在私人專案的 alert_state.json）

公開專案的執行紀錄任何人都看得到，所以這支程式只印「幾則提醒」，不印股票代號、新聞標題。
用法：python alert.py            # 檢查並發到 Discord
      python alert.py --dry      # 只印在畫面（本機測試用），不發送、不記錄
"""
import datetime as dt
import email.utils
import hashlib
import json
import os
import sys
import urllib.parse
import xml.etree.ElementTree as ET

import requests

import exits

DIR = os.path.dirname(os.path.abspath(__file__))
STATE = os.path.join(DIR, "alert_state.json")
TW = dt.timezone(dt.timedelta(hours=8))
DRY = "--dry" in sys.argv

# 原料／報價新聞：搜尋字 → 公司資料（業務、上下游、循環股說明）裡出現這些字才算相關
RAW = {"銅價": ["銅", "電線", "電纜"], "鎳價": ["鎳"], "不銹鋼 價格": ["不銹鋼", "不鏽鋼"], "鋼價": ["鋼"],
       "貨櫃 運價 SCFI": ["貨櫃"], "散裝 BDI": ["散裝", "大宗物資"], "塑化 報價": ["塑", "石化", "PVC", "乙烯"],
       "水泥 價格": ["水泥"], "面板 報價": ["面板"], "記憶體 報價": ["記憶體", "DRAM"], "紙價": ["紙"],
       "油價": ["原油", "燃油", "油價"], "金價": ["黃金"], "鋁價": ["鋁"]}
UP = ("大漲", "暴漲", "飆", "創高", "新高", "急漲", "調漲", "漲價", "上漲", "走高", "攀升", "反彈", "勁揚", "走揚", "上揚", "看漲", "看俏", "減產")
DOWN = ("大跌", "暴跌", "崩", "創低", "新低", "急跌", "調降", "跌價", "下跌", "走低", "重挫", "下滑", "回落", "看跌", "疲軟", "跌破", "增產")
GOOD = ("接單", "獲利成長", "營收創", "創新高", "上修", "得標", "擴產", "調升", "買超", "利多", "受惠", "轉盈", "大單", "漲停")
BAD = ("虧損", "衰退", "下修", "裁員", "火災", "停工", "賣超", "利空", "罰", "跌停", "砍單", "減資", "違約", "掏空")


def tone(title, up=UP, down=DOWN):
    """標題偏漲（+1）、偏跌（−1）、看不出來（0）"""
    u, d = any(w in title for w in up), any(w in title for w in down)
    return 0 if u == d else (1 if u else -1)


def rss(q, hours):
    """Google 新聞搜尋（最近幾小時）"""
    url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote("%s when:1d" % q) + "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
    try:
        root = ET.fromstring(requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"}).content)
    except Exception:
        return []
    cut = dt.datetime.now(dt.timezone.utc) - dt.timedelta(hours=hours)
    out = []
    for it in root.iter("item"):
        title = (it.findtext("title") or "").strip()
        try:
            pub = email.utils.parsedate_to_datetime(it.findtext("pubDate"))
        except Exception:
            pub = None
        if title and (not pub or pub >= cut):
            out.append({"title": title.rsplit(" - ", 1)[0], "src": title.rsplit(" - ", 1)[-1] if " - " in title else "",
                        "d": pub.astimezone(TW).strftime("%m/%d %H:%M") if pub else "", "link": it.findtext("link") or ""})
    return out


def raw_terms(prof):
    """這家公司相關的原料搜尋字 → 價格漲對公司是好（+1）還是壞（−1）
    循環股說明裡有提到的原料（例如華新「獲利跟銅、鎳價格」）：原料漲、產品跟著漲價，算同方向；
    只出現在上游（成本）的：原料漲＝成本變高，算反方向"""
    prof = prof or {}
    out = {}
    for q, kw in RAW.items():
        hit = [k for k in kw if k in "".join(str(prof.get(x, "")) for x in ("biz", "up", "down", "cyc"))]
        if not hit:
            continue
        same = any(k in str(prof.get("cyc", "")) + str(prof.get("biz", "")) for k in hit)
        out[q] = 1 if same else -1
    return out


def judge(item, sign, h, q, plan):
    """一則新聞 → (利多/利空/中性, 判斷建議)"""
    t = item["title"]
    if sign is None:  # 公司本身的新聞
        g = tone(t, UP + GOOD, DOWN + BAD)
        why = ""
    else:  # 原料新聞：原料漲跌 × 對公司的方向
        g = tone(t) * sign
        why = "（原料%s，%s）" % ("漲" if tone(t) > 0 else "跌" if tone(t) < 0 else "變動",
                               "產品報價通常跟著走" if sign > 0 else "原料是成本")
    z, stop = q.get("z"), plan.get("stop")
    hf, sell = plan.get("half"), plan.get("sell") or []
    if g > 0:
        tag = "🟢 偏利多" + why
        tip = "利多不用追買，照你的計畫走" + (("；現價已到 %s 以上，照計畫先賣一半" if z and z >= hf else "；漲到 %s 先賣一半") % exits.px(hf) if hf and not h.get("sold") else "") + \
              ("；%s～%s 賣完" % (exits.px(sell[0]), exits.px(sell[-1])) if len(sell) > 1 else "")
    elif g < 0:
        tag = "🔴 偏利空" + why
        near = z and stop and z <= stop * 1.05
        tip = ("離停損 %s 很近，利空加上跌勢，可以考慮先減碼一半，不要等到停損" % exits.px(stop) if near else
               "先不用急著賣，看今天收盤：收盤跌破 %s 照停損出場；若連續幾天都是這類利空、股價又走弱，可以提前減碼" % exits.px(stop or 0))
    else:
        tag = "⚪ 中性／看不出方向" + why
        tip = "先知道就好，照原本計畫"
    return tag, tip


def price_alerts(sid, name, h, plan, q, seen):
    """價位提醒：先賣一半、賣價區、停損、盤中大漲大跌；回傳 [(key, 文字)]"""
    z, y = q.get("z") or q.get("o"), q.get("y")
    if not z:
        return []
    out = []
    hf, sell, stop = plan.get("half"), plan.get("sell") or [], plan.get("stop")
    if hf and not h.get("sold") and z >= hf and not (sell and z >= sell[0]):
        out.append(("half", "🟠 到你設定的 %s，照計畫先賣一半（%d 股），剩下的%s" % (
            exits.px(hf), h["qty"] // 2, "等 %s～%s 再賣" % (exits.px(sell[0]), exits.px(sell[-1])) if sell else "照停損抱著")))
    if sell and z >= sell[-1]:
        out.append(("sellall", "🔴 到你設定的賣價 %s，照計畫全部賣出" % exits.px(sell[-1])))
    elif sell and z >= sell[0]:
        out.append(("sell", "🟠 到你設定的賣價區 %s～%s，可以開始賣，%s 全部賣完" % (exits.px(sell[0]), exits.px(sell[-1]), exits.px(sell[-1]))))
    if stop and z <= stop:
        out.append(("stop", "🔴 盤中跌破你的停損 %s，收盤還在下面就照計畫賣出" % exits.px(stop)))
    if y:
        g = (z / y - 1) * 100
        if g >= 4:
            out.append(("up4", "📈 盤中大漲 %+.1f%%（下面有新聞的話看原因）" % g))
        elif g <= -4:
            out.append(("dn4", "📉 盤中大跌 %+.1f%%（下面有新聞的話看原因）" % g))
    return [(k, x) for k, x in out if "%s:%s" % (sid, k) not in seen]


def main():
    ld = lambda n, d=None: json.load(open(os.path.join(DIR, n), encoding="utf-8")) if os.path.exists(os.path.join(DIR, n)) else d
    cfg, prof = ld("sop_config.json", {}), ld("stock_profiles.json", {})
    H = exits.holdings(cfg)
    if not H:
        print("沒有持股，不用檢查")
        return
    sp = {x["id"]: x for x in (ld("sell_plan.json", {}) or {}).get("holds", [])}
    today = dt.datetime.now(TW).strftime("%Y-%m-%d")
    st = ld("alert_state.json", {}) or {}
    if st.get("day") != today:
        st["px"] = []  # 價位提醒每天重新算
    st["day"] = today
    seen_px, seen_news = set(st.get("px", [])), set(st.get("news", []))
    from morning_check import quotes
    try:
        Q = {k: {"o": v[0], "z": v[1], "y": v[2]} for k, v in quotes(list(H)).items()}
    except Exception as e:
        print("報價抓取失敗：", type(e).__name__)
        Q = {}
    hp = (cfg.get("orders") or {}).get("holds_plan") or {}
    blocks, n_px, n_news = [], 0, 0
    for sid, h in H.items():
        p, name = prof.get(sid) or {}, (sp.get(sid) or {}).get("name") or sid
        plan = dict(hp.get(sid) or {})
        plan.setdefault("stop", (sp.get(sid) or {}).get("stop"))
        if not plan.get("sell") and (sp.get(sid) or {}).get("t2"):
            plan["sell"] = [sp[sid]["t2"]]
        if not plan.get("half") and (sp.get(sid) or {}).get("t1"):
            plan["half"] = sp[sid]["t1"]
        q = Q.get(sid, {})
        pa = price_alerts(sid, name, h, plan, q, seen_px)
        news = []
        short = name.replace("-KY", "")
        for it in rss("%s %s" % (short, sid), 6) + rss(short + " 股價", 6):
            news.append((it, None))
        for term, sign in raw_terms(p).items():
            for it in rss(term, 6)[:5]:
                if tone(it["title"]) != 0:  # 原料新聞只留有明顯漲跌的
                    news.append((it, sign))
        fresh, keys = [], set()
        for it, sign in news:
            k = hashlib.md5(it["title"].encode("utf-8")).hexdigest()[:12]
            if k in seen_news or k in keys:
                continue
            keys.add(k)
            fresh.append((k, it, sign))
        fresh = fresh[:6]
        if not pa and not fresh:
            continue
        z, y = q.get("z") or q.get("o"), q.get("y")
        L = ["【%s %s】現價 %s%s" % (sid, name, exits.px(z) if z else "—", "（%+.1f%%）" % ((z / y - 1) * 100) if z and y else "")]
        pl = []
        if plan.get("half") and not h.get("sold"):
            pl.append("%s 賣一半" % exits.px(plan["half"]))
        if plan.get("sell"):
            pl.append("%s 賣完" % "～".join(exits.px(x) for x in dict.fromkeys(plan["sell"])))
        if plan.get("stop"):
            pl.append("%s 停損" % exits.px(plan["stop"]))
        L.append("・你的計畫：成本 %s，%s" % (exits.px(h["cost"]), "、".join(pl)))
        for k, x in pa:
            L.append("・" + x)
            seen_px.add("%s:%s" % (sid, k))
            n_px += 1
        for k, it, sign in fresh:
            tag, tip = judge(it, sign, h, q, plan)
            L.append("・%s新聞（%s %s）：%s\n　→ %s。建議：%s" % ("原料" if sign is not None else "", it["d"], it["src"], it["title"], tag, tip))
            seen_news.add(k)
            n_news += 1
        blocks.append("\n".join(L))
    st["px"], st["news"] = sorted(seen_px), list(seen_news)[-800:]
    if not blocks:
        print("沒有新的提醒")
    else:
        now = dt.datetime.now(TW).strftime("%m/%d %H:%M")
        text = "\n\n".join(["⚡ 持股即時提醒（%s）" % now] + blocks +
                           ["利多／利空是依新聞標題的字判斷，可能看錯；要更仔細的判斷，把新聞貼給 Claude 一起看。"])
        if DRY:
            print(text)
        else:
            import send_report
            url = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
            if not url:
                print("沒有設定 DISCORD_WEBHOOK_URL，提醒沒發出")
                return
            send_report.send_discord(url, text)
        print("已發送：價位提醒 %d 則、新聞 %d 則" % (n_px, n_news))
    if not DRY:
        json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
