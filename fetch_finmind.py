"""
fetch_finmind.py - 從 FinMind 抓台股資料，輸出成「條件選股室」可匯入的 data.json

內容：日K、三大法人買賣超、外資持股比率、融資融券餘額、當沖成交量、
      千張大戶／散戶持股（每週集保）、近 30 天個股新聞、月營收、季財報（EPS、毛利率、營益率、
      淨利率、ROE）、本益比／淨值比／殖利率

用法：
  pip install requests
  (可選) 設定 token：寫在 .env（FINMIND_TOKEN 或 TSL_FINMIND_TOKEN），或 Windows 用 set FINMIND_TOKEN=你的token
                     mac/Linux 用 export FINMIND_TOKEN=你的token
  python fetch_finmind.py                 # 用內建清單
  python fetch_finmind.py 2330 2317 2454  # 自訂代號
  python fetch_finmind.py --macro          # 早上只更新國際新聞，產生 macro.json
  python fetch_finmind.py 代號... --lite --days 750 --out data_bt.json   # 回測用：只抓價量、法人、融資券、營收、財報、本益比

每檔股票需要 11 次請求。免 token 每小時約 300 次，大約 25 檔；
集保持股分級與當沖資料若帳號等級不足會是空的，網頁會顯示「沒有此項目」。
檔數多時建議到 FinMind 官網申請免費 token。
"""
import os
import re
import sys
import json
import time
import datetime as dt
import email.utils
import urllib.parse
import xml.etree.ElementTree as ET

import requests

try:  # 讓 requests 使用 Windows／系統憑證庫（有些防毒或公司網路會造成 certifi 憑證驗證失敗）
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = ""  # main() 讀完 .env 後設定

def load_env():
    """讀 .env 檔（KEY=VALUE），不覆蓋已經設定的環境變數。
    找檔順序：--env 指定的檔案 → 目前資料夾的 .env → 桌面 Claude-project/stock-analysis-lab/.env"""
    paths = []
    if "--env" in sys.argv:
        i = sys.argv.index("--env")
        if i + 1 < len(sys.argv):
            paths.append(sys.argv[i + 1])
            del sys.argv[i:i + 2]
    paths += [".env", os.path.join(os.path.expanduser("~"), "Desktop", "Claude-project", "stock-analysis-lab", ".env")]
    for p in paths:
        if os.path.isfile(p):
            with open(p, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip().removeprefix("export ").strip(), v.strip().strip("\"'")
                    os.environ.setdefault(k, v)
                    os.environ.setdefault(k.upper(), v)
            return p
    return None

DAYS = 400  # 保留的交易日數（約一年半，K 線可往前拉）
DEFAULT = (
    "2330 2317 2454 2308 2382 3231 2345 3017 2303 3711 "
    "2881 2882 2891 2412 1301 2002 2603 2609 1519 2344"
).split()


def get(dataset, sid="", start=""):
    params = {"dataset": dataset}
    if sid:
        params["data_id"] = sid
    if start:
        params["start_date"] = start
    if TOKEN:
        params["token"] = TOKEN
    for attempt in range(10):
        try:
            r = requests.get(API, params=params, timeout=30)
            j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code == 200 and j.get("status") == 200:
                return j.get("data", [])
            msg = str(j.get("msg", r.status_code))
            if r.status_code == 402 or "limit" in msg.lower():  # 每小時請求上限：等 10 分鐘再試
                print("  … 到達 FinMind 請求上限，10 分鐘後繼續", file=sys.stderr, flush=True)
                time.sleep(600)
                continue
            print("  ! FinMind 回應：", msg, file=sys.stderr)
            if attempt >= 2:
                break
        except requests.RequestException as e:
            print("  ! 連線錯誤：", e, file=sys.stderr)
        time.sleep(3 * (attempt + 1))
    print("  ! 無法取得", dataset, file=sys.stderr)  # 不印代號（公開執行紀錄）
    return []


def ffill(arr):
    """缺值沿用前一天；開頭缺值用第一個有效值。"""
    first = next((x for x in arr if x is not None), None)
    last = first
    out = []
    for x in arr:
        if x is None:
            out.append(last)
        else:
            out.append(x)
            last = x
    return out


def pick(d, *names):
    for n in names:
        if d.get(n) is not None:
            return d[n]
    return None


def quarters(fin, bal):
    """整理季財報：單季 EPS、毛利率、營益率、淨利率、ROE（%）。"""
    by = {}
    for d in fin:
        by.setdefault(d["date"], {})[d["type"]] = d["value"]
    eq = {}
    for d in bal:
        eq.setdefault(d["date"], {})[d["type"]] = d["value"]
    out = []
    for date in sorted(by):
        y, m = int(date[:4]), int(date[5:7])
        if m not in (3, 6, 9, 12):
            continue
        x = by[date]
        rev = pick(x, "Revenue", "OperatingRevenue")
        gp = pick(x, "GrossProfit")
        op = pick(x, "OperatingIncome")
        ni = pick(x, "IncomeAfterTaxes", "NetIncome")
        eps = pick(x, "EPS")
        e = eq.get(date, {})
        equity = pick(e, "EquityAttributableToOwnersOfParent", "Equity", "TotalEquity")
        pct = lambda a: round(a / rev * 100, 2) if (a is not None and rev) else None
        out.append({
            "q": "%dQ%d" % (y, m // 3),
            "eps": round(eps, 2) if eps is not None else None,
            "gm": pct(gp), "om": pct(op), "nm": pct(ni),
            "roe": round(ni / equity * 100, 2) if (ni is not None and equity) else None,
        })
    return [q for q in out if q["eps"] is not None]


# 國際情勢：用 Google 新聞 RSS 搜尋重要人物與事件（不需要帳號）
MACRO_Q = [
    "川普 關稅", "川普 台灣", "川普 晶片", "川普 中國", "Trump tariff",
    "聯準會 利率", "鮑爾", "黃仁勳", "美國 出口管制 晶片", "台海 軍演",
    "美股 暴跌", "中國 經濟 刺激", "油價 OPEC",
    # 原料／報價（循環股用：原料大漲大跌時，平均高低點的買賣價位要調整）
    "鋼價 調漲", "銅價", "貨櫃 運價 SCFI", "散裝 BDI", "塑化 報價", "水泥 價格", "面板 報價", "記憶體 報價", "紙價",
]


def macro_news(days=3):
    out, seen = [], set()
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    tw = dt.timezone(dt.timedelta(hours=8))
    for q in MACRO_Q:
        url = ("https://news.google.com/rss/search?q=" + urllib.parse.quote("%s when:%dd" % (q, days))
               + "&hl=zh-TW&gl=TW&ceid=TW:zh-Hant")
        try:
            r = requests.get(url, timeout=20, headers={"User-Agent": "Mozilla/5.0"})
            root = ET.fromstring(r.content)
        except Exception as e:  # 網路或格式問題就跳過這個關鍵字
            print("  ! 國際新聞抓取失敗：", q, e, file=sys.stderr)
            if "CERTIFICATE_VERIFY_FAILED" in str(e):
                print("    憑證驗證失敗，可先執行 pip install --upgrade certifi 再試", file=sys.stderr)
            continue
        for it in root.iter("item"):
            title = (it.findtext("title") or "").strip()
            if not title or title in seen:
                continue
            try:
                pub = email.utils.parsedate_to_datetime(it.findtext("pubDate"))
            except Exception:
                pub = None
            if pub and pub < cutoff:
                continue
            seen.add(title)
            src = it.find("source")
            out.append({
                "d": pub.astimezone(tw).strftime("%Y-%m-%d %H:%M") if pub else "",
                "title": title,
                "src": src.text if src is not None else "",
                "link": it.findtext("link") or "",
                "q": q,
            })
        time.sleep(0.5)
    out.sort(key=lambda x: x["d"], reverse=True)
    return out[:200]


def level_range(s):
    """集保持股分級字串 -> (下限股數, 上限股數)，無法辨識回傳 None。"""
    if any(k in s for k in ("差異", "total", "合計")):
        return None
    nums = [int(x.replace(",", "")) for x in re.findall(r"\d[\d,]*", s)]
    if len(nums) >= 2:
        return nums[0], nums[1]
    if len(nums) == 1 and ("more" in s or "以上" in s):
        return nums[0], float("inf")
    return None


def holders(rows):
    """每週：千張以上大戶持股 %、50 張以下散戶持股 %。"""
    by = {}
    for d in rows:
        rg = level_range(str(d.get("HoldingSharesLevel", "")))
        if not rg:
            continue
        w = by.setdefault(d["date"], {"big": 0.0, "ret": 0.0})
        if rg[0] > 1_000_000:
            w["big"] += d.get("percent") or 0
        elif rg[1] <= 50_000:
            w["ret"] += d.get("percent") or 0
    return [{"d": k, "big": round(v["big"], 2), "ret": round(v["ret"], 2)} for k, v in sorted(by.items())]


HS_OK = [False]  # FinMind 集保持股分級要付費等級才有；改用 tdcc.py（集保開放資料，免費）


def main():
    global TOKEN
    load_env()
    TOKEN = (os.environ.get("FINMIND_TOKEN") or os.environ.get("TSL_FINMIND_TOKEN", "")).strip()
    print("FinMind token：", "已設定" if TOKEN else "未設定（免 token 每小時約 300 次請求）")
    if "--macro" in sys.argv:
        nd = sys.argv[sys.argv.index("--news-days") + 1] if "--news-days" in sys.argv else "3"
        m = macro_news(days=int(nd))  # 週末／連假會多抓幾天，涵蓋最後一個交易日之後的新聞
        with open("macro.json", "w", encoding="utf-8") as f:
            json.dump({"asOf": dt.datetime.now().strftime("%Y-%m-%d %H:%M"), "macro": m}, f, ensure_ascii=False)
        print("完成：macro.json（%d 則國際新聞）" % len(m))
        return
    global DAYS
    args, opt = [], {}
    it = iter(sys.argv[1:])
    for a in it:
        if a in ("--days", "--out", "--cache", "--news-days"):
            opt[a] = next(it, "")
        elif not a.startswith("-"):
            args.append(a)
    lite = "--lite" in sys.argv
    DAYS = int(opt.get("--days", DAYS))
    out_path = opt.get("--out", "data.json")
    ids = args or DEFAULT
    today = dt.date.today()
    start_px = (today - dt.timedelta(days=int(DAYS * 1.5))).isoformat()
    start_rev = min(dt.date(today.year - 3, 1, 1), today - dt.timedelta(days=int(DAYS * 1.5) + 400)).isoformat()
    start_per = (today - dt.timedelta(days=20)).isoformat()
    start_news = (today - dt.timedelta(days=30)).isoformat()

    # --cache 上一份 data.json：月營收、季財報不是每天變，非公布期間沿用，少抓 1/3 請求
    cache = {}
    if opt.get("--cache") and os.path.exists(opt["--cache"]):
        try:
            cache = {x["id"]: x for x in json.load(open(opt["--cache"], encoding="utf-8"))["stocks"]}
            print("沿用上一份資料的營收／財報：%d 檔可用" % len(cache))
        except Exception as e:
            print("  ! 讀不到快取：", e, file=sys.stderr)
    want_rev = (today.replace(day=1) - dt.timedelta(days=1)).strftime("%Y-%m") if today.day > 10 else None
    fin_season = today.month in (3, 4, 5, 8, 11)  # 年報 3/31、Q1 5/15、Q2 8/14、Q3 11/14 前後

    info = {d["stock_id"]: d for d in get("TaiwanStockInfo")}
    raw = {}
    all_dates = set()
    for k, sid in enumerate(ids, 1):
        print("抓取 %d/%d" % (k, len(ids)), flush=True)  # 不印代號：公開專案的執行紀錄任何人都看得到（持股混在清單裡）
        etf = sid.startswith("00")  # ETF 沒有營收、財報、本益比，少抓 3 次省額度
        old = cache.get(sid) or {}
        old_rev = old.get("rev") or []
        keep_rev = not etf and today.day > 12 and old_rev and want_rev and old_rev[-1]["m"] >= want_rev
        keep_fin = not etf and not fin_season and bool(old.get("q"))
        r = {
            "px": get("TaiwanStockPrice", sid, start_px),
            "inst": get("TaiwanStockInstitutionalInvestorsBuySell", sid, start_px),
            "hold": [] if lite else get("TaiwanStockShareholding", sid, start_px),
            "margin": get("TaiwanStockMarginPurchaseShortSale", sid, start_px),
            "rev": [] if etf or keep_rev else get("TaiwanStockMonthRevenue", sid, start_rev),
            "fin": [] if etf or keep_fin else get("TaiwanStockFinancialStatements", sid, start_rev),
            "bal": [] if lite else get("TaiwanStockBalanceSheet", sid, start_rev),
            "per": [] if etf else get("TaiwanStockPER", sid, start_per),
            "hs": get("TaiwanStockHoldingSharesPer", sid, start_px) if HS_OK[0] and not lite else [],
            "dt": [] if lite else get("TaiwanStockDayTrading", sid, start_px),
            "news": [] if lite else get("TaiwanStockNews", sid, start_news),
        }
        if not r["hs"] and HS_OK[0] and not lite:
            HS_OK[0] = False
            print("  （帳號等級抓不到集保持股分級，其餘股票略過這項）")
        if keep_rev:
            r["rev_cached"] = old_rev
        if keep_fin:
            r["q_cached"] = old["q"]
        raw[sid] = r
        all_dates.update(d["date"] for d in r["px"])
        time.sleep(0.3)

    dates = sorted(all_dates)[-DAYS:]
    idx = {d: i for i, d in enumerate(dates)}
    n = len(dates)
    stocks = []
    for sid, r in raw.items():
        if not r["px"]:
            continue
        o, h, l, c, v = [None] * n, [None] * n, [None] * n, [None] * n, [0] * n
        for d in r["px"]:
            i = idx.get(d["date"])
            if i is None or not d["close"]:
                continue
            o[i], h[i], l[i], c[i] = d["open"], d["max"], d["min"], d["close"]
            v[i] = round(d["Trading_Volume"] / 1000)  # 股 -> 張
        c = ffill(c)
        o = [o[i] if o[i] is not None else c[i] for i in range(n)]
        h = [h[i] if h[i] is not None else c[i] for i in range(n)]
        l = [l[i] if l[i] is not None else c[i] for i in range(n)]

        fi, it, dl = [0] * n, [0] * n, [0] * n
        for d in r["inst"]:
            i = idx.get(d["date"])
            if i is None:
                continue
            net = round((d["buy"] - d["sell"]) / 1000)  # 股 -> 張
            name = d["name"]
            if name.startswith("Foreign"):
                fi[i] += net
            elif name == "Investment_Trust":
                it[i] += net
            elif name.startswith("Dealer"):
                dl[i] += net

        frh = [None] * n
        for d in r["hold"]:
            i = idx.get(d["date"])
            if i is not None:
                frh[i] = d.get("ForeignInvestmentSharesRatio")
        mg, sh = [None] * n, [None] * n
        for d in r["margin"]:
            i = idx.get(d["date"])
            if i is not None:
                mg[i] = d.get("MarginPurchaseTodayBalance")  # 張
                sh[i] = d.get("ShortSaleTodayBalance")       # 張

        dtv = [None] * n  # 當沖成交量（張）
        for d in r["dt"]:
            i = idx.get(d["date"])
            if i is not None and d.get("Volume") is not None:
                dtv[i] = round(d["Volume"] / 1000)

        months = {}
        for d in r["rev"]:
            m = "%04d-%02d" % (d["revenue_year"], d["revenue_month"])
            months[m] = round(d["revenue"] / 1000)  # 元 -> 千元
        revs = r.get("rev_cached") or [{"m": m, "v": months[m]} for m in sorted(months)]

        pe = pb = dy = None
        if r["per"]:
            last = r["per"][-1]
            pe, pb, dy = last.get("PER"), last.get("PBR"), last.get("dividend_yield")

        shares = None  # 發行股數（張），用來算「占股本」
        for d in reversed(r["hold"]):
            if d.get("NumberOfSharesIssued"):
                shares = round(d["NumberOfSharesIssued"] / 1000)
                break

        meta = info.get(sid, {})
        stocks.append({
            "shares": shares,
            "id": sid,
            "name": meta.get("stock_name", sid),
            "industry": "ETF" if sid.startswith("00") else meta.get("industry_category", "其他"),
            "pe": pe, "pb": pb, "yield": dy,
            "o": o, "h": h, "l": l, "c": c, "v": v,
            "fi": fi, "it": it, "dl": dl,
            "frh": ffill(frh) if any(x is not None for x in frh) else None,
            "mg": ffill(mg) if any(x is not None for x in mg) else None,
            "sh": ffill(sh) if any(x is not None for x in sh) else None,
            "dt": [x or 0 for x in dtv] if any(x is not None for x in dtv) else None,
            "hw": holders(r["hs"]),
            "news": [{"d": str(d.get("date", ""))[:10], "title": d.get("title", ""),
                      "src": d.get("source", ""), "link": d.get("link", "")}
                     for d in sorted(r["news"], key=lambda x: str(x.get("date", "")), reverse=True)[:60]
                     if d.get("title")],
            "rev": revs,
            "q": r.get("q_cached") or quarters(r["fin"], r["bal"]),
        })

    print("抓取國際新聞")
    out = {"source": "FinMind", "asOf": dates[-1], "dates": dates, "stocks": stocks, "macro": [] if lite else macro_news()}
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False)
    print("完成：%s（%d 檔，%d 個交易日）" % (out_path, len(stocks), n))


if __name__ == "__main__":
    main()
