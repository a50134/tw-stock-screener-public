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


KEEP = ("q", "ocf", "liab", "assets", "inv", "ar", "equity")


def pub(qn):
    """季報公布期限：Q1 5/15、Q2 8/14、Q3 11/14、Q4（年報）隔年 3/31"""
    y, n = int(qn[:4]), int(qn[5])
    return {1: "%d-05-15" % y, 2: "%d-08-14" % y, 3: "%d-11-14" % y, 4: "%d-03-31" % (y + 1)}[n]


def merge(path, src="fin_health.json"):
    """把財報健檢資料填進 data.json 每檔的 fh（只留健檢要用的欄位）；回傳填了幾檔"""
    if not os.path.exists(src):
        return 0
    fh = json.load(open(src, encoding="utf-8"))
    d = json.load(open(path, encoding="utf-8"))
    n = 0
    for s in d["stocks"]:
        rows = fh.get(s["id"])
        if rows:
            s["fh"] = [{k: r.get(k) for k in KEEP} for r in rows]
            n += 1
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return n


def check(s, day=None, debt_max=60):
    """財報健檢（回測：近 4 季營業現金流為正＋負債比 < 60%，6 個策略合起來平均報酬 +5.3% → +6.5%）
    回傳 (通過 True/False/None＝沒資料, 說明文字)"""
    f = s.get("fh") or []
    if day:
        f = [x for x in f if pub(x["q"]) <= day]
    if len(f) < 4:
        return None, "財報健檢：沒有足夠的現金流量／資產負債資料"
    last4 = [x.get("ocf") for x in f[-4:]]
    ocf = sum(last4) if all(v is not None for v in last4) else None
    L = f[-1]
    fin = any(k in (s.get("industry") or "") for k in ("金融", "保險"))
    debt = L["liab"] / L["assets"] * 100 if L.get("liab") is not None and L.get("assets") else None
    bad, good = [], []
    if ocf is not None:
        (good if ocf > 0 else bad).append("近 4 季營業現金流 %+.1f 億%s" % (ocf / 1e8, "" if ocf > 0 else "（帳上賺錢但沒收到現金）"))
    if debt is not None:
        if fin:
            good.append("負債比 %.0f%%（金融業本來就高，不扣分）" % debt)
        else:
            (good if debt < debt_max else bad).append("負債比 %.0f%%%s" % (debt, "" if debt < debt_max else "（超過 %d%%，借錢多）" % debt_max))
    # 存貨、應收帳款比去年同季增加太快（只提醒，不算不通過）
    warn = []
    if len(f) >= 5:
        for k, nm in (("inv", "存貨"), ("ar", "應收帳款")):
            a, b = L.get(k), f[-5].get(k)
            if a is not None and b:
                g = (a / b - 1) * 100
                if g > 30:
                    warn.append("%s比去年同季多 %.0f%%（要確認是不是賣不掉／收不到錢）" % (nm, g))
    ok = None if ocf is None and debt is None else not bad
    head = "✅ 財報健檢通過" if ok else "⚠️ 財報健檢沒通過" if ok is False else "財報健檢"
    return ok, "%s（%s 季報）：%s" % (head, L["q"], "、".join(bad + good + warn) or "—")


def divs(rows):
    """股利公告 → [[公告日, 現金股利（元）, 除息日], ...]（同一天公告多筆就加總）"""
    out = {}
    for d in rows:
        cash = (d.get("CashEarningsDistribution") or 0) + (d.get("CashStatutorySurplus") or 0)
        if cash <= 0:
            continue
        a = (d.get("AnnouncementDate") or d.get("date") or "")[:10]
        if not a:
            continue
        x = out.setdefault(a, [a, 0.0, d.get("CashExDividendTradingDate") or ""])
        x[1] = round(x[1] + cash, 4)
    return sorted(out.values())


def merge_div(path, src="fin_div.json"):
    """股利公告填進 data.json 每檔的 dv"""
    if not os.path.exists(src):
        return 0
    dv = json.load(open(src, encoding="utf-8"))
    d = json.load(open(path, encoding="utf-8"))
    n = 0
    for s in d["stocks"]:
        if dv.get(s["id"]):
            s["dv"] = dv[s["id"]]
            n += 1
    json.dump(d, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    return n


def main_div(ids, start):
    res = {}
    for k, sid in enumerate(ids, 1):
        print("股利 %d/%d" % (k, len(ids)), flush=True)
        res[sid] = divs(F.get("TaiwanStockDividend", sid, start))
        time.sleep(0.3)
    json.dump(res, open("fin_div.json", "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("股利公告：%d 檔有資料" % sum(1 for v in res.values() if v))


def main():
    src = sys.argv[1] if len(sys.argv) > 1 else "data.json"
    start = sys.argv[sys.argv.index("--start") + 1] if "--start" in sys.argv else "2023-01-01"
    F.TOKEN = (os.environ.get("FINMIND_TOKEN") or "").strip()
    d = json.load(open(src, encoding="utf-8"))
    ids = [s["id"] for s in d["stocks"] if not s["id"].startswith("00")]
    if "--div" in sys.argv:
        main_div(ids, "2021-01-01")
    if "--div-only" in sys.argv:
        return
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
