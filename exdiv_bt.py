"""
exdiv_bt.py - 回測「除權息前一兩天買、除權息當天賣」短打策略（上市股票）

資料：證交所 TWT49U（除權除息計算結果表：除權息前收盤、參考價、權/息）＋ MI_INDEX（每日全部收盤價、成交量）
報酬計算（含股利）：除權息當天收盤 × (除權息前收盤 ÷ 參考價) ÷ 買進價 − 1，再扣來回交易成本 0.6%
（參考價已扣掉股利；乘回去＝等於把拿到的現金股利或配股價值算進來）

用法：python exdiv_bt.py fetch 2024（抓一年，存 exdiv_2024.json）；python exdiv_bt.py report 2019 2026（合併統計，輸出 exdiv_result.md）
"""
import datetime as dt
import json
import os
import re
import statistics as st
import sys
import time
import urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
UA = {"User-Agent": "Mozilla/5.0"}
COST = 0.6  # 來回手續費 0.1425%×2＋證交稅 0.3%（約）


def get(url):
    for k in range(4):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=40) as r:
                return json.loads(r.read().decode("utf-8-sig"))
        except Exception:
            if k == 3:
                raise
            time.sleep(10)


def num(x):
    try:
        x = str(x).replace(",", "").strip()
        return float(x) if x not in ("", "--", "---") else None
    except ValueError:
        return None


def roc_date(s):
    m = re.match(r"(\d+)年(\d+)月(\d+)日", s.strip())
    return dt.date(int(m.group(1)) + 1911, int(m.group(2)), int(m.group(3))) if m else None


def events(y):
    """一年的除權息事件（上市普通股）"""
    j = get("https://www.twse.com.tw/rwd/zh/exRight/TWT49U?startDate=%d0101&endDate=%d1231&response=json" % (y, y))
    f = j.get("fields") or []
    out = []
    for r in j.get("data") or []:
        row = dict(zip(f, r))
        code = str(row.get("股票代號", "")).strip()
        if not (len(code) == 4 and code.isdigit() and not code.startswith("0")):
            continue
        d = roc_date(str(row.get("資料日期", "")))
        pre, ref = num(row.get("除權息前收盤價")), num(row.get("除權息參考價"))
        if d and pre and ref and ref > 0:
            out.append({"d": d.isoformat(), "id": code, "name": str(row.get("股票名稱", "")).strip(), "pre": pre, "ref": ref,
                        "type": str(row.get("權/息", "")).strip()})
    time.sleep(3)
    return out


CACHE = {}


def day(d):
    """某天全部上市股票 {代號: (收盤, 張數)}；休市回傳 None"""
    k = d.isoformat()
    if k in CACHE:
        return CACHE[k]
    if d.weekday() >= 5:
        CACHE[k] = None
        return None
    j = get("https://www.twse.com.tw/rwd/zh/afterTrading/MI_INDEX?date=%s&type=ALLBUT0999&response=json" % d.strftime("%Y%m%d"))
    tab = next((t for t in (j.get("tables") or []) if (t.get("fields") or [None])[0] == "證券代號" and "收盤價" in (t.get("fields") or [])), None)
    if j.get("stat") != "OK" or not tab:
        CACHE[k] = None
    else:
        f = tab["fields"]
        ic, iv = f.index("收盤價"), f.index("成交股數")
        CACHE[k] = {r[0].strip(): (num(r[ic]), (num(r[iv]) or 0) / 1000) for r in tab["data"]}
    time.sleep(2.5)
    return CACHE[k]


def before(d, n):
    """d 之前第 n 個交易日"""
    x, c = d, 0
    while c < n:
        x -= dt.timedelta(days=1)
        if day(x) is not None:
            c += 1
    return x


def stats(R):
    if not R:
        return "0 筆"
    return "%d 筆｜勝率 %.0f%%｜平均 %+.2f%%｜中位數 %+.2f%%｜最差 %+.1f%%" % (
        len(R), sum(r > 0 for r in R) / len(R) * 100, st.mean(R), sorted(R)[len(R) // 2], min(R))


def fetch(y):
    """抓一年的事件與價格，存 exdiv_YEAR.json（每年可平行跑）"""
    ev = events(y)
    print(y, "除權息事件", len(ev), flush=True)
    res = []
    for i, e in enumerate(ev):
        D = dt.date.fromisoformat(e["d"])
        try:
            dD = day(D)
            if not dD or e["id"] not in dD:
                continue
            b1, b2 = before(D, 1), before(D, 2)
            c1, c2 = day(b1).get(e["id"]), day(b2).get(e["id"])
            cD = dD[e["id"]][0]
            if not (cD and c1 and c2 and c1[0] and c2[0]):
                continue
            k = e["pre"] / e["ref"]  # 把股利加回去的倍數
            e.update(cD=cD, c1=c1[0], c2=c2[0], vol=c2[1],
                     exday=(cD / e["ref"] - 1) * 100,                 # 除權息當天：收盤 vs 參考價（文章說的「當天上漲」）
                     r2=(cD * k / c2[0] - 1) * 100 - COST,            # 前兩天收盤買、除權息當天收盤賣（含股利、扣成本）
                     r1=(cD * k / c1[0] - 1) * 100 - COST,            # 前一天收盤買
                     yld=(k - 1) * 100)
            res.append(e)
        except Exception as x:
            print(e["d"], e["id"], "略過：", x, flush=True)
        if i % 100 == 0:
            print("%d 進度 %d/%d（已抓 %d 天）" % (y, i, len(ev), len(CACHE)), flush=True)
    json.dump(res, open(os.path.join(DIR, "exdiv_%d.json" % y), "w", encoding="utf-8"), ensure_ascii=False)


def main():
    if sys.argv[1] == "fetch":
        return fetch(int(sys.argv[2]))
    y0, y1 = int(sys.argv[2]), int(sys.argv[3])  # report：合併各年檔案做統計
    import glob
    res = [e for f in sorted(glob.glob(os.path.join(DIR, "**", "exdiv_*.json"), recursive=True)) if re.search(r"exdiv_\d{4}\.json$", f)
           for e in json.load(open(f, encoding="utf-8"))]
    liq = [e for e in res if e["vol"] >= 300]  # 前兩天成交量 300 張以上（買得到、賣得掉）
    L = ["# 除權息短打回測（上市普通股 %d～%d）" % (y0, y1), "",
         "報酬已含股利、扣來回成本 %.1f%%；只算成交量 300 張以上（共 %d 筆，全部 %d 筆）" % (COST, len(liq), len(res)), "",
         "## 1. 除權息當天收盤高於參考價（文章說的「當天上漲」）", "- 全部：%.0f%% 上漲" % (sum(e["exday"] > 0 for e in liq) / max(len(liq), 1) * 100), "",
         "## 2. 策略：前兩天買、除權息當天賣（抱 3 天）", "- 全部：" + stats([e["r2"] for e in liq]),
         "- 前一天買：" + stats([e["r1"] for e in liq])]
    for t in ("息", "權", "權息"):
        L.append("- 只看「%s」：%s" % (t, stats([e["r2"] for e in liq if e["type"] == t])))
    L += ["", "## 3. 依年份（前兩天買）"]
    for y in range(y0, y1 + 1):
        L.append("- %d：%s" % (y, stats([e["r2"] for e in liq if e["d"][:4] == str(y)])))
    L += ["", "## 4. 依殖利率（這次配的現金＋股票價值占股價）"]
    for a, b in ((0, 2), (2, 4), (4, 6), (6, 100)):
        L.append("- %d%%～%s：%s" % (a, "%d%%" % b if b < 100 else "以上", stats([e["r2"] for e in liq if a <= e["yld"] < b])))
    # 文章的選股法：挑「過去除權息當天常常上漲」的股票（只用過去資料挑，再看下一次結果＝不偷看答案）
    hist, pick = {}, []
    for e in sorted(liq, key=lambda e: e["d"]):
        h = hist.get(e["id"], [])
        if len(h) >= 4 and sum(x > 0 for x in h) / len(h) >= 0.75:
            pick.append(e["r2"])
        hist.setdefault(e["id"], []).append(e["exday"])
    L += ["", "## 5. 文章選股法：過去至少 4 次、除權息當天上漲 ≥ 75% 的股票（只用過去資料挑）", "- " + stats(pick)]
    txt = "\n".join(L)
    print(txt)
    open(os.path.join(DIR, "exdiv_result.md"), "w", encoding="utf-8").write(txt)


if __name__ == "__main__":
    main()
