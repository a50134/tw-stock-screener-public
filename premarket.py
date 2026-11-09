"""
premarket.py - 開盤前觀察：台指期夜盤、美股收盤、美股期貨，評估今天台股開盤偏多或偏空

資料來源（都不用金鑰）：
  台指期夜盤  期交所行情（mis.taifex.com.tw，盤後交易）；抓不到改用期交所 OpenAPI 每日行情
  美股、期貨  Yahoo Finance：S&P 500、那斯達克、道瓊、費城半導體、台積電 ADR、VIX，
              S&P／那斯達克期貨（台灣早上仍在交易，反映美股收盤後到現在的變化）
評估：台指期夜盤最重要（已經反映前一晚美股），再參考費半、那斯達克期貨、台積電 ADR。
用法：python premarket.py [--debug]   # 單獨執行印出結果；--debug 另外印出原始資料方便除錯
"""
import json
import sys
import time
import urllib.request

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}
DEBUG = "--debug" in sys.argv

US = [  # (代號, 名稱, 權重)
    ("^GSPC", "S&P 500", 0), ("^IXIC", "那斯達克", 0), ("^DJI", "道瓊", 0),
    ("^SOX", "費城半導體", 0.2), ("TSM", "台積電 ADR", 0.15),
]
FUT = [("ES=F", "S&P 期貨", 0), ("NQ=F", "那斯達克期貨", 0.15)]
POLICY_Q = ["國安基金", "金管會 穩定市場", "限空令", "央行 理監事會", "央行 利率"]
RESCUE = ("國安基金", "護盤", "限空", "穩定市場措施", "救市")  # 標題有這些字＝政府出手穩定股市（歷史上隔天上漲機率約 86%）
POLICY_KW = RESCUE + ("央行", "升息", "降息", "金管會")


def policy_news(hours=20):
    """近 hours 小時的國內政策重大新聞（Google 新聞，不用金鑰）。回傳 [(時間, 標題, 是否護盤)]，最多 3 則"""
    import email.utils
    import urllib.parse
    import xml.etree.ElementTree as ET
    from datetime import datetime, timedelta, timezone
    cut, out, seen = datetime.now(timezone.utc) - timedelta(hours=hours), [], set()
    for q in POLICY_Q:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote(q + " when:1d") + "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
        try:
            req = urllib.request.Request(url, headers=UA)
            with urllib.request.urlopen(req, timeout=15) as r:
                root = ET.fromstring(r.read())
        except Exception as e:
            if DEBUG:
                print("[policy] 失敗", q, e, flush=True)
            continue
        for it in root.iter("item"):
            t = (it.findtext("title") or "").rsplit(" - ", 1)[0].strip()
            try:
                pub = email.utils.parsedate_to_datetime(it.findtext("pubDate"))
                pub = pub if pub.tzinfo else pub.replace(tzinfo=timezone.utc)
            except Exception:
                continue
            if not t or t in seen or pub < cut or not any(k in t for k in POLICY_KW):
                continue
            seen.add(t)
            out.append((pub.astimezone(timezone(timedelta(hours=8))).strftime("%m-%d %H:%M"), t, any(k in t for k in RESCUE)))
    out.sort(key=lambda x: (not x[2], x[0]), reverse=False)
    return out[:3]


def get(url, data=None, headers=None, timeout=15):
    h = dict(UA, **(headers or {}))
    req = urllib.request.Request(url, data=data, headers=h)
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return json.loads(r.read().decode("utf-8-sig"))


def num(v):
    try:
        v = float(str(v).replace(",", "").replace("%", ""))
        return v
    except (TypeError, ValueError):
        return None


def yahoo(sym):
    """回傳 (最新價, 漲跌%, 資料日)；最新價和前一筆收盤比"""
    last_err = None
    for host in ("query1", "query2"):
        try:
            j = get("https://%s.finance.yahoo.com/v8/finance/chart/%s?range=1d&interval=1d" % (host, urllib.request.quote(sym)))
            m = j["chart"]["result"][0].get("meta", {})
            px = m.get("regularMarketPrice")
            prev = m.get("chartPreviousClose") or m.get("previousClose")  # range=1d 時就是前一個交易日（期貨是前一日結算）
            day = time.strftime("%m/%d", time.gmtime(m.get("regularMarketTime") or 0))
            if DEBUG:
                print("[yahoo]", sym, px, prev, day, flush=True)
            return px, (px / prev - 1) * 100 if px and prev else None, day
        except Exception as e:
            last_err = e
            time.sleep(1)
    raise RuntimeError("%s：%s" % (sym, last_err))


def tx_night():
    """台指期近月夜盤：回傳 (最新價, 漲跌點, 漲跌%, 說明)"""
    # 1) 期交所行情網（盤後 MarketType=1）
    try:
        body = json.dumps({"MarketType": "1", "SymbolType": "F", "KindID": "1", "CID": "TXF", "ExpireMonth": "",
                           "RowSize": "全部", "PageNo": "", "SortColumn": "", "AscDesc": "A"}).encode()
        j = get("https://mis.taifex.com.tw/futures/api/getQuoteList", data=body, headers={"Content-Type": "application/json"})
        ql = (j.get("RtData") or {}).get("QuoteList") or []
        if DEBUG:
            print("[taifex mis]", json.dumps(ql[:3], ensure_ascii=False)[:1500], flush=True)
        for q in ql:  # 第一筆通常是現貨指數或近月，挑有成交價、名稱是臺指期、非價差的
            name, sid = str(q.get("DispCName", "")), str(q.get("SymbolID", ""))
            if "/" in name or not sid.startswith("TXF"):
                continue
            last, ref = num(q.get("CLastPrice")), num(q.get("CRefPrice"))
            if last and ref:
                tm = str(q.get("CTime", "")).zfill(6)
                return last, last - ref, (last / ref - 1) * 100, "%s 夜盤 %s:%s 成交" % (name, tm[:2], tm[2:4])
    except Exception as e:
        if DEBUG:
            print("[taifex mis] 失敗", e, flush=True)
    # 2) 期交所 OpenAPI 每日行情（盤後交易時段）
    j = get("https://openapi.taifex.com.tw/v1/DailyMarketReportFut", timeout=30)
    rows = [r for r in j if str(r.get("Contract")) == "TX" and "/" not in str(r.get("ContractMonth(Week)", "/"))
            and "盤後" in str(r.get("TradingSession", ""))]
    if DEBUG:
        print("[taifex openapi]", json.dumps(rows[:2], ensure_ascii=False)[:1500], flush=True)
    rows.sort(key=lambda r: str(r.get("ContractMonth(Week)")))
    r = rows[0]
    last, chg = num(r.get("Last")), num(r.get("Change"))
    pct = num(r.get("%")) if num(r.get("%")) is not None else (chg / (last - chg) * 100 if last and chg is not None else None)
    return last, chg, pct, "臺指期 %s 夜盤（%s）" % (r.get("ContractMonth(Week)"), r.get("Date"))


def overview():
    """回傳 (文字, 分數)；分數 > 0 偏多、< 0 偏空；全部抓不到回傳 ("", None)"""
    L, why, score, wsum = [], [], 0.0, 0.0
    try:
        last, chg, pct, desc = tx_night()
        L.append("・台指期夜盤：%s（%+.0f 點，%+.2f%%）｜%s" % ("{:,.0f}".format(last), chg, pct, desc))
        score += pct * 0.5
        wsum += 0.5
        if abs(pct) >= 0.5:
            why.append("台指期夜盤%s %.1f%%" % ("漲" if pct > 0 else "跌", abs(pct)))
    except Exception as e:
        L.append("・台指期夜盤：抓不到（%s）" % str(e)[:60])
    us, fut = [], []
    for grp, out in ((US, us), (FUT, fut)):
        for sym, name, w in grp:
            try:
                px, pct, day = yahoo(sym)
                out.append("%s %s%%" % (name, "%+.2f" % pct if pct is not None else "—"))
                if pct is not None and w:
                    score += pct * w
                    wsum += w
                    if abs(pct) >= 1:
                        why.append("%s%s %.1f%%" % (name, "漲" if pct > 0 else "跌", abs(pct)))
            except Exception as e:
                out.append("%s —" % name)
                if DEBUG:
                    print("[yahoo] 失敗", e, flush=True)
    if us:
        L.append("・美股收盤：" + "、".join(us))
    if fut:
        L.append("・美股期貨（現在）：" + "、".join(fut))
    try:
        vix, vp, _ = yahoo("^VIX")
        L.append("・恐慌指數 VIX：%.1f（%+.1f%%）%s" % (vix, vp or 0, "，偏高，市場緊張" if vix >= 25 else ""))
        if vix >= 25 or (vp or 0) >= 15:
            why.append("VIX 升到 %.1f" % vix)
            score -= 0.2
    except Exception:
        pass
    rescue = False
    try:  # 國內政策重大消息（國安基金、央行、金管會）：常在收盤後或週末宣布
        pn = policy_news()
        rescue = any(x[2] for x in pn)
        for d, t, r in pn:
            L.append("・%s 政策消息（%s）：%s" % ("🛡️" if r else "🏛️", d, t))
    except Exception as e:
        if DEBUG:
            print("[policy] 失敗", e, flush=True)
    if not wsum:
        return "", None
    s = score / wsum
    if rescue:
        why.append("政府護盤（國安基金／金管會）")
    if s >= 0.8:
        verdict, tip = "📈 偏多（可能開高）", "可能開高：名單股票注意不追價，高於「不追價」就掛單等回檔"
    elif s >= 0.3:
        verdict, tip = "小漲", "氣氛偏正面，照開盤檢查的規則買"
    elif s > -0.3:
        verdict, tip = "持平", "沒有明顯方向，照開盤檢查的規則買"
    elif s > -0.8:
        verdict, tip = "小跌", "可能小幅開低：分兩批買，第一批先買一半"
    else:
        verdict, tip = "📉 偏空（可能開低）", "可能開低：先觀察 15 分鐘，止跌再買、只買一半；持股留意停損"
    if rescue and s < 0.8:
        tip += "；政府已出手護盤，急跌後的強勢龍頭股可以小量分批買，不要一次買滿"
    head = "🌙 開盤前觀察：%s（綜合分數 %+.2f）" % (verdict, s)
    return "\n".join([head] + L + ["・原因：" + ("、".join(why) if why else "各項變動都不大"), "・建議：" + tip]), s


if __name__ == "__main__":
    t, s = overview()
    print(t or "全部資料都抓不到")
