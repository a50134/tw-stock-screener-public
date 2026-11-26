"""
2026-11-26 理財達人秀 11/20、11/23（語音辨識全文）＋錢線百分百 11/24 可驗證說法的回測（照老師原話的條件）
A 威良「大盤一天跌超過 2,000 點，過去 7 次之後 1～6 個月上漲機率 100%」：加權指數單日跌 ≥2,000 點／≥5%／≥7%，之後 20／60／120 天
B 永年「止跌訊號：外資連 3 日買超（集中市場）、融資不再增加」：加權指數從 60 日高點跌 15% 以上後 20 天內，
   b1 第一次外資連 3 天買超、b2 第一次融資餘額連 3 天沒增加、b3 兩個都有；對照：跌到 15% 當天就買
C 漢偉「融資 3 天減少 10% 以上、法人站在買方」的個股：大盤（0050）離 60 日高點 −10% 以上時，
   融資 3 天減 10% 以上＋外資投信 3 天合計買超 vs 融資大減但法人沒買 vs 全部股票（data.json 約 1.5 年）
D 威良「大跌後反彈第一天，個股先收復大跌前一天高點＋投信買＋融資減」（原話是大盤還沒收復時；但大多數反彈日大盤當天就收復，所以不限制）：
   0050 5 天跌 5% 以上後第一個漲 1.5% 以上的日子，符合 vs 其他股票（data.json）
E 小哥「地板股」：成交量 ≥ 20 日均量 2.5 倍＋收盤比年線（240 日）低 15% 以上 vs 只有比年線低 15%（市值前 150 檔 11 年）
F 錢線「5 日線開始上揚、股價拉回回測 5 日線沒破就是最佳買點」：大跌後（離 60 日高點 −15% 以上、20 天內）
   5 日線連 2 天上揚＋當天最低碰到 5 日線（±0.5%）＋收盤在 5 日線上 vs 「收盤站回 5 日線」（跌深反彈現在用的買點）
隔天開盤買、扣成本 0.6%（A、B 指數不扣）；注意 E、F 只測現在還是大型股的公司（倖存者偏差，結果偏樂觀）
用法：FINMIND_TOKEN=… python research/tv_20261126_bt.py data.json
"""
import json
import os
import statistics as stt
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
from sepa_bt import yahoo  # noqa: E402
import fetch_finmind  # noqa: E402


def ma(c, t, n):
    if t < n - 1:
        return None
    w = c[t - n + 1:t + 1]
    return sum(w) / n if all(w) else None


def line(name, rs, H=(20, 60, 120)):
    out = ["　%s：" % name]
    for k in H:
        r = [x[k] for x in rs if x.get(k) is not None]
        if not r:
            continue
        out.append("%d 天 %d 次 漲 %.0f%%、平均 %+.1f%%" % (k, len(r), 100 * sum(v > 0 for v in r) / len(r), stt.mean(r) * 100))
    print(out[0] + "；".join(out[1:]) if len(out) > 1 else out[0] + "0 次")


def fwd_close(c, t, H):
    return {k: (c[t + k] / c[t] - 1 if t + k < len(c) else None) for k in H}


def fwd_open(o, c, t, H, cost=0.006):
    if t + 1 >= len(c) or not o[t + 1]:
        return {}
    return {k: (c[t + 1 + k] / o[t + 1] - 1 - cost if t + 1 + k < len(c) and c[t + 1 + k] else None) for k in H}


def part_a(TW):
    print("\n【A】大盤一天大跌之後（加權指數，2000 年起）")
    D = sorted(TW)
    o = [TW[d][0] for d in D]
    c = [TW[d][3] for d in D]
    for name, cond in (("單日跌 ≥2,000 點", lambda t: c[t - 1] - c[t] >= 2000), ("單日跌 ≥5%", lambda t: c[t] / c[t - 1] - 1 <= -0.05),
                       ("單日跌 ≥7%", lambda t: c[t] / c[t - 1] - 1 <= -0.07)):
        ev, last = [], -99
        for t in range(1, len(c)):
            if cond(t) and t - last > 5:
                ev.append(t)
                last = t
        print("　%s：%s" % (name, "、".join(D[t] for t in ev)))
        line(name, [fwd_close(c, t, (20, 60, 120)) for t in ev])


def part_b(TW):
    print("\n【B】永年的止跌訊號（加權指數從 60 日高點跌 15% 以上後 20 天內）")
    fetch_finmind.TOKEN = (os.environ.get("FINMIND_TOKEN") or "").strip()
    inst = fetch_finmind.get("TaiwanStockTotalInstitutionalInvestors", "", "2005-01-01", wait=True) or []
    mg = fetch_finmind.get("TaiwanStockTotalMarginPurchaseShortSale", "", "2005-01-01", wait=True) or []
    if inst:
        print("　法人資料欄位：", sorted(inst[0].keys()), sorted({r.get("name") for r in inst})[:8])
    if mg:
        print("　融資資料欄位：", sorted(mg[0].keys()), sorted({r.get("name") for r in mg})[:8])
    fnet = {}
    for r in inst:
        if "Foreign" in str(r.get("name")) and "Dealer" not in str(r.get("name")):
            fnet[r["date"]] = fnet.get(r["date"], 0) + (r.get("buy") or 0) - (r.get("sell") or 0)
    mbal = {r["date"]: r.get("TodayBalance") for r in mg if r.get("name") == "MarginPurchaseMoney" and r.get("TodayBalance")}
    D = sorted(d for d in TW if d >= "2005-01-01")
    c = [TW[d][3] for d in D]
    print("　外資買賣超 %d 天、融資餘額 %d 天" % (len(fnet), len(mbal)))
    R = {"跌 15% 當天就買": [], "b1 外資連 3 天買超": [], "b2 融資連 3 天沒增加": [], "b3 兩個都有": []}
    last = -99
    for t in range(60, len(D) - 1):
        if t - last <= 40 or c[t] / max(c[t - 59:t + 1]) - 1 > -0.15:
            continue
        last = t
        R["跌 15% 當天就買"].append(fwd_close(c, t, (20, 60, 120)))
        got = {}
        for k in range(t, min(t + 20, len(D) - 1)):
            f3 = all(fnet.get(D[j], 0) > 0 for j in (k - 2, k - 1, k)) and all(D[j] in fnet for j in (k - 2, k - 1, k))
            m3 = all(D[j] in mbal for j in (k - 3, k - 2, k - 1, k)) and all(mbal[D[j]] <= mbal[D[j - 1]] for j in (k - 2, k - 1, k))
            if f3 and "b1" not in got:
                got["b1"] = k
            if m3 and "b2" not in got:
                got["b2"] = k
            if f3 and m3 and "b3" not in got:
                got["b3"] = k
        for key, name in (("b1", "b1 外資連 3 天買超"), ("b2", "b2 融資連 3 天沒增加"), ("b3", "b3 兩個都有")):
            if key in got:
                R[name].append(fwd_close(c, got[key], (20, 60, 120)))
    for k, v in R.items():
        line(k, v)


def part_cd(d):
    S = [s for s in d["stocks"] if not s["id"].startswith("00")]
    m = next((s for s in d["stocks"] if s["id"] == "0050"), None)
    if not m:
        print("\n【C】【D】data.json 沒有 0050，略過")
        return
    mc, mh = m["c"], m["h"]
    n = len(d["dates"])
    print("\n【C】融資 3 天減 10%% 以上＋法人 3 天買超（大盤離 60 日高點 −10%% 以上時，data.json %s～%s）" % (d["dates"][0], d["dates"][-1]))
    R = {"融資大減＋法人買": [], "融資大減、法人沒買": [], "同一天全部股票": []}
    for t in range(60, n - 22):
        if not mc[t] or mc[t] / max(x for x in mc[t - 59:t + 1] if x) - 1 > -0.10:
            continue
        for s in S:
            mg, fi, it = s.get("mg"), s.get("fi"), s.get("it")
            if not mg or not fi or not s["c"][t] or not s["o"][t + 1]:
                continue
            r = fwd_open(s["o"], s["c"], t, (20,))
            if not r or r.get(20) is None:
                continue
            R["同一天全部股票"].append(r)
            if mg[t] and mg[t - 3] and mg[t] / mg[t - 3] - 1 <= -0.10:
                inst = sum((fi[k] or 0) + ((it or [0] * n)[k] or 0) for k in (t - 2, t - 1, t))
                R["融資大減＋法人買" if inst > 0 else "融資大減、法人沒買"].append(r)
    for k, v in R.items():
        line(k, v, (20,))
    print("\n【D】大跌後反彈第一天，先收復前一天高點的股票")
    R = {"收復前高＋投信買＋融資 5 天減": [], "只有收復前高": [], "沒收復": []}
    last = -99
    for t in range(6, n - 22):
        if t - last <= 10 or not mc[t] or not all(mc[t - 6:t + 1]) or any(abs(mc[k] / mc[k - 1] - 1) > 0.11 for k in range(t - 5, t)) \
                or mc[t - 1] / mc[t - 6] - 1 > -0.05 or mc[t] / mc[t - 1] - 1 < 0.015:  # 分割日不算；大盤當天也收復的反彈很多，不另外限制
            continue
        last = t
        print("　反彈日：", d["dates"][t])
        for s in S:
            c, h = s["c"], s["h"]
            if not c[t] or not h[t - 1]:
                continue
            r = fwd_open(s["o"], c, t, (20,))
            if not r or r.get(20) is None:
                continue
            if c[t] > h[t - 1]:
                mg, it = s.get("mg") or [], s.get("it") or []
                good = it and (it[t] or 0) > 0 and mg and mg[t] and mg[t - 5] and mg[t] < mg[t - 5]
                R["收復前高＋投信買＋融資 5 天減" if good else "只有收復前高"].append(r)
            else:
                R["沒收復"].append(r)
    for k, v in R.items():
        line(k, v, (20,))


def part_ef(d):
    U = sorted(((float(x["shares"]) * x["c"][-1], x) for x in d["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"] and x["c"][-1]), key=lambda z: -z[0])[:150]
    E = {"地板股（量 2.5 倍＋年線下 15%）": [], "只有年線下 15%": []}
    F = {"5 日線上揚、回測 5 日線沒破": [], "收盤站回 5 日線（現在用的）": []}
    for _, x in U:
        rows = yahoo(x["id"] + (".TWO" if x.get("mkt") == "tpex" else ".TW"))
        if len(rows) < 400:
            continue
        o, h, l, c, v = ([r[i] for r in rows] for i in range(1, 6))
        n = len(c)
        le = lf1 = lf2 = -99
        for t in range(245, n - 2):
            y = ma(c, t, 240)
            av = ma(v, t - 1, 20)
            if y and c[t] / y - 1 <= -0.15 and t - le > 20:
                vol = av and v[t] >= 2.5 * av
                E["地板股（量 2.5 倍＋年線下 15%）" if vol else "只有年線下 15%"].append(fwd_open(o, c, t, (20, 60)))
                le = t
            deep = any(c[k] / max(h[k - 59:k + 1]) - 1 <= -0.15 for k in range(t - 19, t + 1))
            if not deep:
                continue
            m5, m5a, m5b = ma(c, t, 5), ma(c, t - 1, 5), ma(c, t - 2, 5)
            if t - lf1 > 20 and m5 and m5a and m5b and m5 > m5a > m5b and l[t] <= m5 * 1.005 and c[t] >= m5:
                F["5 日線上揚、回測 5 日線沒破"].append(fwd_open(o, c, t, (20, 60)))
                lf1 = t
            if t - lf2 > 20 and m5 and m5a and c[t] > m5 and c[t - 1] < m5a:
                F["收盤站回 5 日線（現在用的）"].append(fwd_open(o, c, t, (20, 60)))
                lf2 = t
    print("\n【E】小哥的地板股（市值前 150 檔、Yahoo 約 11 年）")
    for k, v in E.items():
        line(k, v, (20, 60))
    print("\n【F】錢線：大跌後 5 日線上揚、拉回測 5 日線沒破（市值前 150 檔、11 年）")
    for k, v in F.items():
        line(k, v, (20, 60))


def main(path):
    rows = yahoo("%5ETWII", 27)
    TW = {r[0]: (r[1], r[2], r[3], r[4]) for r in rows if r[0] >= "2000-01-01" and r[4]}
    print("加權指數 %d 天" % len(TW))
    part_a(TW)
    part_b(TW)
    d = json.load(open(path, encoding="utf-8"))
    part_cd(d)
    part_ef(d)
    print("\n注意：E、F 只測現在還是大型股的公司（倒掉的沒算），結果偏樂觀；C、D 只有約 1.5 年資料。")


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "data.json")
