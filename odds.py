"""
odds.py - 情境機率：找出歷史上「跟現在很像」的日子，統計之後隔天／5 天／20 天怎麼走
（2026-11-25 使用者要的：判斷要用數字，不要憑感覺。例：廣達漲停隔天，我說「碰跌停機會不高」，結果真的碰到；
  全部股票統計其實約 1 成）

「很像」＝同時符合：
  前一天漲跌幅區間（漲停、大漲、小漲、平、小跌、大跌、跌停）
  離月線多遠（低 10% 以上、低 3～10%、月線附近、高 3～10%、高 10% 以上）
  月線往上或往下彎
  外資近 5 天買超或賣超
  美股費城半導體前一晚漲跌（只在有資料時用；台股開盤前已經知道）
符合的太少（< 30 筆）就逐步放寬條件（先拿掉費半、再拿掉外資、再拿掉月線方向）。

兩種歷史：
  全市場：網頁資料 data.json 全部股票（約 270 檔、1 年半）
  這一檔自己：Yahoo 11 年日 K（還原權值；沒有法人資料，不看外資條件）
用法：python odds.py 2382 [data.json]   # 單獨執行印出結果
"""
import bisect
import json
import os
import sys

D1 = (-0.095, -0.05, -0.02, 0.02, 0.05, 0.095)
D1_NAME = ("跌停", "大跌 5% 以上", "小跌 2～5%", "平盤附近", "小漲 2～5%", "大漲 5% 以上", "漲停")
M20 = (-0.10, -0.03, 0.03, 0.10)
M20_NAME = ("比月線低 10% 以上", "比月線低 3～10%", "在月線附近", "比月線高 3～10%", "比月線高 10% 以上")
SOX = (-0.03, -0.01, 0.01, 0.03)
SOX_NAME = ("費半前一晚大跌 3% 以上", "費半前一晚跌 1～3%", "費半前一晚持平", "費半前一晚漲 1～3%", "費半前一晚大漲 3% 以上")
MIN_N = 30
RAW = "https://raw.githubusercontent.com/a50134/tw-stock-screener-public/site-data/data.json"


def bucket(x, cuts):
    return bisect.bisect_right(cuts, x)


def ma(c, t, n):
    if t < n - 1:
        return None
    w = c[t - n + 1:t + 1]
    return sum(w) / n if all(w) else None


def feats(c, t, fi=None):
    """第 t 天收盤後的情境（d1, m20, slope, fi5）；資料不足回傳 None"""
    if t < 25 or not c[t] or not c[t - 1]:
        return None
    r = c[t] / c[t - 1] - 1
    if abs(r) > 0.11:  # 除權息、減資等跳動，不算
        return None
    m, m5 = ma(c, t, 20), ma(c, t - 5, 20)
    if not m or not m5:
        return None
    f5 = None
    if fi and t >= 4 and all(x is not None for x in fi[t - 4:t + 1]):
        f5 = 1 if sum(fi[t - 4:t + 1]) > 0 else 0
    return bucket(r, D1), bucket(c[t] / m - 1, M20), 1 if m >= m5 else 0, f5


def outcome(o, h, l, c, t, H=20):
    """第 t 天收盤後的結果：隔天最低／最高／收盤、5 天、20 天報酬、20 天內最大跌幅（都從第 t 天收盤算）"""
    e = t + H
    if e >= len(c) or not c[t] or not all(c[t:e + 1]) or not all(l[t + 1:e + 1]) or not h[t + 1]:
        return None
    if any(abs(c[u] / c[u - 1] - 1) > 0.11 for u in range(t + 1, e + 1)):
        return None
    p = c[t]
    return (l[t + 1] / p - 1, h[t + 1] / p - 1, c[t + 1] / p - 1, c[t + 5] / p - 1, c[e] / p - 1, min(l[t + 1:e + 1]) / p - 1)


def sox_map(rows):
    """Yahoo 日 K [(日期, 開, 高, 低, 收)] → {美國日期: 當天漲跌幅}"""
    out = {}
    for i in range(1, len(rows)):
        if rows[i - 1][4]:
            out[rows[i][0]] = rows[i][4] / rows[i - 1][4] - 1
    return out


def sox_for(dates, sm):
    """台股第 t 天收盤後、隔天開盤前的那一晚美股（美國日期＝台股同一個日期）；沒有資料就 None"""
    return [bucket(sm[d], SOX) if d in sm else None for d in dates]


def pool_market(data, sxb=None):
    """全市場：[(key, t, outcome)]，key=(d1, m20, slope, fi5, sox)"""
    P = []
    for s in data["stocks"]:
        if str(s["id"]).startswith("00"):
            continue
        c, o, h, l, fi = s["c"], s["o"], s["h"], s["l"], s.get("fi")
        for t in range(25, len(c) - 1):
            f = feats(c, t, fi)
            if not f:
                continue
            y = outcome(o, h, l, c, t)
            if y:
                P.append((f + ((sxb[t] if sxb else None),), t, y))
    return P


def pool_own(D, sm=None):
    """這一檔自己的 11 年歷史（沒有外資資料）"""
    dates = [x[0] for x in D]
    o, h, l, c = ([x[k] for x in D] for k in (1, 2, 3, 4))
    sxb = sox_for(dates, sm) if sm else None
    P = []
    for t in range(25, len(c) - 1):
        f = feats(c, t)
        if not f:
            continue
        y = outcome(o, h, l, c, t)
        if y:
            P.append((f + ((sxb[t] if sxb else None),), t, y))
    return P


LEVELS = ((0, 1, 2, 3, 4), (0, 1, 2, 3), (0, 1, 2), (0, 1), (0,))  # 逐步放寬：拿掉費半、外資、月線方向、離月線距離


def match(P, key, before=None):
    """找相似情境；before＝只用結果在這個索引之前就已知的資料（回測避免偷看未來）。回傳 (用到的條件, 結果列表)"""
    for lv in LEVELS:
        if any(key[i] is None for i in lv):
            continue
        got = [y for k, t, y in P if all(k[i] == key[i] for i in lv) and (before is None or t + 20 < before)]
        if len(got) >= MIN_N:
            return lv, got
    return (), []


def stats(Y):
    n = len(Y)
    f = lambda cond: sum(1 for y in Y if cond(y)) / n  # noqa: E731
    return {
        "n": n,
        "lo5": f(lambda y: y[0] <= -0.05), "lo9": f(lambda y: y[0] <= -0.09), "lo3": f(lambda y: y[0] <= -0.03),
        "hi5": f(lambda y: y[1] >= 0.05), "up1": f(lambda y: y[2] > 0),
        "up5": f(lambda y: y[3] > 0), "avg5": sum(y[3] for y in Y) / n,
        "up20": f(lambda y: y[4] > 0), "avg20": sum(y[4] for y in Y) / n,
        "dd10": f(lambda y: y[5] <= -0.10),
    }


def desc(key, lv):
    parts = [D1_NAME[key[0]]]
    if 1 in lv:
        parts.append(M20_NAME[key[1]])
    if 2 in lv:
        parts.append("月線往上" if key[2] else "月線往下")
    if 3 in lv:
        parts.append("外資近 5 天買超" if key[3] else "外資近 5 天賣超")
    if 4 in lv:
        parts.append(SOX_NAME[key[4]])
    return "、".join(parts)


def pc(x):
    return "%d%%" % round(x * 100)


def lines(title, key, lv, Y):
    if not Y:
        return ["・%s：相似情況太少，不統計" % title]
    s = stats(Y)
    return [
        "・%s（%s，共 %d 次）：" % (title, desc(key, lv), s["n"]),
        "　隔天：收紅 %s；最低跌 3%% 以上 %s、跌 5%% 以上 %s、碰到跌停 %s；最高漲 5%% 以上 %s" % (
            pc(s["up1"]), pc(s["lo3"]), pc(s["lo5"]), pc(s["lo9"]), pc(s["hi5"])),
        "　5 天後上漲 %s（平均 %+.1f%%）；20 天後上漲 %s（平均 %+.1f%%）；20 天內曾跌 10%% 以上 %s" % (
            pc(s["up5"]), s["avg5"] * 100, pc(s["up20"]), s["avg20"] * 100, pc(s["dd10"])),
    ]


def verdict(s):
    """依統計給一句白話結論。
    回測（research/odds_bt.py，2026-11-25）：隔天最低跌 5% 的機率算得準（預測 10～20% → 實際 18%），
    但「相似情境 20 天上漲比例」不能拿來挑股（分數高的反而勝率較低、各時段不穩定），所以結論只用隔天的數字"""
    if not s:
        return ""
    lo3, lo5, lo9 = s["lo3"], s["lo5"], s["lo9"]
    if lo5 >= 0.2:
        v = "隔天跌 5%% 以上的機會不小（約 %s），不要開盤追，掛比昨收低 3～5%% 的限價單（跌 3%% 以上約 %s 會成交）" % (pc(lo5), pc(lo3))
    elif lo3 >= 0.3:
        v = "隔天常會先拉回（跌 3%% 以上約 %s），掛比昨收低 2～3%% 的限價單比較划算" % pc(lo3)
    else:
        v = "隔天大跌的機會不高（跌 5%% 以上約 %s），掛太低可能買不到" % pc(lo5)
    if lo9 >= 0.05:
        v += "；碰到跌停的機會約 %s，不是零" % pc(lo9)
    return v + "。20 天的數字只當參考：回測顯示它不能用來預測漲跌"


def load_data(path="data.json"):
    for p in (path, "site_data.json"):
        if p and os.path.exists(p):
            try:
                d = json.load(open(p, encoding="utf-8"))
                if d.get("stocks"):
                    return d
            except Exception:
                pass
    try:
        import requests
        r = requests.get(RAW, timeout=60)
        r.raise_for_status()
        return r.json()
    except Exception:
        return None


_CACHE = {}


def run(s, data=None, D=None):
    """查個股用：s＝FinMind 格式（c, o, h, l, fi）。回傳文字"""
    import deepdive
    out = ["📊 情境機率（歷史上跟現在很像的日子，之後怎麼走）："]
    if "sox" not in _CACHE:
        _CACHE["sox"] = sox_map(deepdive.daily("^SOX", 11))
    sm = _CACHE["sox"]
    c = s["c"]
    t = len(c) - 1
    f = feats(c, t, s.get("fi"))
    if not f:
        return "\n".join(out + ["・資料不足，不統計"])
    # 最新一晚的費半：美國日期＝台股最後一天（台灣早上才有；晚上查時美股還沒收盤）
    last = (data or {}).get("asOf") or (s.get("dates") or [None])[-1]
    sx = bucket(sm[last], SOX) if last and last in sm else None
    key = f + (sx,)
    if sx is None:
        out.append("・美股今晚還沒收盤，先不看費半；隔天早上 9 點前再查會比較準")
    if data is None:
        data = _CACHE.get("data") or load_data()
        _CACHE["data"] = data
    if data:
        if "mkt" not in _CACHE:
            _CACHE["mkt"] = pool_market(data, sox_for(data["dates"], sm) if sm else None)
        lv, Y = match(_CACHE["mkt"], key)
        out += lines("全市場 %d 檔" % len([x for x in data["stocks"] if not str(x["id"]).startswith("00")]), key, lv, Y)
        sm_ = stats(Y) if Y else None
    else:
        sm_ = None
        out.append("・全市場資料抓不到，略過")
    if D is None:
        sym = deepdive.symbol(s["id"], s.get("mkt"))
        D = deepdive.daily(sym, 11) if sym else []
    own = None
    if len(D) > 300:
        P = pool_own(D, sm)
        k2 = (f[0], f[1], f[2], None, sx)
        lv2, Y2 = match(P, k2)
        out += lines("這一檔自己 %d 年" % round(len(D) / 245), k2, lv2, Y2)
        own = stats(Y2) if Y2 else None
    v = verdict(own if own and own["n"] >= MIN_N and not sm_ else sm_ or own)
    if v:
        out.append("・結論：" + v)
    return "\n".join(out)


if __name__ == "__main__":
    sid = sys.argv[1] if len(sys.argv) > 1 else "2382"
    d = load_data(sys.argv[2] if len(sys.argv) > 2 else "data.json")
    s = next(x for x in d["stocks"] if x["id"] == sid)
    print(run(s, d))
