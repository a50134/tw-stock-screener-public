"""
alert.py - 盤中即時提醒（只發 Discord，不發 LINE；持股是私人資料）

開盤前到收盤（alert.yml：09:00～11:00 與 13:00～13:30 每 10 分鐘、其餘每 30 分鐘）先掃大環境（2026-11-11 使用者要的）：
  A. 大盤急漲急跌：0050 當天漲跌超過 2%／3.5%／5%，或跟上一次檢查比短時間變動 1% 以上
  B. 重大消息：國安基金、央行、金管會、限空令、美國升降息、關稅等（同一類消息一天最多 2 則）
  C. 前一晚推薦的股票盤中急漲急跌 4% 以上
再檢查每一檔持股：
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


BIG_Q = ["國安基金", "金管會 股市", "限空令", "央行 利率", "聯準會 利率", "台股 盤中", "關稅 台灣", "輝達 黃仁勳", "台指期 結算"]
# 重大消息分類：(標題要有的字, 排除的字, 圖示, 對投資的影響, 原因, 建議)；對不上任何一類的新聞＝不重要，不發（2026-11-12 使用者：沒有重大消息就不發，有的話要說影響和原因）
IMPACT = [
    (("國安基金", "護盤", "穩定市場"), ("退場", "撤出"), "🛡️", "偏利多（短線）",
     "政府用國安基金進場買權值股，賣壓會被承接；回測 9 次進場，第一波平均反彈約 13%、第 13 天左右見高，之後平均回跌 13%",
     "手上有的先抱；想買的不要追第一波，等每晚報告的「回跌買點」（從高點回跌約 6%）；護盤股優先台達電、鴻海、台積電、廣達"),
    (("國安基金退場", "國安基金撤出", "護盤退場"), (), "⚠️", "偏利空（中期）",
     "國安基金退場代表政府認為市場已穩定，之後少了承接的買盤，歷史上退場後常盤整一段時間",
     "已經賺的可以分批獲利了結；不急著加碼"),
    (("限空", "禁止放空", "平盤以下不得放空"), (), "🛡️", "偏利多（短線）",
     "限制放空讓空方不能再壓低股價，空單回補還會推升股價；通常是政府護盤的配套措施",
     "跟國安基金一樣，不追第一波反彈，等回跌再分批"),
    (("央行升息", "央行 升息", "升息半碼", "升息一碼"), ("聯準會", "Fed", "美國"), "🏦", "偏利空",
     "台灣利率上升，房貸和企業借錢變貴，營建、高負債公司受影響最大；但銀行利差變大，金融股反而有利",
     "營建股、高負債股先不加碼；金融股影響小或偏好"),
    (("央行降息", "央行 降息", "降息半碼", "降息一碼"), ("聯準會", "Fed", "美國"), "🏦", "偏利多",
     "台灣利率下降，資金成本變低，營建、高股息、成長股比較受惠；銀行利差變小",
     "可以照計畫買；營建、高股息股相對有利"),
    (("央行", "理監事會"), ("聯準會", "Fed", "美國", "日本", "歐洲"), "🏦", "看內容",
     "央行利率不變或調整房貸限制（信用管制），主要影響營建股與房市",
     "利率不變影響不大；信用管制收緊對營建股不利"),
    (("聯準會升息", "Fed升息", "Fed 升息", "美國升息"), (), "🇺🇸", "偏利空",
     "美國升息讓美元資產更吸引人，外資容易從台股匯出（台幣變弱），成長股與高本益比股受壓；美債價格也會跌",
     "成長股、科技股先不追；美債 ETF 分批買不要重壓"),
    (("聯準會降息", "Fed降息", "Fed 降息", "美國降息"), (), "🇺🇸", "偏利多",
     "美國降息讓資金回流股市與新興市場，外資有機會回補台股，債券價格上漲",
     "持股可以抱；美債 ETF 受惠"),
    (("聯準會", "Fed", "鮑爾"), (), "🇺🇸", "看內容",
     "聯準會官員的發言會改變市場對升降息的預期，影響外資進出與科技股",
     "偏鷹派（想升息）對科技股不利，偏鴿派（想降息）有利；先看收盤反應，不要盤中追殺"),
    (("輝達財報", "輝達 財報", "NVIDIA財報", "輝達營收", "輝達 營收"), (), "🟩", "看內容（影響 AI 供應鏈）",
     "輝達是台灣 AI 伺服器、先進封裝、PCB 的最大客戶，財報好壞和下一季展望會直接帶動台積電、廣達、鴻海、緯創、PCB 族群",
     "財報優於預期、展望上修：AI 股有機會反彈；不如預期或下修：先別加碼 AI 股，持股照停損"),
    (("黃仁勳", "輝達 聽證", "輝達 國安", "輝達 調查", "輝達 起訴", "輝達 FBI"), (), "🟩", "偏利空（AI 供應鏈）",
     "輝達執行長捲入國安調查／國會聽證，如果被限制出貨或換掉執行長，台廠訂單可能遞延；市場不確定時會先賣 AI 股",
     "AI 伺服器、PCB、先進封裝持股先不加碼；等聽證結果明朗再說，跌破停損照紀律出場"),
    (("結算",), ("財報",), "📅", "短線偏空（結算前）",
     "外資期貨空單很多時，結算前常有人壓低指數讓空單獲利，結算後賣壓才解除",
     "結算前幾天先不加碼、留一點現金；結算後再看有沒有錯殺的好股"),
    (("關稅",), (), "🌐", "偏利空（出口股）",
     "美國提高關稅會讓台灣出口到美國的貨變貴，電子代工、零組件、傳產出口股獲利受影響；暫緩或豁免則是利多",
     "看標題是加徵（利空）還是暫緩／豁免（利多）；出口比重高的持股留意停損"),
    (("戰爭", "開戰", "飛彈", "軍演"), ("停火",), "⚔️", "偏利空（短線）",
     "地緣衝突讓資金避險，股市先跌、油價和金價上漲；歷史上大多是短線衝擊，除非戰事擴大",
     "不要恐慌殺低；跌破停損才處理；原物料、航運可能受惠"),
    (("停火", "和談", "休戰"), (), "🕊️", "偏利多",
     "衝突降溫，避險資金回到股市，油價、金價回落",
     "照計畫走；先前因戰爭上漲的油、金相關股留意回落"),
    (("熔斷", "崩盤", "股災"), (), "🚨", "利空",
     "市場恐慌性賣壓，短線可能繼續殺；但歷史上暫時性大跌（衰退警訊沒亮）撿好股勝率高",
     "持股照停損處理；抄底等每晚報告的第 1 批訊號，不要盤中接刀"),
]
TIERS = (2, 3.5, 5)


def classify(title):
    """新聞標題 → IMPACT 的一類；對不上就是不重要的新聞（回傳 None）"""
    for kw, ex, icon, eff, why, tip in IMPACT:
        if any(k.replace(" ", "") in title.replace(" ", "") for k in kw) and not any(x in title for x in ex):
            return kw[0], icon, eff, why, tip
    return None


def market_scan(st, seen_px, seen_news, plan_rows, quotes):
    """大盤急漲急跌、重大消息、昨晚推薦股急漲急跌；回傳 (文字區塊清單, 則數)。會更新 st["mkt"]、seen_px、seen_news"""
    blocks, n = [], 0
    ids = ["0050"] + [r["id"] for r in plan_rows]
    try:
        Q = quotes(ids)
    except Exception as e:
        print("大盤報價抓取失敗：", type(e).__name__)
        Q = {}
    now = dt.datetime.now(TW)
    o, z, y = Q.get("0050", (None, None, None))
    z = z or o
    L = []
    if z and y:
        g = (z / y - 1) * 100
        for lv in reversed(TIERS):  # 只發到達的最高一級，較低的級數一併記成已發
            k = "mkt:%s%s" % ("up" if g > 0 else "dn", lv)
            if abs(g) < lv:
                continue
            new = k not in seen_px
            for lo_ in TIERS:
                if lo_ <= lv:
                    seen_px.add("mkt:%s%s" % ("up" if g > 0 else "dn", lo_))
            if new:
                tip = ("大漲不追高，手上有到價的照計畫賣" if g > 0 else
                       "先不要急著賣也不要急著接；持股跌破停損才處理，抄底等每晚報告的第 1 批訊號")
                L.append("%s 大盤（0050）盤中 %+.1f%%，現價 %s（超過 %g%% 門檻）\n　→ 可能原因：%s\n　→ 建議：%s" % (
                    "📈" if g > 0 else "📉", g, exits.px(z), lv, "WHY", tip))
            break
        last = st.get("mkt") or {}
        try:
            mins = (now - dt.datetime.fromisoformat(last["t"])).total_seconds() / 60
        except Exception:
            mins = 999
        if last.get("px") and 0 < mins <= 45 and last.get("day") == now.strftime("%Y-%m-%d"):
            sw = (z / last["px"] - 1) * 100
            cnt = sum(1 for k in seen_px if k.startswith("mkt:sw"))
            if abs(sw) >= 1 and cnt < 4:
                seen_px.add("mkt:sw%s" % now.strftime("%H%M"))
                L.append("⚡ 大盤（0050）%d 分鐘內%s %.1f%%（%s → %s），今天累計 %+.1f%%\n　→ 可能原因：%s" % (
                    mins, "急拉" if sw > 0 else "急殺", abs(sw), exits.px(last["px"]), exits.px(z), g, "WHY"))
        st["mkt"] = {"px": z, "t": now.isoformat(), "day": now.strftime("%Y-%m-%d")}
    # 重大消息：只發對得上 IMPACT 分類的（每則附影響、原因、建議）；同一類一天最多 2 則，避免同一件事各家媒體洗版
    N, today = [], now.strftime("%Y-%m-%d")
    if st.get("big_day") != today:
        st["big_day"], st["big_today"] = today, []
    for q in BIG_Q:
        for it in rss(q, 2):
            c = classify(it["title"])
            if not c:
                continue
            kw, icon, eff, why, tip = c
            h = hashlib.md5(it["title"].encode("utf-8")).hexdigest()[:12]
            cnt = sum(1 for k in seen_px if k.startswith("big:%s:" % kw))
            if h in seen_news or cnt >= 2 or len(N) >= 4:
                continue
            seen_news.add(h)
            seen_px.add("big:%s:%d" % (kw, cnt))
            st["big_today"] = (st.get("big_today") or [])[-5:] + [it["title"][:40]]
            N.append("・%s %s（%s %s）\n　→ 影響：%s\n　→ 原因：%s\n　→ 建議：%s" % (icon, it["title"], it["d"], it["src"], eff, why, tip))
    if L:
        reason = "、".join("「%s」" % t for t in (st.get("big_today") or [])[-2:]) or "沒找到相關的重大新聞，可能是外資進出、期貨或美股影響，先看收盤"
        blocks.append("\n".join(["【大盤】"] + ["・" + x.replace("WHY", reason) for x in L]))
        n += len(L)
    if N:
        blocks.append("\n".join(["【重大消息】"] + N))
        n += len(N)
    P = []
    for r in plan_rows:
        o, z, y = Q.get(r["id"], (None, None, None))
        z = z or o
        if not z or not y:
            continue
        g = (z / y - 1) * 100
        k = "pick:%s:%s" % (r["id"], "up" if g > 0 else "dn")
        if abs(g) >= 4 and k not in seen_px:
            seen_px.add(k)
            P.append("・%s %s %s 盤中 %+.1f%%，現價 %s%s" % ("📈" if g > 0 else "📉", r["id"], r.get("name", ""), g, exits.px(z),
                     "（超過不追價 %s，不要追）" % exits.px(r["chase"]) if g > 0 and r.get("chase") and z > r["chase"] else
                     "（跌破停損價 %s，不要買）" % exits.px(r["stop"]) if r.get("stop") and z <= r["stop"] else ""))
    if P:
        blocks.append("\n".join(["【昨晚推薦的股票】"] + P))
        n += len(P)
    return blocks, n


def digest(cfg, prof, sell_plan=None, hours=30, per=8):
    """每晚報告用：持股的公司新聞＋原料新聞整理（近 hours 小時），每則附利多／利空與建議；沒有持股回傳空字串"""
    H = exits.holdings(cfg)
    if not H:
        return ""
    sp = {x["id"]: x for x in (sell_plan or {}).get("holds", [])}
    hp = (cfg.get("orders") or {}).get("holds_plan") or {}
    out = []
    for sid, h in H.items():
        p, name = prof.get(sid) or {}, (sp.get(sid) or {}).get("name") or sid
        plan = dict(hp.get(sid) or {})
        plan.setdefault("stop", (sp.get(sid) or {}).get("stop"))
        q = {"z": (sp.get(sid) or {}).get("close")}
        short = name.replace("-KY", "")
        seen, comp, raw = set(), [], []
        for it in rss("%s %s" % (short, sid), hours) + rss(short + " 股價", hours):
            if it["title"] not in seen:
                seen.add(it["title"])
                comp.append((it, None))
        for term, sign in raw_terms(p).items():
            for it in rss(term, hours)[:6]:
                if it["title"] not in seen and tone(it["title"]) != 0:
                    seen.add(it["title"])
                    raw.append((it, sign, term.split()[0]))
        if not comp and not raw:
            continue
        L = ["【%s %s】" % (sid, name)]
        if comp:
            L.append("・公司新聞：")
            for it, sign in comp[:per]:
                tag, tip = judge(it, sign, h, q, plan)
                L.append("　%s %s %s（%s）" % (it["d"], tag.split("（")[0], it["title"], it["src"]))
        if raw:
            L.append("・原料／報價新聞：")
            for it, sign, term in raw[:per]:
                tag, tip = judge(it, sign, h, q, plan)
                L.append("　%s［%s］%s %s（%s）" % (it["d"], term, tag.split("（")[0], it["title"], it["src"]))
        ups = sum(1 for it, sg in comp if tone(it["title"], UP + GOOD, DOWN + BAD) > 0) + sum(1 for it, sg, _ in raw if tone(it["title"]) * sg > 0)
        dns = sum(1 for it, sg in comp if tone(it["title"], UP + GOOD, DOWN + BAD) < 0) + sum(1 for it, sg, _ in raw if tone(it["title"]) * sg < 0)
        L.append("・整體：利多 %d 則、利空 %d 則 → %s" % (ups, dns, "偏利多，照計畫抱著" if ups > dns else
                 "偏利空，留意收盤有沒有守住支撐，跌破停損照計畫出場" if dns > ups else "多空都有，先照原本計畫"))
        out.append("\n".join(L))
    if not out:
        return ""
    return "\n\n".join(["📰 持股相關新聞（近 %d 小時，只給自己）" % hours] + out +
                       ["利多／利空依標題的字判斷，可能看錯；拿不準就把新聞貼給 Claude 一起看。"])


def main():
    ld = lambda n, d=None: json.load(open(os.path.join(DIR, n), encoding="utf-8")) if os.path.exists(os.path.join(DIR, n)) else d
    cfg, prof = ld("sop_config.json", {}), ld("stock_profiles.json", {})
    H = exits.holdings(cfg)
    sp = {x["id"]: x for x in (ld("sell_plan.json", {}) or {}).get("holds", [])}
    today = dt.datetime.now(TW).strftime("%Y-%m-%d")
    st = ld("alert_state.json", {}) or {}
    if st.get("day") != today:
        st["px"] = []  # 價位提醒每天重新算
    st["day"] = today
    seen_px, seen_news = set(st.get("px", [])), set(st.get("news", []))
    from morning_check import quotes
    rows = [r for r in (ld("sop_plan.json", {}) or {}).get("rows", []) if r.get("state") == "ok" and r["id"] not in H]
    blocks, n_mkt = market_scan(st, seen_px, seen_news, rows, quotes) if "--no-market" not in sys.argv else ([], 0)
    try:
        Q = {k: {"o": v[0], "z": v[1], "y": v[2]} for k, v in quotes(list(H)).items()} if H else {}
    except Exception as e:
        print("報價抓取失敗：", type(e).__name__)
        Q = {}
    hp = (cfg.get("orders") or {}).get("holds_plan") or {}
    n_px, n_news = 0, 0
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
            if sign is None and tone(it["title"], UP + GOOD, DOWN + BAD) == 0:  # 看不出利多利空的公司新聞不發（不重要）
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
            g = tone(it["title"], UP + GOOD, DOWN + BAD) if sign is None else tone(it["title"]) * sign
            why = ("公司本身的%s消息，通常會反映在股價上" % ("好" if g > 0 else "壞") if sign is None else
                   "原料%s，%s" % ("漲" if tone(it["title"]) > 0 else "跌", "這家公司的產品報價通常跟著原料走，所以對獲利是同方向" if sign > 0 else "原料是這家公司的成本，所以對獲利是反方向"))
            L.append("・%s新聞（%s %s）：%s\n　→ 影響：%s\n　→ 原因：%s\n　→ 建議：%s" % ("原料" if sign is not None else "公司", it["d"], it["src"], it["title"], tag.split("（")[0], why, tip))
            seen_news.add(k)
            n_news += 1
        blocks.append("\n".join(L))
    st["px"], st["news"] = sorted(seen_px), list(seen_news)[-800:]
    if not blocks:
        print("沒有新的提醒")
    else:
        now = dt.datetime.now(TW).strftime("%m/%d %H:%M")
        text = "\n\n".join(["⚡ 盤中即時提醒（%s）" % now] + blocks +
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
        print("已發送：大盤與重大消息 %d 則、價位提醒 %d 則、新聞 %d 則" % (n_mkt, n_px, n_news))
    if not DRY:
        json.dump(st, open(STATE, "w", encoding="utf-8"), ensure_ascii=False)


if __name__ == "__main__":
    main()
