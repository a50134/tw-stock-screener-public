"""
growth.py - 潛力成長股：先用財報挑「潛力股名單」，再用四個面向挑出真正有爆發力的，最後用型態與指標抓買點、用季線／ATR 抓賣點

一、潛力股名單（初步篩選，財報公布後名單會跟著換）
   CAN SLIM（使用者版本）：連 2 季 EPS 年增 >25%、連 2 年 EPS 年增 >25%、連 2 季營收年增 >25%、近 4 季 ROE >17%、最新一季 EPS >0.75 元
   ＋財報健檢（近 4 季營業現金流為正、負債比 <60%）＋外資投信 20／60 日買超＋20 日均量 ≥300 張
二、四個面向（加分，越多越好）
   1. 產業趨勢：同產業近 60 日漲幅（中位數）排在前 30%
   2. 技術面強勢：近 120 日相對強弱前 20%、或近 5 日創 60 日新高、或均線多頭排列（5>20>60）
   3. 籌碼面：外資＋投信近 20 日買超且有人連買 3 天以上、或千張大戶持股增加
   4. 市場關注：近 30 天新聞 5 則以上，或新聞有法說、展望、接單、擴產、漲價等字
三、買點（同一檔成長股，發動時間不一樣，用型態抓時間點）
   ・VCP 收縮型態突破：先前漲 30% 以上，之後 2～5 次回檔、一次比一次小（後一次 ≤ 前一次 0.75 倍、最後一次 ≤ 10%），
     最後一次回檔量縮；收盤帶量（> 50 日均量 1.4 倍）突破樞紐點（最後一次回檔前的高點）
   ・短線買訊：5 日線 > 20 日線，而且日 KD、週 KD、月 KD 都是 K > D
   ・網球型態：創新高後拉回 2～10 天、拉回時量縮，接著又創新高（強勢股的回檔很快被買上去）
四、賣點
   ・收盤跌破往下彎的季線（葛蘭碧法則：季線走平再下彎＝空頭）
   ・海龜 ATR 移動停損：買進後最高收盤價 −3×ATR(20)（ATR＝平均真實波幅，威爾德 1978；海龜原版 2 倍，
     台股回測 2 倍太容易被洗出去：勝率 50%、平均 +16%；3 倍 57%、+21%）
"""
import json
import os
import statistics as st

import analysis

DIR = os.path.dirname(os.path.abspath(__file__))
HOT = ("法說", "展望", "接單", "訂單", "擴產", "漲價", "新高", "成長", "AI", "產能", "滿載")


# ---------- 財報（用當時已公布的季報） ----------
def pub(qn):
    y, n = int(qn[:4]), int(qn[5])
    return {1: "%d-05-15" % y, 2: "%d-08-14" % y, 3: "%d-11-14" % y, 4: "%d-03-31" % (y + 1)}[n]


def prevy(q):
    return "%dQ%s" % (int(q[:4]) - 1, q[5])


def qrev(s):
    m = {r["m"]: r["v"] for r in s.get("rev") or []}
    o = {}
    for k in m:
        y, mm = int(k[:4]), int(k[5:7])
        n = (mm - 1) // 3 + 1
        ms = ["%d-%02d" % (y, 3 * n - 2 + i) for i in range(3)]
        if all(x in m for x in ms):
            o["%dQ%d" % (y, n)] = sum(m[x] for x in ms) * 1000
    return o


def canslim(s, day, qr=None):
    """回傳 (是否通過, 說明 dict)"""
    q = [x for x in (s.get("q") or []) if pub(x["q"]) <= day]
    if len(q) < 2:
        return False, {}
    qm = {x["q"]: x for x in q}
    qr = qr if qr is not None else qrev(s)

    def g(x):
        b = qm.get(prevy(x["q"]))
        if not b or x["eps"] is None or b["eps"] is None:
            return None
        return (x["eps"] / b["eps"] - 1) * 100 if b["eps"] > 0 else (999 if x["eps"] > 0 else None)
    g1, g0 = g(q[-1]), g(q[-2])
    Y = {}
    for x in q:
        Y.setdefault(x["q"][:4], []).append(x["eps"])
    ys = sorted(y for y in Y if len(Y[y]) == 4 and all(v is not None for v in Y[y]))
    v = [sum(Y[y]) for y in ys]
    ag = [(v[i] / v[i - 1] - 1) * 100 for i in range(1, len(v)) if v[i - 1] > 0][-2:]
    rg = []
    for x in q[-2:]:
        a, b = qr.get(x["q"]), qr.get(prevy(x["q"]))
        rg.append((a / b - 1) * 100 if a and b else None)
    fh = [x for x in (s.get("fh") or []) if pub(x["q"]) <= day]
    ni = [(qm[x["q"]].get("nm") or 0) / 100 * qr[x["q"]] for x in q[-4:] if x["q"] in qr and qm[x["q"]].get("nm") is not None]
    eqq = next((x for x in reversed(fh) if x["q"] == q[-1]["q"]), fh[-1] if fh else None)
    roe = sum(ni) / eqq["equity"] * 100 if len(ni) == 4 and eqq and eqq.get("equity") else None
    ok = (g1 is not None and g0 is not None and g1 > 25 and g0 > 25 and ag and all(x > 25 for x in ag)
          and all(x is not None and x > 25 for x in rg) and roe is not None and roe > 17 and (q[-1]["eps"] or 0) > 0.75)
    return ok, {"g": [g0, g1], "ag": ag, "rg": rg, "roe": roe, "eps": q[-1]["eps"], "q": q[-1]["q"]}


def health(s, day):
    """近 4 季營業現金流為正＋負債比 <60%（金融保險不看負債比；沒資料算通過）"""
    f = [x for x in (s.get("fh") or []) if pub(x["q"]) <= day]
    if len(f) < 4:
        return True
    oc = [x.get("ocf") for x in f[-4:]]
    ocf = sum(oc) if all(v is not None for v in oc) else None
    L = f[-1]
    fin = any(k in (s.get("industry") or "") for k in ("金融", "保險"))
    debt = L["liab"] / L["assets"] * 100 if L.get("liab") is not None and L.get("assets") else None
    return (ocf is None or ocf > 0) and (fin or debt is None or debt < 60)


def base(s, t, D, qr=None):
    """潛力股名單的條件（全部要符合）"""
    c, v, fi, it = s["c"], s["v"], s.get("fi") or [], s.get("it") or []
    if t < 60 or sum(v[t - 19:t + 1]) / 20 < 300:
        return False, {}
    if fi and it:
        a = sum(fi[t - 19:t + 1]) + sum(it[t - 19:t + 1])
        b = sum(fi[t - 59:t + 1]) + sum(it[t - 59:t + 1])
        if not (a > 0 and b > 0):
            return False, {}
    ok, info = canslim(s, D[t], qr)
    if not ok or not health(s, D[t]):
        return False, info
    return True, info


# ---------- 技術指標 ----------
def ma(c, n, t):
    return sum(c[t - n + 1:t + 1]) / n


def kd(h, l, c, step, n=9):
    """KD(9)：step＝1 日線、5 週線、20 月線（用交易日切 K 棒，最後一根到今天）。回傳每天的 (K, D)"""
    N = len(c)
    K, D_ = [None] * N, [None] * N
    k = d = 50.0
    last = None
    for t in range(step * n, N):
        # 以今天為最後一根，往回切 n 根
        if step == 1 or (N - 1 - t) % step == 0 or last is None:
            lo = min(l[t - step * n + 1:t + 1])
            hi = max(h[t - step * n + 1:t + 1])
            rsv = (c[t] - lo) / (hi - lo) * 100 if hi > lo else 50
            k = k * 2 / 3 + rsv / 3
            d = d * 2 / 3 + k / 3
            last = (k, d)
        else:  # 還沒收完這根：用上一根的 K、D 加上今天的 RSV 估算
            lo = min(l[t - step * n + 1:t + 1])
            hi = max(h[t - step * n + 1:t + 1])
            rsv = (c[t] - lo) / (hi - lo) * 100 if hi > lo else 50
            k0, d0 = last
            kk = k0 * 2 / 3 + rsv / 3
            K[t], D_[t] = kk, d0 * 2 / 3 + kk / 3
            continue
        K[t], D_[t] = k, d
    return K, D_


def atr(h, l, c, t, n=20):
    tr = [max(h[i] - l[i], abs(h[i] - c[i - 1]), abs(l[i] - c[i - 1])) for i in range(t - n + 1, t + 1)]
    return sum(tr) / n


def vcp(s, t):
    """VCP 收縮型態：回傳 None 或 {pivot, cons:[回檔%...], vol_dry, breakout}"""
    c, h, l, v = s["c"], s["h"], s["l"], s["v"]
    if t < 130:
        return None
    lo0 = min(c[t - 130:t - 30])
    if max(c[t - 60:t + 1]) / lo0 < 1.3:  # 先前要有一段 30% 以上的漲幅（初升段）
        return None
    # 找整理區：近 60 天的最高點開始
    top = max(range(t - 60, t), key=lambda i: h[i])
    if t - top < 10:
        return None
    # 在整理區找一波一波的回檔（高點 → 低點），轉折用 3 天的局部高低點
    seg, i, cons = [], top, []
    while i < t:
        pk = i
        j = i + 1
        lo_i = j
        while j < t:
            if l[j] < l[lo_i]:
                lo_i = j
            if h[j] > h[pk] * 0.999 and j > lo_i:  # 反彈回到前高附近：一波結束
                break
            # 反彈超過這波跌幅的一半也算結束
            if j > lo_i + 2 and c[j] > l[lo_i] + (h[pk] - l[lo_i]) * 0.6:
                break
            j += 1
        depth = (h[pk] - l[lo_i]) / h[pk] * 100
        if depth >= 2:
            cons.append((pk, lo_i, depth))
        nxt = max(range(lo_i, min(t, j + 1)), key=lambda k: h[k]) if lo_i < t else t
        if nxt <= i:
            break
        i = nxt if nxt > lo_i else j
        if j >= t:
            break
    if not 2 <= len(cons) <= 5:
        return None
    ds = [x[2] for x in cons]
    if ds[0] > 35 or ds[-1] > 10 or any(ds[k] > ds[k - 1] * 0.75 for k in range(1, len(ds))):
        return None
    pk, lo_i, _ = cons[-1]
    v50 = sum(v[t - 49:t + 1]) / 50
    vlast = sum(v[pk:t]) / max(1, t - pk)
    vfirst = sum(v[cons[0][0]:cons[0][1] + 1]) / max(1, cons[0][1] - cons[0][0] + 1)
    pivot = max(h[pk:t])  # 樞紐點：最後一次回檔前的高點
    return {"pivot": pivot, "cons": [round(x, 1) for x in ds], "vol_dry": vlast < vfirst * 0.8 or vlast < v50 * 0.7,
            "breakout": c[t] > pivot and v[t] > v50 * 1.4 and c[t] <= pivot * 1.05}


def kd3(K, D):
    """日、週、月 KD 都是 K > D"""
    return lambda t: all(k[t] is not None and d[t] is not None and k[t] > d[t] for k, d in zip(K, D))


def tennis(s, t):
    """網球型態：近 15 天內創 60 日新高 → 拉回 2～10 天（量縮）→ 今天又創新高"""
    c, v = s["c"], s["v"]
    if t < 80 or c[t] < max(c[t - 59:t]):
        return False
    prev = [i for i in range(t - 15, t - 2) if c[i] >= max(c[i - 59:i])]
    if not prev:
        return False
    p = prev[-1]
    gap = t - p
    if not 2 <= gap <= 10:
        return False
    v_pull = sum(v[p + 1:t]) / max(1, gap - 1)
    return v_pull < sum(v[p - 19:p + 1]) / 20  # 拉回量縮


# ---------- 四個面向 ----------
def industry_rank(data, t):
    """每個產業近 60 日漲幅中位數的排名（0～100，越大越強）"""
    by = {}
    for s in data["stocks"]:
        c = s["c"]
        if t < 60 or not c[t - 60] or s["id"].startswith("00"):
            continue
        by.setdefault(s.get("industry") or "其他", []).append(c[t] / c[t - 60] - 1)
    med = {k: st.median(v) for k, v in by.items() if len(v) >= 3}
    order = sorted(med, key=lambda k: med[k])
    return {k: (i + 1) / len(order) * 100 for i, k in enumerate(order)}


def rs_rank(data, t, n=120):
    arr = sorted((s["c"][t] / s["c"][t - n], s["id"]) for s in data["stocks"] if t >= n and s["c"][t - n])
    return {sid: (i + 1) / len(arr) * 100 for i, (_, sid) in enumerate(arr)}


def four(s, t, ind_rk, rs_rk, live=True):
    """回傳 [(面向, 是否符合, 說明)]"""
    c, fi, it = s["c"], s.get("fi") or [0] * len(s["c"]), s.get("it") or [0] * len(s["c"])
    out = []
    r = ind_rk.get(s.get("industry") or "其他")
    out.append(("產業趨勢", r is not None and r >= 70, "%s 產業強度前 %.0f%%" % (s.get("industry") or "", 100 - r) if r is not None else "產業股票太少"))
    nh = any(c[i] >= max(c[i - 59:i + 1]) for i in range(t - 4, t + 1))
    bull = ma(c, 5, t) > ma(c, 20, t) > ma(c, 60, t)
    rr = rs_rk.get(s["id"], 0)
    tech = [x for x, g in (("相對強弱前 %.0f%%" % (100 - rr), rr >= 80), ("近 5 日創 60 日新高", nh), ("均線多頭排列", bull)) if g]
    out.append(("技術面強勢", bool(tech), "、".join(tech) or "還不夠強"))
    f20, i20 = sum(fi[t - 19:t + 1]), sum(it[t - 19:t + 1])
    stk = lambda a: next((k for k in range(0, 30) if a[t - k] <= 0), 30)
    chip = []
    if f20 + i20 > 0 and max(stk(fi), stk(it)) >= 3:
        chip.append("外資＋投信 20 日買超 %s 張、%s連買 %d 天" % (analysis.zh(f20 + i20), "外資" if stk(fi) >= stk(it) else "投信", max(stk(fi), stk(it))))
    hw = [x for x in (s.get("hw") or []) if x.get("big") is not None]
    if live and len(hw) >= 2 and hw[-1]["big"] > hw[-2]["big"]:
        chip.append("千張大戶 %.1f%% → %.1f%%" % (hw[-2]["big"], hw[-1]["big"]))
    out.append(("籌碼面", bool(chip), "；".join(chip) or "法人還沒明顯進駐"))
    if live:
        news = s.get("news") or []
        hot = [n.get("title", "") for n in news if any(k in n.get("title", "") for k in HOT)]
        ok = len(news) >= 5 or bool(hot)
        out.append(("市場關注", ok, ("近 30 天新聞 %d 則" % len(news)) + ("，題材：" + hot[0][:30] if hot else "")))
    return out


# ---------- 每晚 ----------
POOL = "growth_pool.json"


def nightly(data, profiles=None, pool_path=None):
    """更新潛力股名單並產生報告文字。名單存在 growth_pool.json（私人專案同步）"""
    pp = pool_path or os.path.join(DIR, POOL)
    P = json.load(open(pp, encoding="utf-8")) if os.path.exists(pp) else {"stocks": {}}
    D = data["dates"]
    t = len(D) - 1
    ind_rk, rs_rk = industry_rank(data, t), rs_rank(data, t)
    by = {s["id"]: s for s in data["stocks"]}
    today = D[t]
    new, alerts, rows = [], [], []
    if not P["stocks"]:  # 第一次：往回看 60 個交易日，當時符合的也放進名單
        for s in data["stocks"]:
            if s["id"].startswith("00") or len(s["c"]) < 130:
                continue
            for u in range(max(130, t - 60), t, 5):
                ok, info = base(s, u, D)
                if ok:
                    P["stocks"][s["id"]] = {"name": s["name"], "added": D[u], "px": s["c"][u], "q": info.get("q")}
                    break
    for s in data["stocks"]:
        if s["id"].startswith("00") or len(s["c"]) < 130:
            continue
        ok, info = base(s, t, D)
        rec = P["stocks"].get(s["id"])
        if ok and not rec:
            P["stocks"][s["id"]] = rec = {"name": s["name"], "added": today, "px": s["c"][t], "q": info.get("q")}
            new.append(s["id"])
        if rec:
            rec["ok"] = ok
            rec["last"] = today
    # 追蹤名單裡每一檔
    for sid, rec in list(P["stocks"].items()):
        s = by.get(sid)
        if not s:
            continue
        c, h, l = s["c"], s["h"], s["l"]
        F = four(s, t, ind_rk, rs_rk)
        nf = sum(1 for _, g, _ in F if g)
        V = vcp(s, t)
        K, Dd = zip(*(kd(h, l, c, k) for k in (1, 5, 20)))
        sig3 = ma(c, 5, t) > ma(c, 20, t) and kd3(K, Dd)(t)
        sig3_new = sig3 and not (ma(c, 5, t - 1) > ma(c, 20, t - 1) and kd3(K, Dd)(t - 1))
        tb = tennis(s, t)
        a = atr(h, l, c, t)
        m60, m60p = ma(c, 60, t), ma(c, 60, t - 5)
        pos = rec.get("pos")
        status = []
        if V and V["breakout"]:
            status.append("🚀 VCP 帶量突破樞紐點 %s（回檔 %s）" % (analysis.px(V["pivot"]), "→".join("%.0f%%" % x for x in V["cons"])))
        elif V:
            status.append("⏳ VCP 收縮中（回檔 %s%s），樞紐點 %s" % ("→".join("%.0f%%" % x for x in V["cons"]), "、量縮" if V["vol_dry"] else "", analysis.px(V["pivot"])))
        if sig3_new:
            status.append("📈 短線買訊剛出現：5 日線 > 20 日線＋日／週／月 KD 都黃金交叉")
        elif sig3:
            status.append("短線多方（5 日線 > 20 日線、日週月 KD 都 K > D）")
        if tb:
            status.append("🎾 網球型態：拉回量縮後再創新高")
        # 賣點（有標記進場的才算移動停損）
        exitw = []
        if c[t] < m60 and m60 < m60p:
            exitw.append("跌破往下彎的季線 %s" % analysis.px(m60))
        if pos:
            pos["hi"] = max(pos.get("hi", 0), c[t])
            stop = pos["hi"] - 3 * a
            pos["stop"] = round(stop, 2)
            if c[t] < stop:
                exitw.append("跌破 ATR 移動停損 %s（最高 %s − 3×ATR %s）" % (analysis.px(stop), analysis.px(pos["hi"]), analysis.px(a)))
        # 進場訊號：VCP 突破或短線買訊剛出現或網球型態，且四面向至少 2 個
        trig = (V and V["breakout"]) or sig3_new or tb
        if trig and nf >= 2 and not pos and not exitw:
            rec["pos"] = pos = {"d": today, "px": c[t], "hi": c[t], "stop": round(c[t] - 3 * a, 2), "why": status[0] if status else ""}
            alerts.append(sid)
        if pos and exitw:
            alerts.append(sid)
            rec.setdefault("closed", []).append({"in": pos["d"], "px": pos["px"], "out": today, "outpx": c[t], "ret": round((c[t] / pos["px"] - 1) * 100, 1), "why": exitw[0]})
            rec["pos"] = None
        rows.append((sid, rec, F, nf, status, exitw, a))
    # 12 週沒通過初步篩選的移出名單
    for sid, rec in list(P["stocks"].items()):
        if not rec.get("ok") and not rec.get("pos") and _weeks(rec.get("added"), today) >= 12:
            del P["stocks"][sid]
    json.dump(P, open(pp, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    return text(rows, new, alerts, today), P


def _weeks(a, b):
    import datetime as dt
    try:
        return (dt.date.fromisoformat(b) - dt.date.fromisoformat(a)).days / 7
    except Exception:
        return 0


def text(rows, new, alerts, today):
    if not rows:
        return ""
    L = ["🌱 潛力成長股追蹤（%s）：財報挑出的潛力股，等型態與指標發動再買" % today,
         "名單 %d 檔%s" % (len(rows), "；今天新加入：%s" % "、".join(new) if new else "")]
    rows.sort(key=lambda r: (not (r[0] in alerts), -r[3]))
    for sid, rec, F, nf, status, exitw, a in rows:
        pos = rec.get("pos")
        done = (rec.get("closed") or [])[-1:] if sid in alerts and not pos else []
        head = "・%s %s（%s 加入，四面向 %d/4：%s）" % (sid, rec["name"], rec["added"], nf, "、".join(n for n, g, _ in F if g) or "—")
        L.append(head)
        if status:
            L.append("　" + "；".join(status))
        if exitw and sid in alerts:
            L.append("　🔻 出場訊號：%s（%s 發動價 %s → %+.1f%%）" % ("；".join(exitw), done[0]["in"], analysis.px(done[0]["px"]), done[0]["ret"]) if done else "　🔻 出場訊號：" + "；".join(exitw))
        elif exitw:
            L.append("　⚠️ " + "；".join(exitw) + "：趨勢轉弱，還不是買點")
        elif pos:
            L.append("　✅ 追蹤中：%s 以 %s 發動（%s），移動停損 %s" % (pos["d"], analysis.px(pos["px"]), pos.get("why", ""), analysis.px(pos["stop"])))
        else:
            L.append("　還沒發動：等 VCP 突破樞紐點、短線買訊或網球型態（四面向至少 2 個）")
    L.append("賣出：收盤跌破往下彎的季線，或跌破移動停損（最高收盤 − 3 倍 ATR）。名單每週日檢討，12 週財報條件不再符合的移出。")
    return "\n".join(L)


if __name__ == "__main__":
    import sys
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    txt, _ = nightly(d, pool_path=sys.argv[2] if len(sys.argv) > 2 else None)
    print(txt)
