"""
cycle_study.py - 循環股近 5 年「為何大漲、為何大跌、有沒有固定時間」研究

每檔循環股（cycle_bands.json 裡的）抓 2021 年起的日K與月營收（FinMind），算出：
  1. 每年最低點、最高點落在幾月 → 看有沒有固定發生的月份（季節性）
  2. 大波段（月收盤漲跌 35% 以上的轉折）：從哪個月到哪個月、漲跌幾 %
  3. 每個大漲波段開始前後，月營收年增率有沒有先轉正（營收是不是領先指標）
  4. 每個月份的平均漲跌（季節性）
結果：cycle_study.json（給每晚掃描用：訊號出現時附上「過去 5 年的規律」）、cycle_study.md（人看的摘要）
產業別的漲跌原因寫在 cycle_reasons.json（人工整理，依產業）

用法：python cycle_study.py          # cycle_bands.json 全部
      python cycle_study.py 1605     # 只做指定股票
"""
import datetime as dt
import json
import os
import sys
import time

DIR = os.path.dirname(os.path.abspath(__file__))
START = "2020-07-01"  # 往前多抓半年，避免 2021 年 1 月因為是資料第一個月被誤算成低點
SWING = 35  # 大波段門檻（%）

# 產業分組：stock_profiles.json 的 biz／cyc 出現這些字就歸到這一組（cycle_reasons.json 用同樣的組名）
GROUPS = [("貨櫃航運", ["貨櫃"]), ("散裝航運", ["散裝", "BDI"]), ("航空", ["航空"]), ("銅與電線電纜", ["電纜", "銅"]),
          ("鋼鐵", ["鋼"]), ("石化塑化", ["石化", "塑", "煉油", "合成橡膠", "氯鹼", "烷基苯"]), ("記憶體", ["記憶體", "DRAM"]),
          ("面板", ["面板"]), ("被動元件", ["被動元件"]), ("矽晶圓與半導體", ["矽晶圓", "半導體", "封測", "IC 測試", "封裝"]),
          ("PCB 與電子零組件", ["PCB", "電路板", "連接器", "電子", "LED", "光電", "電聲"]), ("證券金融", ["證券", "金融", "成交量"]),
          ("營建水泥", ["營建", "營造", "建設", "建案", "水泥", "混凝土", "工程", "房市"]), ("紙業", ["紙"]),
          ("輪胎橡膠", ["輪胎", "橡膠"]), ("化纖紡織", ["化纖", "纖維", "紡織"]), ("製鞋代工", ["運動鞋", "鞋"])]


def group_of(prof):
    text = str((prof or {}).get("biz", "")) + str((prof or {}).get("cyc", ""))
    for g, kws in GROUPS:
        if any(k in text for k in kws):
            return g
    return "其他"


def monthly(rows):
    """日K → {YYYY-MM: [開, 高, 低, 收]}"""
    m = {}
    for d in rows:
        k = d["date"][:7]
        o, h, l, c = d.get("open"), d.get("max"), d.get("min"), d.get("close")
        if not c:
            continue
        a = m.get(k)
        if not a:
            m[k] = [o, h, l, c]
        else:
            a[1], a[2], a[3] = max(a[1], h), min(a[2], l), c
    return dict(sorted(m.items()))


def swings(months, closes, th=SWING):
    """月收盤的大波段（zigzag）：從高點回落 th% 算一段跌、從低點反彈 th% 算一段漲；回傳 [(起點月, 終點月, 漲跌%)]"""
    t, n = th / 100, len(closes)
    trend, hi, lo, piv = 0, 0, 0, []
    for i in range(1, n):
        c = closes[i]
        if c > closes[hi]:
            hi = i
        if c < closes[lo]:
            lo = i
        if trend != -1 and hi < i and c <= closes[hi] * (1 - t):
            piv.append(hi)
            trend, lo = -1, i
        elif trend != 1 and lo < i and c >= closes[lo] * (1 + t):
            piv.append(lo)
            trend, hi = 1, i
    piv.append(hi if trend == 1 else lo if trend == -1 else n - 1)
    res = []
    for a, b in zip(piv, piv[1:]):
        p = (closes[b] / closes[a] - 1) * 100
        if a != b and abs(p) >= th:
            res.append((months[a], months[b], round(p, 1)))
    return res


def rev_yoy(rev):
    """月營收 {YYYY-MM: 年增%}"""
    v = {}
    for d in rev:
        v["%04d-%02d" % (d["revenue_year"], d["revenue_month"])] = d["revenue"]
    out = {}
    for k, x in v.items():
        p = "%d-%s" % (int(k[:4]) - 1, k[5:])
        if v.get(p, 0) > 0 and x > 0:
            out[k] = round((x / v[p] - 1) * 100, 1)
    return dict(sorted(out.items()))


def shift(m, n):
    y, mm = int(m[:4]), int(m[5:]) + n
    while mm < 1:
        y, mm = y - 1, mm + 12
    while mm > 12:
        y, mm = y + 1, mm - 12
    return "%04d-%02d" % (y, mm)


def study(sid, name, prof, px, rev):
    M = monthly(px)
    if len(M) < 36:
        return None
    months, closes = list(M), [M[k][3] for k in M]
    this = dt.date.today().year
    yl, yh = {}, {}
    for y in range(2021, this + 1):  # 只算 2021 年起的年份（2020 下半只拿來當前一段資料）
        ks = [k for k in months if k.startswith(str(y))]
        if not ks:
            continue
        yl[y] = min(ks, key=lambda k: M[k][2])
        yh[y] = max(ks, key=lambda k: M[k][1])
    full = [y for y in yl if y < this]
    cnt_lo, cnt_hi = {}, {}
    for y in full:
        cnt_lo[int(yl[y][5:])] = cnt_lo.get(int(yl[y][5:]), 0) + 1
        cnt_hi[int(yh[y][5:])] = cnt_hi.get(int(yh[y][5:]), 0) + 1

    def season(cnt):  # 同一個月（或前後一個月）出現在一半以上的年份，才算有固定時間
        best = None
        for m in range(1, 13):
            n = sum(cnt.get((m + d - 1) % 12 + 1, 0) for d in (-1, 0, 1))
            if not best or n > best[1]:
                best = (m, n)
        return {"month": best[0], "years": best[1], "of": len(full), "fixed": best[1] >= max(3, (len(full) + 1) // 2 + 1)} if best else None

    ret = {}
    for i in range(1, len(months)):
        ret.setdefault(int(months[i][5:]), []).append(closes[i] / closes[i - 1] - 1)
    mavg = {m: round(sum(v) / len(v) * 100, 1) for m, v in sorted(ret.items())}
    yoy = rev_yoy(rev)
    sw = []
    for a, b, p in swings(months, closes):
        r0 = [yoy.get(shift(a, k)) for k in (-3, -2, -1, 0, 1, 2)]
        lead = None
        if p > 0:  # 大漲：起漲前後營收年增有沒有先轉強
            rr = [x for x in r0 if x is not None]
            lead = bool(rr) and (rr[-1] - rr[0] > 10 or any(x > 0 for x in rr[-3:]) and any(x <= 0 for x in rr[:3]))
        sw.append({"from": a, "to": b, "pct": p, "px": [round(M[a][3], 2), round(M[b][3], 2)], "rev_yoy_around_start": r0, "rev_leads": lead})
    return {"id": sid, "name": name, "group": group_of(prof), "year_low_month": {str(y): yl[y] for y in yl},
            "year_high_month": {str(y): yh[y] for y in yh}, "low_season": season(cnt_lo), "high_season": season(cnt_hi),
            "month_avg_ret": mavg, "swings": sw, "last": months[-1]}


def summary(res):
    """cycle_study.md：依產業整理"""
    by = {}
    for r in res.values():
        by.setdefault(r["group"], []).append(r)
    L = ["# 循環股近 5 年漲跌研究（%s）" % dt.date.today().isoformat(), ""]
    for g in sorted(by, key=lambda g: -len(by[g])):
        rs = by[g]
        L.append("## %s（%d 檔）" % (g, len(rs)))
        lo = {}
        for r in rs:
            s = r.get("low_season")
            if s and s["fixed"]:
                lo[s["month"]] = lo.get(s["month"], 0) + 1
        L.append("- 有固定低點月份的：%s" % ("、".join("%d 月附近 %d 檔" % (m, n) for m, n in sorted(lo.items(), key=lambda x: -x[1])) or "沒有"))
        ups = [s for r in rs for s in r["swings"] if s["pct"] > 0]
        if ups:
            lead = [s for s in ups if s["rev_leads"]]
            L.append("- 大漲波段 %d 次，起漲前後營收年增先轉強的有 %d 次（%.0f%%）" % (len(ups), len(lead), len(lead) / len(ups) * 100))
        for r in rs:
            sw = "；".join("%s→%s %+.0f%%" % (s["from"], s["to"], s["pct"]) for s in r["swings"])
            ls = r.get("low_season")
            L.append("  - %s %s：%s｜低點常在 %s" % (r["id"], r["name"], sw or "沒有 35%% 以上的波段",
                                                  "%d 月（%d/%d 年）" % (ls["month"], ls["years"], ls["of"]) if ls else "—"))
        L.append("")
    return "\n".join(L)


def main():
    import fetch_finmind
    fetch_finmind.load_env()
    fetch_finmind.TOKEN = (os.environ.get("FINMIND_TOKEN") or "").strip()
    bands = json.load(open(os.path.join(DIR, "cycle_bands.json"), encoding="utf-8")).get("bands", {})
    prof = json.load(open(os.path.join(DIR, "stock_profiles.json"), encoding="utf-8"))
    ids = [a for a in sys.argv[1:] if a.isdigit()] or list(bands)
    info = {d["stock_id"]: d.get("stock_name", "") for d in fetch_finmind.get("TaiwanStockInfo")}
    out_p = os.path.join(DIR, "cycle_study.json")
    res = json.load(open(out_p, encoding="utf-8")).get("stocks", {}) if os.path.exists(out_p) and len(sys.argv) > 1 else {}
    for k, sid in enumerate(ids, 1):
        px = fetch_finmind.get("TaiwanStockPrice", sid, START)
        rev = fetch_finmind.get("TaiwanStockMonthRevenue", sid, "2019-12-01")
        r = study(sid, info.get(sid, sid), prof.get(sid), px, rev)
        if r:
            res[sid] = r
        print("研究 %d/%d：%s" % (k, len(ids), "完成" if r else "資料不足"), flush=True)
        time.sleep(0.3)
    json.dump({"date": dt.date.today().isoformat(), "swing_pct": SWING, "stocks": res}, open(out_p, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    open(os.path.join(DIR, "cycle_study.md"), "w", encoding="utf-8").write(summary(res))
    print("完成：%d 檔" % len(res))


if __name__ == "__main__":
    main()
