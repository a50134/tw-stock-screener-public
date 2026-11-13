"""
2026-11-13 使用者同意回測的三個想法（錢線百分百 11/13 節目），在 GitHub 雲端跑（要連 Yahoo、FinMind）
股票：網頁資料（site-data）市值前 150 檔（現在的大公司，有倖存者偏差；看「條件組 vs 全部」的差別比較準）
報酬：都用「比加權指數多賺」，訊號隔天開盤買；同一檔 20 天內只算一次

1. 跟投信、買在投信成本附近
   投信成本＝近 60 個交易日投信「買超那幾天」的收盤價，用買超張數加權平均（估計值）
   投信一直買＝近 20 天投信買超天數 ≥ 12 天，且近 60 天累計買超 > 0
   比較：股價在投信成本 −5%～+3%（節目說的保底價附近）、+3%～+10%、+10% 以上（追高）、投信沒在買
   再加「月營收年增 > 20%」（節目說的獲利大幅成長）看會不會更好
2. 庫藏股＋外資／投信同買：先找 FinMind 有沒有庫藏股歷史資料（分點「主力」資料要付費，用外資＋投信代替）
3. 好公司跌到年線（240 日均線）
   之前多頭：近 120 天有 70% 以上收在年線上、年線比 20 天前高
   訊號：收盤回到年線 ±2% 內（近 60 天第一次）
   比較：跌破年線 5% 以上（第一次）、年線往下時碰到年線、任何一天買
用法：FINMIND_TOKEN=… python research/nov13_bt.py data.json
"""
import json
import os
import statistics as stt
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import fetch_finmind
import us


def pct(x):
    return "—" if x is None else "%+.1f%%" % (x * 100)


def grp(name, L):
    L = [x for x in L if x is not None]
    if not L:
        return "・%s：0 筆" % name
    return "・%-34s %5d 筆｜平均 %s｜中位數 %s｜輸大盤 %.0f%%｜最差 %s" % (
        name, len(L), pct(stt.mean(L)), pct(stt.median(L)), 100 * sum(x < 0 for x in L) / len(L), pct(min(L)))


def load(path):
    d = json.load(open(path, encoding="utf-8"))
    L = sorted(((float(x["shares"]) * x["c"][-1], x) for x in d["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"] and x["c"][-1]), key=lambda z: -z[0])[:150]
    return [x for _, x in L]


def main(path):
    fetch_finmind.TOKEN = (os.environ.get("FINMIND_TOKEN") or "").strip()
    U = load(path)
    tw = {r["date"]: r["adj"] for r in us.yahoo("%5ETWII", years=11)[0]}
    H = (20, 60, 120)

    # ---------- 2：先找庫藏股資料 ----------
    print("=" * 60 + "\n【3. 庫藏股】找 FinMind 有沒有庫藏股歷史資料\n")
    tre = None
    for ds in ("TaiwanStockTreasuryStock", "TaiwanStockTreasuryStockBuyBack", "TaiwanStockBuyBack", "TaiwanStockSharesBuyback"):
        rows = fetch_finmind.get(ds, U[0]["id"], "2015-01-01")
        rows = rows or fetch_finmind.get(ds, "", "2026-01-01")
        print("  %s：%s" % (ds, ("有 %d 筆，欄位 %s" % (len(rows), sorted(rows[0].keys()))) if rows else "沒有"))
        if rows and not tre:
            tre = ds
    if not tre:
        print("  → FinMind 沒有庫藏股資料，方法 3 這次測不了（要另外找公開資訊觀測站的資料）")

    R1 = {k: {h: [] for h in H} for k in ("全部（任何一天）", "投信一直買：股價在成本 −5%～+3%", "投信一直買：成本 +3%～+10%",
                                         "投信一直買：成本 +10% 以上（追高）", "投信一直買：跌破成本 5% 以上",
                                         "成本 −5%～+3%＋月營收年增 >20%", "投信沒在買（近 20 天買超 ≤5 天）")}
    R3 = {k: {h: [] for h in H} for k in ("多頭股回到年線 ±2%", "多頭股回到年線＋大盤在年線上", "多頭股跌破年線 5% 以上",
                                         "年線往下時碰到年線", "全部（任何一天）")}
    ok = 0
    for x in U:
        sid = x["id"]
        try:
            rows = us.yahoo(sid + (".TWO" if x.get("mkt") == "tpex" else ".TW"), years=11)[0]
        except Exception:
            continue
        if len(rows) < 400:
            continue
        D = [r["date"] for r in rows]
        c = [r["close"] for r in rows]  # 原始收盤價（和投信成本比）
        a = [r["adj"] for r in rows]    # 還原權息（算報酬）
        o = [r["open"] * r["adj"] / r["close"] if r["close"] else None for r in rows]
        n = len(D)

        def ex(t, h):
            if t + 1 + h >= n or not o[t + 1] or D[t + 1] not in tw or D[t + 1 + h] not in tw:
                return None
            return (a[t + 1 + h] / o[t + 1] - 1) - (tw[D[t + 1 + h]] / tw[D[t + 1]] - 1)

        # ---------- 年線 ----------
        cs = [0]
        for v in a:
            cs.append(cs[-1] + v)
        ma = lambda k, t: (cs[t + 1] - cs[t + 1 - k]) / k if t >= k - 1 else None
        last = {k: -99 for k in R3}
        prev_near = -99
        for t in range(400, n - 1):
            m, m20 = ma(240, t), ma(240, t - 20)
            for h in H:
                if t % 5 == 0:
                    R3["全部（任何一天）"][h].append(ex(t, h))
            above = sum(a[k] > ma(240, k) for k in range(t - 119, t + 1)) / 120
            near = abs(a[t] / m - 1) <= 0.02
            k = None
            if near and t - prev_near > 60:
                if above >= 0.7 and m > m20:
                    k = "多頭股回到年線 ±2%"
                elif m < m20:
                    k = "年線往下時碰到年線"
            if near:
                prev_near = t
            if k:
                for h in H:
                    R3[k][h].append(ex(t, h))
                if k == "多頭股回到年線 ±2%":
                    z = [tw[dd] for dd in sorted(tw) if dd <= D[t]][-240:]
                    if len(z) == 240 and z[-1] > sum(z) / 240:
                        for h in H:
                            R3["多頭股回到年線＋大盤在年線上"][h].append(ex(t, h))
            if a[t] < m * 0.95 and a[t - 1] >= ma(240, t - 1) * 0.95 and above >= 0.7 and t - last["多頭股跌破年線 5% 以上"] > 60:
                last["多頭股跌破年線 5% 以上"] = t
                for h in H:
                    R3["多頭股跌破年線 5% 以上"][h].append(ex(t, h))

        # ---------- 投信成本 ----------
        inst = fetch_finmind.get("TaiwanStockInstitutionalInvestorsBuySell", sid, "2015-01-01")
        rev = fetch_finmind.get("TaiwanStockMonthRevenue", sid, "2014-01-01")
        if not inst:
            continue
        ok += 1
        it = {}
        for r in inst:
            if r.get("name") == "Investment_Trust":
                it[r["date"]] = it.get(r["date"], 0) + (r.get("buy") or 0) - (r.get("sell") or 0)
        rv = {}
        for r in rev or []:
            ym = "%d-%02d" % (r["revenue_year"], r["revenue_month"]) if r.get("revenue_year") else r["date"][:7]
            rv[ym] = r.get("revenue")
        net = [it.get(dd, 0) for dd in D]
        last_sig = -99
        for t in range(300, n - 1):
            if D[t] < "2015-04-01":
                continue
            w = net[t - 19:t + 1]
            buyd = sum(v > 0 for v in w)
            if t % 5 == 0:
                for h in H:
                    R1["全部（任何一天）"][h].append(ex(t, h))
            if buyd <= 5:
                if t % 5 == 0:
                    for h in H:
                        R1["投信沒在買（近 20 天買超 ≤5 天）"][h].append(ex(t, h))
                continue
            if buyd < 12 or sum(net[t - 59:t + 1]) <= 0 or t - last_sig <= 20:
                continue
            ww = [(net[k], c[k]) for k in range(t - 59, t + 1) if net[k] > 0]
            cost = sum(v * p for v, p in ww) / sum(v for v, _ in ww)
            g = c[t] / cost - 1
            k = ("投信一直買：跌破成本 5% 以上" if g < -0.05 else "投信一直買：股價在成本 −5%～+3%" if g <= 0.03 else
                 "投信一直買：成本 +3%～+10%" if g <= 0.10 else "投信一直買：成本 +10% 以上（追高）")
            last_sig = t
            for h in H:
                R1[k][h].append(ex(t, h))
            if k == "投信一直買：股價在成本 −5%～+3%":
                y, m_ = int(D[t][:4]), int(D[t][5:7])
                m_ -= 2  # 當月 10 日前只公布到上上個月，保守用上上個月
                if m_ <= 0:
                    y, m_ = y - 1, m_ + 12
                cur, old = rv.get("%d-%02d" % (y, m_)), rv.get("%d-%02d" % (y - 1, m_))
                if cur and old and cur / old - 1 > 0.2:
                    for h in H:
                        R1["成本 −5%～+3%＋月營收年增 >20%"][h].append(ex(t, h))
    print("\n有投信資料 %d 檔\n" % ok)
    print("=" * 60 + "\n【1. 跟投信，買在投信成本附近】比加權指數多賺（不設停損）\n")
    for h in H:
        print("抱 %d 天" % h)
        for k, v in R1.items():
            print(grp(k, v[h]))
    print("\n" + "=" * 60 + "\n【年線】多頭股拉回年線\n")
    for h in H:
        print("抱 %d 天" % h)
        for k, v in R3.items():
            print(grp(k, v[h]))


if __name__ == "__main__":
    main(next((a for a in sys.argv[1:] if a.endswith(".json")), "data.json"))
