"""
fin_health.py - 財報健檢資料：每檔抓近 3 年的現金流量表、資產負債表（FinMind），整理成每季數字
（給每晚掃描的「財報健檢」條件與回測用）

存成 fin_health.json（fin-data 分支）：{代號: [{q, ocf, icf, capex, ni, assets, liab, cur_a, cur_l, inv, ar, equity}, ...]}
  ・現金流量表在台灣是「今年累計」：這裡已經換成單季（Q2＝上半年－Q1）
  ・ocf 營業現金流、icf 投資現金流、capex 買廠房設備（負數）、liab 負債、cur_a/cur_l 流動資產／負債、inv 存貨、ar 應收帳款
用法：python fin_health.py data.json [--start 2023-01-01]
"""
import json
import os
import sys
import time
from collections import Counter

import fetch_finmind as F

CF = {"ocf": ["CashFlowsFromOperatingActivities", "NetCashInflowFromOperatingActivities", "CashProvidedByOperatingActivities"],
      "icf": ["CashProvidedByInvestingActivities", "CashFlowsFromInvestingActivities", "NetCashInflowFromInvestingActivities"],
      "capex": ["PropertyAndPlantAndEquipment", "AcquisitionOfPropertyPlantAndEquipment"]}
BS = {"assets": ["TotalAssets"], "liab": ["Liabilities", "TotalLiabilities"], "cur_a": ["CurrentAssets"], "cur_l": ["CurrentLiabilities"],
      "inv": ["Inventories"], "ar": ["AccountsReceivableNet", "NotesAndAccountsReceivableNet", "AccountsReceivable"],
      "equity": ["EquityAttributableToOwnersOfParent", "Equity", "TotalEquity"]}


def by_date(rows):
    out = {}
    for d in rows:
        if d["date"][5:7] in ("03", "06", "09", "12"):
            out.setdefault(d["date"], {})[d["type"]] = d["value"]
    return out


def qname(date):
    return "%sQ%d" % (date[:4], int(date[5:7]) // 3)


def build(cf, bs):
    c, b = by_date(cf), by_date(bs)
    out = []
    for date in sorted(set(c) | set(b)):
        x, y = c.get(date, {}), b.get(date, {})
        r = {"q": qname(date)}
        for k, names in CF.items():
            v = F.pick(x, *names)
            if v is not None and date[5:7] != "03":  # 累計 → 單季
                pd = [dd for dd in c if dd[:4] == date[:4] and dd < date]
                pv = F.pick(c[max(pd)], *names) if pd else None
                v = v - pv if pv is not None else None
            r[k] = v
        for k, names in BS.items():
            r[k] = F.pick(y, *names)
        out.append(r)
    return out


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "data.json"
    start = sys.argv[sys.argv.index("--start") + 1] if "--start" in sys.argv else "2023-01-01"
    F.TOKEN = (os.environ.get("FINMIND_TOKEN") or "").strip()
    d = json.load(open(src, encoding="utf-8"))
    ids = [s["id"] for s in d["stocks"] if not s["id"].startswith("00")]
    res, tc, tb = {}, Counter(), Counter()
    for k, sid in enumerate(ids, 1):
        print("抓取 %d/%d" % (k, len(ids)), flush=True)  # 不印代號
        cf = F.get("TaiwanStockCashFlowsStatement", sid, start)
        bs = F.get("TaiwanStockBalanceSheet", sid, start)
        tc.update(set(x["type"] for x in cf))
        tb.update(set(x["type"] for x in bs))
        res[sid] = build(cf, bs)
        time.sleep(0.3)
    json.dump(res, open("fin_health.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    # 欄位名稱（之後對照用；不含代號）
    json.dump({"cf_types": tc.most_common(), "bs_types": tb.most_common()}, open("fin_types.json", "w", encoding="utf-8"), ensure_ascii=False, indent=0)
    ok = sum(1 for v in res.values() if any(q.get("ocf") is not None for q in v))
    print("完成：%d 檔，有營業現金流 %d 檔、有負債 %d 檔" % (len(res), ok, sum(1 for v in res.values() if any(q.get("liab") is not None for q in v))))


if __name__ == "__main__":
    main()
