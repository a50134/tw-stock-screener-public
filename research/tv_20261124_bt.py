"""
錢線百分百 2026-11-23（有完整字幕）三個具體說法的回測
A 毓棠「套牢別亂攤平，出現落底訊號才加碼」：股票從 20 日高點跌 15% 以上後，10 天內第一次出現
   a1 爆量下影線（量 ≥ 前 5 天平均 2 倍、下影線 ≥ 股價 3% 且比實體長）
   a2 連續 3 天不破前低（前一天創 20 日新低，之後 3 天最低價都沒跌破）
   a3 實體紅 K 站回 5 日線（漲 1.5% 以上的紅 K、收盤站上 5 日線、前一天在 5 日線下）
   對照：跌 15% 當天就買（盲目攤平）
   隔天開盤買，看 20／60 天報酬、賺錢機率、買了之後還會再跌多深
B 毓棠「倒金字塔減碼」：弱勢股（收盤在季線下、季線下彎、離 60 日高點 −20% 以上）
   反彈到 5 日線賣 20%、10 日線賣 30%、月線賣剩下的（60 天內沒碰到就第 60 天賣）
   對照：抱著不動 60 天
C 嘉明「外資 3 日平均買超金額突破 5 日平均」：大盤弱（0050 在月線下且 5 天下跌）時，
   每天挑「3 日平均買超金額 − 5 日平均」最大的前 10 檔，看之後 20 天比同一天全部股票平均多賺多少（資料只有約 1.5 年）
用法：python research/tv_20261124_bt.py data.json
"""
import json
import os
import statistics as stt
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from sepa_bt import yahoo  # noqa: E402


def ma(c, t, n):
    return sum(c[t - n + 1:t + 1]) / n


def fwd(o, l, c, t, H):
    if t + 1 + H >= len(c):
        return None
    e = o[t + 1]
    return c[t + 1 + H] / e - 1 - 0.006, min(l[t + 1:t + 2 + H]) / e - 1


def show(name, rs):
    for H in (20, 60):
        r = [x[H] for x in rs if x.get(H)]
        if not r:
            continue
        ret = [z[0] for z in r]
        dd = sorted(z[1] for z in r)
        print("　%s %d 天：%d 次，賺錢 %.0f%%、平均 %+.1f%%、中位數 %+.1f%%；買了之後再跌 中位數 %.1f%%、最慘 1 成 %.1f%%" % (
            name, H, len(r), sum(x > 0 for x in ret) / len(r) * 100, stt.mean(ret) * 100, stt.median(ret) * 100,
            stt.median(dd) * 100, dd[len(dd) // 10] * 100))


def main(path):
    d = json.load(open(path, encoding="utf-8"))
    U = sorted(((float(x["shares"]) * x["c"][-1], x) for x in d["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"] and x["c"][-1]), key=lambda z: -z[0])[:150]
    A = {k: [] for k in ("跌 15% 當天就買（盲目攤平）", "a1 爆量下影線", "a2 連 3 天不破前低", "a3 實體紅K站回5日線", "a1～a3 任一出現")}
    B = {"倒金字塔減碼": [], "抱著不動 60 天": [], "倒金字塔比抱著多": []}
    ok = 0
    for _, x in U:
        rows = yahoo(x["id"] + (".TWO" if x.get("mkt") == "tpex" else ".TW"))
        if len(rows) < 400:
            continue
        ok += 1
        o, h, l, c, v = ([r[i] for r in rows] for i in range(1, 6))
        n = len(c)
        last = -99
        for t in range(70, n - 2):
            if t - last <= 20 or c[t] / max(h[t - 19:t + 1]) - 1 > -0.15:
                continue
            last = t
            A["跌 15% 當天就買（盲目攤平）"].append({H: fwd(o, l, c, t, H) for H in (20, 60)})
            hit = {}
            for k in range(t, min(t + 10, n - 2)):
                body = abs(c[k] - o[k])
                low_sh = min(o[k], c[k]) - l[k]
                av5 = sum(v[k - 5:k]) / 5
                if "a1" not in hit and av5 and v[k] >= 2 * av5 and low_sh >= 0.03 * c[k] and low_sh > body:
                    hit["a1"] = k
                if "a2" not in hit and k >= 3 and l[k - 3] <= min(l[k - 22:k - 3]) and min(l[k - 2:k + 1]) >= l[k - 3]:
                    hit["a2"] = k
                if "a3" not in hit and c[k] > o[k] * 1.015 and c[k] > ma(c, k, 5) and c[k - 1] < ma(c, k - 1, 5):
                    hit["a3"] = k
            for key, name in (("a1", "a1 爆量下影線"), ("a2", "a2 連 3 天不破前低"), ("a3", "a3 實體紅K站回5日線")):
                if key in hit:
                    A[name].append({H: fwd(o, l, c, hit[key], H) for H in (20, 60)})
            if hit:
                k = min(hit.values())
                A["a1～a3 任一出現"].append({H: fwd(o, l, c, k, H) for H in (20, 60)})
        # B 倒金字塔
        last = -99
        for t in range(130, n - 62):
            m60, m60p = ma(c, t, 60), ma(c, t - 5, 60)
            if t - last <= 40 or not (c[t] < m60 and m60 < m60p and c[t] / max(h[t - 59:t + 1]) - 1 <= -0.20):
                continue
            last = t
            left, cash, steps = 1.0, 0.0, [(5, 0.2), (10, 0.3), (20, 1.0)]
            for k in range(t + 1, t + 61):
                while steps and c[k] >= ma(c, k, steps[0][0]):
                    p = steps[0][1] if steps[0][1] < 1 else left
                    sell = min(left, p)
                    cash += sell * c[k] / c[t]
                    left -= sell
                    steps.pop(0)
                if left <= 1e-9:
                    break
            val = cash + left * c[t + 60] / c[t] - 1
            hold = c[t + 60] / c[t] - 1
            B["倒金字塔減碼"].append(val)
            B["抱著不動 60 天"].append(hold)
            B["倒金字塔比抱著多"].append(val - hold)
    print("個股 %d 檔（市值前 150，Yahoo 約 11 年）" % ok)
    print("\n【A 落底訊號才加碼 vs 盲目攤平】（隔天開盤買，扣成本 0.6%）")
    for k, rs in A.items():
        show(k, rs)
    print("\n【B 弱勢股倒金字塔減碼 vs 抱著】%d 次" % len(B["倒金字塔減碼"]))
    for k, rs in B.items():
        if rs:
            print("　%s：平均 %+.1f%%、中位數 %+.1f%%、%s %.0f%%" % (k, stt.mean(rs) * 100, stt.median(rs) * 100,
                                                     "勝過抱著" if "比" in k else "賺錢", sum(x > 0 for x in rs) / len(rs) * 100))

    # C 外資 3 日平均買超金額突破 5 日平均
    S = [x for _, x in U if x.get("fi") and len(x["fi"]) == len(x["c"])]
    e = next((x for x in d["stocks"] if x["id"] == "0050"), None)
    D = d["dates"]
    if not e:
        print("\n沒有 0050，跳過 C")
        return
    ec = e["c"]
    ex = []
    for t in range(20, len(D) - 20):
        if not (ec[t] < ma(ec, t, 20) and ec[t] < ec[t - 5]):
            continue
        rows = []
        for x in S:
            c, fi = x["c"], x["fi"]
            if not c[t] or not c[t + 20]:
                continue
            a3 = sum(fi[t - 2:t + 1][i] * c[t - 2 + i] for i in range(3)) / 3
            a5 = sum(fi[t - 4:t + 1][i] * c[t - 4 + i] for i in range(5)) / 5
            rows.append((a3 - a5, a3, c[t + 20] / c[t] - 1))
        if len(rows) < 50:
            continue
        allr = stt.mean(z[2] for z in rows)
        top = sorted([z for z in rows if z[1] > 0], key=lambda z: -z[0])[:10]
        if top:
            ex.append((stt.mean(z[2] for z in top), allr))
    if ex:
        diff = [a - b for a, b in ex]
        print("\n【C 大盤弱時，外資 3 日平均買超金額突破 5 日平均的前 10 檔】%d 天（%s～）" % (len(ex), D[0]))
        print("　前 10 檔 20 天平均 %+.1f%%（賺錢 %.0f%%）；同一天全部股票平均 %+.1f%%；贏過全部的天數 %.0f%%" % (
            stt.mean(a for a, _ in ex) * 100, sum(a > 0 for a, _ in ex) / len(ex) * 100, stt.mean(b for _, b in ex) * 100,
            sum(x > 0 for x in diff) / len(diff) * 100))


if __name__ == "__main__":
    main(sys.argv[1])
