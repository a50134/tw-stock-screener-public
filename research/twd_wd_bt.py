"""
2026-11-13 使用者同意的兩個回測（在 GitHub 雲端跑，要連 Yahoo、FinMind）
A. 台幣由貶轉升 → 之後加權指數是不是比較會漲？
   美元兌台幣（Yahoo TWD=X）。三種「轉升」定義，同一種訊號 20 天內只算一次：
   A1 匯率 60 天內創新高（台幣最弱）後，從高點回落 1.5% 以上且跌破 20 日線
   A2 匯率 20 日線由上往下穿過 60 日線（升值趨勢成形）
   A3 匯率曾到 33 以上，之後收盤回到 32.5 以下
   比較：之後 20／60／120 天加權指數報酬 vs 任何一天買
B. 年底作帳：投信、外資同時在買、投信持股還不多的股票，11～12 月是不是比較會漲？
   股票：網頁資料（site-data）市值前 150 檔（現在的大公司，有倖存者偏差，結果偏樂觀，兩組比較時影響較小）
   投信持股比例 FinMind 沒有現成資料，用「近 2 年投信累計買超 ÷ 發行股數」估計；千張大戶歷史資料要付費，這次不測
   進場：每年 11/1、11/15 後第一個交易日收盤買；出場：12 月最後一個交易日
   對照：同樣條件放在 5/1 → 6/30（不是作帳季），看是不是只有年底才有效
用法：FINMIND_TOKEN=… python research/twd_wd_bt.py data.json
"""
import json
import os
import statistics as stt
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import fetch_finmind
import rescue_study as rs


def pct(x):
    return "—" if x is None else "%+.1f%%" % (x * 100)


def grp(name, L, lose="下跌機率"):
    L = [x for x in L if x is not None]
    if not L:
        return "・%s：0 筆" % name
    return "・%-30s %4d 筆｜平均 %s｜中位數 %s｜%s %.0f%%｜最差 %s" % (
        name, len(L), pct(stt.mean(L)), pct(stt.median(L)), lose, 100 * sum(x < 0 for x in L) / len(L), pct(min(L)))


def ma(c, k, t):
    return sum(c[t - k + 1:t + 1]) / k if t >= k - 1 else None


# ---------------- A ----------------
def part_a():
    print("=" * 60 + "\n【A】台幣由貶轉升 → 加權指數之後的表現\n")
    fx, tw = rs.yahoo("TWD=X"), rs.yahoo("%5ETWII")
    D = sorted(d for d in tw if d in fx and d >= "2005-01-01")
    f = [fx[d] for d in D]
    for i in range(1, len(f)):  # Yahoo 匯率偶爾有錯價：單日跳 3% 以上當作前一天
        if abs(f[i] / f[i - 1] - 1) > 0.03:
            f[i] = f[i - 1]
    c = [tw[d] for d in D]
    n = len(D)
    print("資料 %s～%s，%d 天；最新匯率 %.2f\n" % (D[0], D[-1], n, f[-1]))
    H = (20, 60, 120)
    fw = lambda t, h: c[t + h] / c[t] - 1 if t + h < n else None
    base = {h: [fw(t, h) for t in range(60, n)] for h in H}
    sig = {"A1 創高後回落 1.5%＋跌破 20 日線": [], "A2 20 日線穿過 60 日線向下": [], "A3 曾到 33 以上、回到 32.5 以下": []}
    last = {k: -99 for k in sig}
    above33 = False
    for t in range(61, n):
        hi_t = max(range(t - 59, t + 1), key=lambda k: f[k])
        a1 = t - hi_t <= 20 and f[t] <= f[hi_t] * 0.985 and f[t] < ma(f, 20, t) and f[t - 1] >= ma(f, 20, t - 1) * 0.999
        a2 = ma(f, 20, t) < ma(f, 60, t) and ma(f, 20, t - 1) >= ma(f, 60, t - 1)
        if f[t] >= 33:
            above33 = True
        a3 = above33 and f[t] <= 32.5
        if a3:
            above33 = False
        for k, ok in zip(sig, (a1, a2, a3)):
            if ok and t - last[k] > 20:
                last[k] = t
                sig[k].append(t)
    for h in H:
        print("抱 %d 天" % h)
        print(grp("任何一天買（基準）", base[h]))
        for k, L in sig.items():
            print(grp(k, [fw(t, h) for t in L]))
    print("\n最近 10 次 A1／A2 訊號：")
    for k in list(sig)[:2]:
        print("  %s：%s" % (k[:2], "、".join("%s(%s)" % (D[t], pct(fw(t, 60))) for t in sig[k][-10:])))
    print("  A3 全部：%s" % "、".join("%s(%s)" % (D[t], pct(fw(t, 60))) for t in sig["A3 曾到 33 以上、回到 32.5 以下"]))
    hi_t = max(range(n - 60, n), key=lambda k: f[k])
    print("\n現在：近 60 天匯率最高 %.2f（%s），現在 %.2f，20 日線 %.2f、60 日線 %.2f" % (f[hi_t], D[hi_t], f[-1], ma(f, 20, n - 1), ma(f, 60, n - 1)))


# ---------------- B ----------------
def part_b(path):
    print("\n" + "=" * 60 + "\n【B】年底作帳：投信＋外資同買、投信持股不多\n")
    fetch_finmind.TOKEN = (os.environ.get("FINMIND_TOKEN") or "").strip()
    d = json.load(open(path, encoding="utf-8"))
    L = sorted(((float(x["shares"]) * x["c"][-1], x) for x in d["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"] and x["c"][-1]), key=lambda z: -z[0])[:150]
    tw = rs.yahoo("%5ETWII")
    TD = sorted(d0 for d0 in tw if d0 >= "2015-01-01")
    tix = {d0: i for i, d0 in enumerate(TD)}
    years = range(2016, int(TD[-1][:4]) + 1)
    wins = []
    for y in years:
        for m0, d0, m1, tag in ((11, 1, 12, "年底 11/1 買"), (11, 15, 12, "年底 11/15 買"), (5, 1, 6, "對照 5/1 買")):
            a = next((k for k in TD if k >= "%d-%02d-%02d" % (y, m0, d0)), None)
            b = max((k for k in TD if k[:7] == "%d-%02d" % (y, m1)), default=None)
            if a and b and b > a and b[:4] == str(y):
                wins.append((y, tag, a, b))
    R = {}
    ok = 0
    for _, x in L:
        sid = x["id"]
        px = rs.yahoo(sid + (".TWO" if x.get("mkt") == "tpex" else ".TW"))
        inst = fetch_finmind.get("TaiwanStockInstitutionalInvestorsBuySell", sid, "2014-01-01")
        hold = fetch_finmind.get("TaiwanStockShareholding", sid, "2015-01-01")
        if not px or not inst or not hold:
            continue
        ok += 1
        it, fi = {}, {}
        for r in inst:
            net = (r.get("buy") or 0) - (r.get("sell") or 0)
            if r.get("name") == "Investment_Trust":
                it[r["date"]] = it.get(r["date"], 0) + net
            elif r.get("name") in ("Foreign_Investor", "Foreign_Dealer_Self"):
                fi[r["date"]] = fi.get(r["date"], 0) + net
        sh = {r["date"]: r.get("NumberOfSharesIssued") for r in hold if r.get("NumberOfSharesIssued")}
        shd = sorted(sh)
        idates = sorted(set(it) | set(fi))
        for y, tag, a, b in wins:
            if a not in px or b not in px:
                continue
            past = [k for k in idates if k < a]
            if len(past) < 400:
                continue
            p20, p500 = past[-20:], past[-500:]
            it20, fi20 = sum(it.get(k, 0) for k in p20), sum(fi.get(k, 0) for k in p20)
            s0 = next((sh[k] for k in reversed(shd) if k < a), None)
            if not s0:
                continue
            ithold = max(0, sum(it.get(k, 0) for k in p500)) / s0
            ex = (px[b] / px[a] - 1) - (tw[b] / tw[a] - 1)
            g = R.setdefault(tag, {k: [] for k in ("全部", "投信近 20 天買超", "投信＋外資同買", "投信＋外資同買＋投信持股估計 <10%", "投信＋外資同買＋投信持股估計 ≥10%", "投信賣超")})
            g["全部"].append(ex)
            if it20 > 0:
                g["投信近 20 天買超"].append(ex)
            if it20 < 0:
                g["投信賣超"].append(ex)
            if it20 > 0 and fi20 > 0:
                g["投信＋外資同買"].append(ex)
                g["投信＋外資同買＋投信持股估計 <10%" if ithold < 0.10 else "投信＋外資同買＋投信持股估計 ≥10%"].append(ex)
            R.setdefault(("年", tag, y), []).append((ex, it20 > 0 and fi20 > 0 and ithold < 0.10))
    print("有資料 %d 檔；%d～%d 年\n" % (ok, years[0], years[-1]))
    for tag in ("年底 11/1 買", "年底 11/15 買", "對照 5/1 買"):
        print("%s → %s（比加權指數多賺）" % (tag, "6 月底賣" if "5/1" in tag else "12 月底賣"))
        for k, v in R.get(tag, {}).items():
            print(grp(k, v, "輸大盤機率"))
    print("\n每年「投信＋外資同買＋持股 <10%」比全部多賺（11/1 買）：")
    for y in years:
        v = R.get(("年", "年底 11/1 買", y)) or []
        s = [e for e, k in v if k]
        if v and s:
            print("  %d：符合 %d 檔 平均 %s｜全部 %s" % (y, len(s), pct(stt.mean(s)), pct(stt.mean(e for e, _ in v))))


if __name__ == "__main__":
    if "--b" not in sys.argv:
        part_a()
    if "--a" not in sys.argv:
        part_b(next((a for a in sys.argv[1:] if a.endswith(".json")), "data.json"))
