"""
market_scan.py - 全市場粗篩：一次看過全部上市、上櫃股票和 ETF（約 1,800 檔以上）

為什麼要分兩段：FinMind 一檔要抓 6 次，全部台股逐檔抓要 1 萬多次，每天跑不完。
證交所、櫃買中心有「全市場一次給」的免費資料（收盤價、成交量、本益比、殖利率、淨值比），
先用這些把明顯不合的篩掉，只把剩下的交給 fetch_finmind.py 抓完整歷史、再套選股策略。

用法：
  python market_scan.py            # 印出粗篩結果，存成 market_scan.json
  （daily_run.py 會自動呼叫，把結果加進當天要抓的清單）

設定在 sop_config.json 的 "scan"（沒寫就用下面的 DEFAULT）：
  on        false 就不做全市場粗篩，只抓 universe 清單
  stock     個股條件：股價 ≤ maxPrice、成交量 ≥ minVol 張，
            且（0 < 本益比 ≤ maxPE 或 殖利率 ≥ minYield%）；依成交量由大到小取 max 檔
  etf       ETF 條件：成交量 ≥ minVol 張、股價 ≤ maxPrice；skipLev=true 排除槓桿(L)／反向(R)；
            skipBond=true 排除債券 ETF(B)；依成交量取 max 檔
抓不到資料（網站維護、改版）時回傳空名單，每日報告照常用 universe 清單跑。
"""
import datetime as dt
import json
import os
import sys

import requests

try:
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass

DIR = os.path.dirname(os.path.abspath(__file__))
DEFAULT = {
    "on": True,
    "stock": {"maxPrice": 100, "minVol": 500, "maxPE": 15, "minYield": 4, "max": 80},
    "etf": {"on": True, "maxPrice": 100, "minVol": 1000, "max": 30, "skipLev": True, "skipBond": False},
}
UA = {"User-Agent": "Mozilla/5.0 (tw-stock-screener market scan)"}
SRC = {
    "twse_px": "https://openapi.twse.com.tw/v1/exchangeReport/STOCK_DAY_ALL",
    "twse_pe": "https://openapi.twse.com.tw/v1/exchangeReport/BWIBBU_ALL",
    "tpex_px": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_daily_close_quotes",
    "tpex_pe": "https://www.tpex.org.tw/openapi/v1/tpex_mainboard_peratio_analysis",
}
# 兩個網站欄位名稱不同，依序找第一個有的
K_CODE = ["Code", "SecuritiesCompanyCode", "證券代號", "股票代號"]
K_NAME = ["Name", "CompanyName", "證券名稱", "公司名稱"]
K_CLOSE = ["ClosingPrice", "Close", "收盤價"]
K_VOL = ["TradeVolume", "TradingShares", "成交股數"]
K_PE = ["PEratio", "PriceEarningRatio", "本益比"]
K_DY = ["DividendYield", "YieldRatio", "殖利率(%)", "殖利率"]
K_PB = ["PBratio", "PriceBookRatio", "股價淨值比"]


def pick(row, keys):
    for k in keys:
        if k in row:
            return row[k]
    return None


def num(x):
    try:
        v = float(str(x).replace(",", "").strip())
        return v if v == v else None
    except (TypeError, ValueError):
        return None


def get_json(url):
    for attempt in range(3):
        try:
            r = requests.get(url, headers=UA, timeout=60)
            r.raise_for_status()
            j = r.json()
            if isinstance(j, list):
                return j
        except (requests.RequestException, ValueError) as e:
            print("  ! %s：%s" % (url, e), file=sys.stderr)
    return []


def is_etf(code):
    return code.startswith("00")


def market():
    """回傳 {代號: {name, close, vol(張), pe, dy, pb, mkt}}"""
    out = {}
    for mkt in ("twse", "tpex"):
        px, pe = get_json(SRC[mkt + "_px"]), get_json(SRC[mkt + "_pe"])
        print("%s：行情 %d 筆、本益比 %d 筆" % ("上市" if mkt == "twse" else "上櫃", len(px), len(pe)))
        for row in px:
            code = str(pick(row, K_CODE) or "").strip()
            close, vol = num(pick(row, K_CLOSE)), num(pick(row, K_VOL))
            if not code or not close or vol is None:
                continue
            out[code] = {"name": str(pick(row, K_NAME) or "").strip(), "close": close,
                         "vol": round(vol / 1000), "pe": None, "dy": None, "pb": None, "mkt": mkt}
        for row in pe:
            code = str(pick(row, K_CODE) or "").strip()
            if code in out:
                out[code].update(pe=num(pick(row, K_PE)), dy=num(pick(row, K_DY)), pb=num(pick(row, K_PB)))
    return out


def screen(m, cfg, skip=()):
    """粗篩：回傳 (個股清單, ETF 清單)，各依成交量由大到小、排除 skip 裡已經有的"""
    s, e = cfg["stock"], cfg["etf"]
    stocks, etfs = [], []
    for code, x in m.items():
        if code in skip:
            continue
        if is_etf(code):
            if not e.get("on", True) or x["vol"] < e["minVol"] or x["close"] > e["maxPrice"]:
                continue
            if e.get("skipLev") and code[-1:] in ("L", "R"):
                continue
            if e.get("skipBond") and code[-1:] == "B":
                continue
            etfs.append(code)
        elif len(code) == 4 and code.isdigit():  # 一般股票（排除權證、特別股等）
            if x["close"] > s["maxPrice"] or x["vol"] < s["minVol"]:
                continue
            cheap = x["pe"] is not None and 0 < x["pe"] <= s["maxPE"]
            rich = x["dy"] is not None and x["dy"] >= s["minYield"]
            if cheap or rich:
                stocks.append(code)
    by_vol = lambda c: -m[c]["vol"]
    return sorted(stocks, key=by_vol)[:s["max"]], sorted(etfs, key=by_vol)[:e["max"]]


def config():
    p = os.path.join(DIR, "sop_config.json")
    user = (json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}).get("scan") or {}
    cfg = {"on": user.get("on", DEFAULT["on"])}
    for k in ("stock", "etf"):
        cfg[k] = dict(DEFAULT[k], **(user.get(k) or {}))
    return cfg


def run(skip=()):
    """daily_run.py 用：回傳要另外加抓的代號（個股＋ETF）。失敗回傳 []，不中斷每日報告。"""
    cfg = config()
    if not cfg["on"]:
        print("全市場粗篩：已關閉（sop_config.json 的 scan.on = false）")
        return []
    try:
        m = market()
    except Exception as e:  # 網站改版等意外狀況：照樣跑原本清單
        print("全市場粗篩失敗：", e, file=sys.stderr)
        return []
    if not m:
        print("全市場粗篩：抓不到證交所／櫃買中心資料，今天只用原本清單", file=sys.stderr)
        return []
    stocks, etfs = screen(m, cfg, set(skip))
    n_stock = sum(1 for c in m if not is_etf(c) and len(c) == 4 and c.isdigit())
    n_etf = sum(1 for c in m if is_etf(c))
    print("全市場粗篩：看過 %d 檔個股、%d 檔 ETF → 另外加抓 %d 檔個股、%d 檔 ETF"
          % (n_stock, n_etf, len(stocks), len(etfs)))
    with open(os.path.join(DIR, "market_scan.json"), "w", encoding="utf-8") as f:
        json.dump({"date": dt.date.today().isoformat(), "seen": {"stock": n_stock, "etf": n_etf},
                   "stocks": [dict(id=c, **m[c]) for c in stocks],
                   "etfs": [dict(id=c, **m[c]) for c in etfs]}, f, ensure_ascii=False, indent=1)
    return stocks + etfs


if __name__ == "__main__":
    p = os.path.join(DIR, "sop_config.json")
    base = (json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {}).get("universe") or []
    ids = run(skip=[str(x) for x in base])
    print(" ".join(ids))
