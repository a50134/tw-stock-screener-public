"""
market.py - 全市場（上市＋上櫃，約 2,000 檔股票與 ETF）每日行情與法人買賣超，給網頁版「查任何一檔」用

資料來源（都不用金鑰，證交所／櫃買中心公開資料）：
  上市 日成交：twse.com.tw MI_INDEX（全部，不含權證）    上市 法人：T86
  上櫃 日成交：tpex.org.tw daily_close_quotes            上櫃 法人：3itrade_hedge
快取：market_hist.json（{日期: {代號: [開, 高, 低, 收, 張數, 外資, 投信]}}，只留最近 KEEP 個交易日）
輸出：site_m/index.json（[[代號, 名稱, 市場], ...]）、site_m/<代號前兩碼>.json（{dates, s: {代號: {n, o,h,l,c,v,fi,it}}}）

用法：
  python market.py              # 補齊到今天（第一次會往回補 KEEP 個交易日，約 30～40 分鐘）
  python market.py --days 5     # 只往回檢查 5 天（每晚用）
"""
import datetime as dt
import json
import os
import sys
import time
import urllib.parse
import urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
CACHE = os.path.join(DIR, "market_hist.json")
OUT = os.path.join(DIR, "site_m")
KEEP = 130  # 約半年
UA = {"User-Agent": "Mozilla/5.0"}


def get(url):
    for k in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read().decode("utf-8-sig"))
        except Exception as e:
            if k == 2:
                raise
            time.sleep(8)


def num(x):
    try:
        x = str(x).replace(",", "").strip()
        return float(x) if x not in ("", "--", "---", "-", "除權息", "除息", "除權") else None
    except ValueError:
        return None


def keep_id(code):
    """只留股票（4 碼數字）與 ETF（00 開頭）；權證、特別股、債券不要"""
    return (len(code) == 4 and code.isdigit() and not code.startswith("0")) or (code.startswith("00") and 4 <= len(code) <= 6)


def fetch_day(d):
    """一天的全市場資料；休市回傳 None。回傳 ({代號: [o,h,l,c,v,fi,it]}, {代號: (名稱, 市場)})"""
    ymd, roc = d.strftime("%Y%m%d"), "%d/%02d/%02d" % (d.year - 1911, d.month, d.day)
    j = get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=%s&type=ALLBUT0999&response=json" % ymd)
    tab = next((t for t in (j.get("tables") or []) if (t.get("fields") or [None])[0] == "證券代號" and "收盤價" in (t.get("fields") or [])), None)
    if j.get("stat") != "OK" or not tab or not tab.get("data"):
        return None, None
    rows, names = {}, {}
    f = tab["fields"]
    io, ih, il, ic, iv = f.index("開盤價"), f.index("最高價"), f.index("最低價"), f.index("收盤價"), f.index("成交股數")
    for r in tab["data"]:
        code = r[0].strip()
        if not keep_id(code):
            continue
        c = num(r[ic])
        rows[code] = [num(r[io]), num(r[ih]), num(r[il]), c, round((num(r[iv]) or 0) / 1000), 0, 0]
        names[code] = (r[1].strip(), "上市")
    time.sleep(3)
    t = get("https://www.twse.com.tw/rwd/zh/fund/T86?date=%s&selectType=ALLBUT0999&response=json" % ymd)
    for r in t.get("data") or []:  # [4] 外陸資買賣超（不含外資自營商）、[7] 外資自營商買賣超、[10] 投信買賣超（股）
        code = r[0].strip()
        if code in rows:
            rows[code][5] = round(((num(r[4]) or 0) + (num(r[7]) or 0)) / 1000)
            rows[code][6] = round((num(r[10]) or 0) / 1000)
    time.sleep(3)
    try:
        otc = fetch_otc(d)
    except Exception as e:  # 上櫃出錯不影響上市
        print(d, "上櫃抓取失敗：", e, flush=True)
        otc = None
    if otc:
        rows.update(otc[0])
        names.update(otc[1])
    return rows, names


def raw(url, form=None):
    """只試一次（上櫃探測用，失敗就換下一個來源），回傳 JSON；不是 JSON 時把開頭印出來方便查"""
    data = urllib.parse.urlencode(form).encode() if form else None
    req = urllib.request.Request(url, data=data, headers=dict(UA, **({"Content-Type": "application/x-www-form-urlencoded"} if form else {})))
    with urllib.request.urlopen(req, timeout=30) as r:
        txt = r.read().decode("utf-8-sig", "replace")
    try:
        return json.loads(txt)
    except ValueError:
        raise ValueError("不是 JSON：" + " ".join(txt[:150].split()))


def otc_sources(d):
    """櫃買中心上櫃日行情的幾種網址（新版網站要用 POST）；依序試，第一個日期對的就用"""
    ymd, roc = d.strftime("%Y/%m/%d"), "%d/%02d/%02d" % (d.year - 1911, d.month, d.day)
    new = "https://www.tpex.org.tw/www/zh-tw/afterTrading/dailyQ"
    # 實測（2026-10）：「舊版otc」會照日期回傳；「舊版se」只回最新一天；新版網址 404。依序試，日期核對不過就換下一個
    return [("舊版otc", "https://www.tpex.org.tw/web/stock/aftertrading/otc_quotes_no1430/stk_wn1430_result.php?l=zh-tw&o=json&se=EW&d=%s" % roc, None),
            ("舊版se", "https://www.tpex.org.tw/web/stock/aftertrading/daily_close_quotes/stk_quote_result.php?l=zh-tw&o=json&se=EW&d=%s" % roc, None),
            ("新版POST", new, {"date": ymd, "type": "EW", "response": "json"})]


def otc_table(t):
    """是不是上櫃日行情表：第一欄是代號、有收盤價、而且有資料"""
    f = [str(x) for x in (t.get("fields") or [])]
    return bool(f) and "代號" in f[0] and any("收盤" in x for x in f) and bool(t.get("data"))


def same_day(x, d):
    """櫃買回傳的日期（115/09/01、20260901、2026/09/01 都可能）是否就是要的那天"""
    x = str(x or "").replace("/", "").replace("-", "").strip()
    return x in (d.strftime("%Y%m%d"), "%d%02d%02d" % (d.year - 1911, d.month, d.day))


def fetch_otc(d):
    """上櫃一天的行情＋法人；抓不到或櫃買回的不是那一天就回傳 None（寧可缺，不要錯）"""
    roc = "%d/%02d/%02d" % (d.year - 1911, d.month, d.day)
    tab = None
    for name, url, form in otc_sources(d):
        try:
            j = raw(url, form)
        except Exception as e:
            print(d, "上櫃來源", name, "失敗：", str(e)[:160], flush=True)
            continue
        t = next((t for t in (j.get("tables") or []) if otc_table(t)), None)
        if not t and (j.get("aaData") or j.get("data")):  # 舊格式：沒有 tables，直接 aaData
            t = {"fields": ["代號", "名稱", "收盤", "漲跌", "開盤", "最高", "最低", "均價", "成交股數"], "data": j.get("aaData") or j.get("data"),
                 "date": j.get("reportDate") or j.get("date")}
        got = (t or {}).get("date") or j.get("date") or j.get("reportDate")
        if t and t.get("data") and same_day(got, d):
            tab = t
            break
        print(d, "上櫃來源", name, "日期不符或沒有資料：", got, [(x.get("title"), (x.get("fields") or [])[:9], len(x.get("data") or [])) for x in (j.get("tables") or [])][:3], flush=True)
    if not tab:
        return None
    f = [str(x).strip() for x in tab["fields"]]
    col = lambda *ns: next((i for n in ns for i, x in enumerate(f) if n in x), None)  # 欄名只要包含關鍵字就算（各版欄名略有不同）
    ic, io, ih, il, iv = col("收盤"), col("開盤"), col("最高"), col("最低"), col("成交股數", "成交量")
    print(d, "上櫃欄位：", f[:10], flush=True) if d.day == 1 else None
    rows, names = {}, {}
    for r in tab["data"]:
        code = str(r[0]).strip()
        if not keep_id(code):
            continue
        rows[code] = [num(r[io]), num(r[ih]), num(r[il]), num(r[ic]), round((num(r[iv]) or 0) / 1000), 0, 0]
        names[code] = (str(r[1]).strip(), "上櫃")
    time.sleep(3)
    oi = get("https://www.tpex.org.tw/web/stock/3insti/daily_trade/3itrade_hedge_result.php?l=zh-tw&se=EW&t=D&d=%s&o=json" % roc)
    it = next((x for x in (oi.get("tables") or []) if (x.get("fields") or [None])[0] == "代號"), None)
    for r in (it or {}).get("data") or []:  # [10] 外資及陸資合計買賣超、[13] 投信買賣超（股）
        code = r[0].strip()
        if code in rows and len(r) > 13:
            rows[code][5] = round((num(r[10]) or 0) / 1000)
            rows[code][6] = round((num(r[13]) or 0) / 1000)
    time.sleep(3)
    return rows, names


def build_site(hist, names):
    """輸出網頁用檔案：索引＋依代號前兩碼分組"""
    dates = sorted(hist)[-KEEP:]
    os.makedirs(OUT, exist_ok=True)
    for f in os.listdir(OUT):
        os.remove(os.path.join(OUT, f))
    codes = sorted({c for d in dates for c in hist[d]})
    buckets = {}
    for code in codes:
        o, h, l, c, v, fi, it = ([] for _ in range(7))
        for d in dates:
            r = hist[d].get(code)
            for arr, k in ((o, 0), (h, 1), (l, 2), (c, 3), (v, 4), (fi, 5), (it, 6)):
                arr.append(r[k] if r else None)
        if not any(x is not None for x in c):
            continue
        n, mkt = names.get(code, (code, ""))
        buckets.setdefault(code[:2], {})[code] = {"n": n, "m": mkt, "o": o, "h": h, "l": l, "c": c, "v": v, "fi": fi, "it": it}
    for b, s in buckets.items():
        with open(os.path.join(OUT, "%s.json" % b), "w", encoding="utf-8") as f:
            json.dump({"dates": dates, "s": s}, f, ensure_ascii=False, separators=(",", ":"))
    idx = [[c, s["n"], s["m"]] for b in sorted(buckets) for c, s in sorted(buckets[b].items())]
    with open(os.path.join(OUT, "index.json"), "w", encoding="utf-8") as f:
        json.dump({"asOf": dates[-1] if dates else None, "stocks": idx}, f, ensure_ascii=False, separators=(",", ":"))
    return len(idx), len(buckets), dates[-1] if dates else None


def main():
    days = int(sys.argv[sys.argv.index("--days") + 1]) if "--days" in sys.argv else None
    try:  # 快取不存在或是空檔（第一次跑）就從頭補
        cache = json.load(open(CACHE, encoding="utf-8"))
    except (OSError, ValueError):
        cache = {"hist": {}, "names": {}, "closed": []}
    hist, names, closed = cache["hist"], {k: tuple(v) for k, v in cache.get("names", {}).items()}, set(cache.get("closed", []))
    otc_v = cache.get("otc_v")
    if otc_v != 3 and hist:  # 舊版上櫃資料每天都是同一天的價格（來源不認日期），清掉後重抓上櫃
        otc = {k for k, v in names.items() if v[1] == "上櫃"}
        for ds in hist:
            for k in otc:
                hist[ds].pop(k, None)
        fails = 0
        for ds in sorted(hist, reverse=True):  # 從最近往回抓
            try:
                got = fetch_otc(dt.date.fromisoformat(ds))
            except Exception as e:
                got = None
                print(ds, "上櫃重抓失敗：", e, flush=True)
            if got:
                fails = 0
                hist[ds].update(got[0])
                names.update(got[1])
                print(ds, "上櫃重抓 %d 檔" % len(got[0]), flush=True)
            else:
                fails += 1
                if fails >= 3:
                    print("上櫃連續 3 天抓不到，先停（上市資料照常更新）", flush=True)
                    break
        else:
            otc_v = 3  # 全部試過才算完成，下次不再重抓
    today = dt.date.today()
    if days is None:  # 往回補到有 KEEP 個交易日
        days = 400 if len(hist) < KEEP else 10
    d = today
    for _ in range(days):
        ds = d.isoformat()
        if d.weekday() < 5 and ds not in hist and ds not in closed and not (d == today and dt.datetime.now().hour < 15):
            try:
                rows, nm = fetch_day(d)
            except Exception as e:
                print(ds, "抓取失敗：", e, flush=True)
                rows = None
                nm = {}
            if rows:
                hist[ds] = rows
                names.update(nm)
                print(ds, "全市場 %d 檔" % len(rows), flush=True)
            elif nm is None:
                closed.add(ds)
        if len(hist) >= KEEP and d.isoformat() < sorted(hist)[-KEEP]:
            break
        d -= dt.timedelta(days=1)
    for k in sorted(hist)[:-KEEP]:
        del hist[k]
    json.dump({"otc_v": otc_v, "hist": hist, "names": names, "closed": sorted(x for x in closed if x >= (today - dt.timedelta(days=400)).isoformat())},
              open(CACHE, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    if not hist:  # 一天都沒抓到就不要輸出空檔（避免把網頁上的舊資料蓋掉）
        sys.exit("全市場資料一天都沒抓到，先不更新")
    n, b, last = build_site(hist, names)
    print("完成：%d 檔、%d 個分組檔、%d 個交易日（最新 %s）" % (n, b, len(hist), last))


if __name__ == "__main__":
    main()
