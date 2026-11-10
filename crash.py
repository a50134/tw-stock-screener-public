"""
crash.py - 大跌撿好股（3-3-4 分批加碼法）

什麼時候啟動：0050 近 5 日跌 6% 以上（一次大跌事件，之後 30 個交易日內持續追蹤）
挑哪些股票（大跌那天）：
  財報健檢通過（fin_health.check）、近 4 季 EPS 合計 > 0（斷捨離沒有基本面的）、
  大跌前站在季線上（本來就強，被大盤拖下來）、5 日跌 10% 以上、20 日均量 ≥ 500 張；
  外資 5 日賣超又融資增加（散戶接刀的投機股）剔除；法人 5 日沒賣超的排前面，再看跌得深
買法（使用者定的 3-3-4 分批）：
  第 1 批 30%：跌破整數關卡＋超賣背離（股價創 20 日新低、RSI 沒有創新低，或 RSI < 30 往上勾）
  第 2 批 30%：站穩 5 日線（連 2 天收在 5 日線上）＋融資大退（融資餘額比大跌前少 10% 以上）
  第 3 批 40%：放量長紅突破月線（收盤站上月線、量 ≥ 20 日均量 1.5 倍、紅 K 實體 ≥ 3%）
汰弱留強：買進後跌破大跌事件的最低價再低 5%，不再加碼
系統性衰退不撿（regime）：美股跌破 200 日線＋近一年美債殖利率倒掛 → 只列名單不買（1997～2026 年 80 次大跌：這種情況 82% 撿了會套）
大盤落地指標（使用者定的止跌訊號，market_bottom）：融資連續大減、爆量長下影線、3 天不破底、KD／RSI 低檔金叉、台積電聯發科站穩
  回測：等 2 個訊號才買反而變差（抱 20 天勝率 61%→48%，大跌常是 V 型反彈）；3 個以上只出現過 1 波（20 天勝率 94%），所以只當參考，不擋買進

用法：python crash.py [data.json] [--bt]   # --bt 用歷史大跌回測
"""
import json
import math
import os
import sys

import exits
import fin_health

DIR = os.path.dirname(os.path.abspath(__file__))
TRIG = -0.06      # 0050 近 5 日跌幅門檻
DROP = -0.10      # 個股 5 日跌幅門檻
WINDOW = 30       # 大跌後追蹤幾個交易日
TOP = 8
LOTS = (0.3, 0.3, 0.4)


def r5(c, t):
    return c[t] / c[t - 5] - 1 if t >= 5 and c[t - 5] else 0


def events(D, m):
    """0050 大跌事件的起始日（連續大跌算同一波；排除分割造成的假跌）"""
    out, last = [], -99
    for t in range(5, len(D)):
        r = r5(m, t)
        if -0.4 < r <= TRIG:
            if t - last > 5:  # 中間有 5 個交易日以上沒在大跌，就算新的一波
                out.append(t)
            last = t
    return out


def qpub(q):
    y, n = int(q[:4]), int(q[-1])
    return {1: "%d-05-15" % y, 2: "%d-08-14" % y, 3: "%d-11-14" % y, 4: "%d-03-31" % (y + 1)}[n]


def step(p):
    """整數關卡間距：10、50、100、500…（股價 25 → 5、180 → 50、475 → 50、1690 → 500）"""
    e = 10 ** math.floor(math.log10(p))
    return e / 2 if p < e * 5 else e


MODE = "dual"  # 外資、融資雙賣的題材股剔除（權值股可以）；回測用：old／big50／big100
data_rank = {}


def big(s, t, rank, n):
    """是不是權值股：市值（股本 × 股價）排名前 n"""
    return rank.get(s["id"], 9999) <= n


def set_rank(data, t):
    L = sorted(((float(x["shares"]) * x["c"][t], x["id"]) for x in data["stocks"]
                if not x["id"].startswith("00") and x.get("shares") and x["c"][t]), reverse=True)
    data_rank.clear()
    data_rank.update({sid: i + 1 for i, (_, sid) in enumerate(L)})


def pick(s, t, D, m):
    """大跌那天是否入選；回傳 (入選, 排序分數, 說明) """
    c, v = s["c"], s["v"]
    if s["id"].startswith("00") or t < 70 or not c[t] or not c[t - 6]:
        return False, 0, ""
    if sum(v[t - 20:t]) / 20 < 500 or r5(c, t) > DROP:
        return False, 0, ""
    if c[t - 6] <= sum(c[t - 65:t - 5]) / 60:  # 大跌前不在季線上
        return False, 0, ""
    ok, _ = fin_health.check(s, D[t])
    q = [x for x in (s.get("q") or []) if qpub(x["q"]) <= D[t]]
    if ok is not True or len(q) < 4 or sum(x["eps"] for x in q[-4:]) <= 0:
        return False, 0, ""
    fi5 = sum(s["fi"][i] or 0 for i in range(t - 4, t + 1))
    it5 = sum(s["it"][i] or 0 for i in range(t - 4, t + 1))
    mg = s.get("mg") or []
    mg_up = len(mg) > t and mg[t] and mg[t - 5] and mg[t] > mg[t - 5]
    mg_dn = len(mg) > t and mg[t] and mg[t - 5] and mg[t] < mg[t - 5]
    if MODE == "old" and fi5 < 0 and mg_up:
        return False, 0, ""
    if MODE in ("dual", "big50", "big100") and fi5 < 0 and mg_dn and not big(s, t, data_rank, 50):  # 外資、融資雙賣的題材股：斷捨離（權值股可以）
        return False, 0, ""
    if MODE == "big50" and not big(s, t, data_rank, 50):
        return False, 0, ""
    if MODE == "big100" and not big(s, t, data_rank, 100):
        return False, 0, ""
    score = (200 if big(s, t, data_rank, 50) else 0) + (1 if fi5 + it5 >= 0 else 0) * 100 - r5(c, t) * 100  # 權值股（市值前 50）排最前面：回測抱 60 天勝率 87%、最差 −15%
    return True, score, "%s5 日 %+.1f%%（大盤 %+.1f%%），法人 5 日 %s 張" % ("權值股・" if big(s, t, data_rank, 50) else "", r5(c, t) * 100, r5(m, t) * 100, "{:+,}".format(fi5 + it5))


def signals(s, t0, t):
    """大跌事件 t0 之後第 t 天的三批訊號：回傳 {1: 說明, 2: 說明, 3: 說明}（當天成立的）"""
    c, o, v = s["c"], s["o"], s["v"]
    out = {}
    pre = c[t0 - 6]  # 大跌前的收盤
    st = step(c[t])
    lv = math.ceil(c[t] / st) * st  # 現價上面最近的整數關卡（例如 727 → 800、4480 → 4500）
    if lv > pre:  # 大跌前就在這個關卡下面，不算「跌破」
        lv = None
    lo20 = min(c[t - 20:t])
    r_now, r_lo = exits.rsi(c, t), exits.rsi(c, c.index(lo20, t - 20, t))
    div = c[t] <= lo20 and r_now > r_lo + 2
    hook = exits.rsi(c, t - 1) < 30 and r_now > exits.rsi(c, t - 1)
    if lv and c[t] < lv and (div or hook):
        out[1] = "跌破整數關卡 %s＋%s（RSI %.0f）" % (exits.px(lv), "超賣背離" if div else "超賣往上勾", r_now)
    m5, m5p = exits.ma(c, 5, t), exits.ma(c, 5, t - 1)
    mg = s.get("mg") or []
    if c[t] > m5 and c[t - 1] > m5p and len(mg) > t and mg[t] and mg[t0 - 5] and mg[t] <= mg[t0 - 5] * 0.9:
        out[2] = "站穩 5 日線 %s＋融資比大跌前少 %.0f%%" % (exits.px(m5), (1 - mg[t] / mg[t0 - 5]) * 100)
    m20 = exits.ma(c, 20, t)
    av = sum(v[t - 20:t]) / 20
    if c[t] > m20 and c[t - 1] <= exits.ma(c, 20, t - 1) and v[t] >= av * 1.5 and o[t] and c[t] / o[t] - 1 >= 0.03:
        out[3] = "帶量長紅突破月線 %s（量 %.1f 倍、紅 K %+.1f%%）" % (exits.px(m20), v[t] / av, (c[t] / o[t] - 1) * 100)
    return out


def kd(s, t, n=9):
    """日 KD（9 日）：回傳 [(K, D)]，到 t 為止"""
    c, h, l = s["c"], s["h"], s["l"]
    K = Dv = 50.0
    out = []
    for i in range(max(n, t - 60), t + 1):
        hi, lo = max(h[i - n + 1:i + 1]), min(l[i - n + 1:i + 1])
        rsv = (c[i] - lo) / (hi - lo) * 100 if hi > lo else 50
        K = K * 2 / 3 + rsv / 3
        Dv = Dv * 2 / 3 + K / 3
        out.append((K, Dv))
    return out


def market_bottom(data, t, t0):
    """大盤落地指標（使用者定的止跌訊號）：回傳 [(名稱, 成立, 說明)]
    籌碼：全部股票融資餘額連 3 天減少、5 日減 3% 以上；量價：0050 近 3 日有爆量長下影線、最低點後 3 天不破底；
    技術：0050 日 KD 低檔（K<30）黃金交叉、RSI 低檔（RSI12<40）RSI6 上穿 RSI12（近 3 日）；權值：台積電、聯發科連 2 天站上 5 日線"""
    by = {x["id"]: x for x in data["stocks"]}
    e = by["0050"]
    c, o, h, l, v = e["c"], e["o"], e["h"], e["l"], e["v"]
    out = []
    mg = [sum((x.get("mg") or [0] * (t + 1))[i] or 0 for x in data["stocks"] if not x["id"].startswith("00")) for i in range(t - 6, t + 1)]
    dn3 = all(mg[i] < mg[i - 1] for i in range(4, 7))
    chg5 = mg[-1] / mg[1] - 1 if mg[1] else 0
    out.append(("融資連續大減", dn3 and chg5 <= -0.03, "全市場融資 5 日 %+.1f%%%s" % (chg5 * 100, "、連 3 天減少" if dn3 else "")))
    av = sum(v[t - 23:t - 3]) / 20
    hit = ""
    for i in range(t - 2, t + 1):
        body, lower = abs(c[i] - o[i]), min(o[i], c[i]) - l[i]
        if v[i] >= av * 1.5 and lower >= max(body * 2, c[i] * 0.015):
            hit = "%s 量 %.1f 倍、下影線 %.1f%%" % (data["dates"][i][5:], v[i] / av, lower / c[i] * 100)
    out.append(("爆量長下影線", bool(hit), hit or "近 3 日沒有"))
    lo_i = min(range(t0 - 5, t + 1), key=lambda i: l[i])
    out.append(("3 天不破底", t - lo_i >= 3, "最低 %s（%s），之後 %d 天沒破" % (exits.px(l[lo_i]), data["dates"][lo_i][5:], t - lo_i)))
    K = kd(e, t)
    kx = any(K[i][0] > K[i][1] and K[i - 1][0] <= K[i - 1][1] and K[i - 1][0] < 30 for i in range(len(K) - 3, len(K)))
    r6 = [exits.rsi(c, i, 6) for i in range(t - 3, t + 1)]
    r12 = [exits.rsi(c, i, 12) for i in range(t - 3, t + 1)]
    rx = any(r6[i] > r12[i] and r6[i - 1] <= r12[i - 1] and r12[i - 1] < 40 for i in range(1, 4))
    out.append(("KD／RSI 低檔金叉", kx and rx, "KD %s、RSI %s（K %.0f、RSI12 %.0f）" % ("金叉" if kx else "未金叉", "金叉" if rx else "未金叉", K[-1][0], r12[-1])))
    st = []
    for sid in ("2330", "2454"):
        x = by.get(sid)
        ok = x and all(x["c"][i] > exits.ma(x["c"], 5, i) for i in (t - 1, t))
        st.append(("台積電" if sid == "2330" else "聯發科") + ("站穩" if ok else "未站穩"))
    out.append(("權值股先站穩", all("未" not in z for z in st), "、".join(st) + " 5 日線"))
    return out


def plan(s, t0, upto):
    """模擬 3-3-4：嚴格依序等第 1、2、3 批訊號（沒有第 1 批就不買）；跌破事件低點 −5% 停止加碼。
    回傳 [(批次, 日期索引, 價格)]"""
    c, o = s["c"], s["o"]
    got, low = [], min(c[t0 - 5:t0 + 1])
    for t in range(t0, min(upto, t0 + WINDOW) + 1):
        low = min(low, c[t])
        if got and c[t] < low * 0.95:
            break
        sg = signals(s, t0, t)
        n = len(got) + 1
        if n == 1 and 1 in sg:  # 使用者規定：一定要先出現「破整數關卡＋超賣背離」才開始買
            got.append((1, t, c[t]))
        elif n == 2 and 2 in sg:
            got.append((2, t, c[t]))
        elif n == 3 and 3 in sg:
            got.append((3, t, c[t]))
        if len(got) == 3:
            break
    return got


def regime():
    """系統性衰退警訊（crash_hist.py 用 1997～2026 年 80 次台股大跌研究）：
    美股（標普 500）跌破 200 日線、而且近一年美債殖利率曲線（10 年 − 3 個月）倒掛過 → 17 次有 14 次撿了會套（82%），120 天平均 −4.6%
    （2000～2001 網路泡沫、2007～2008 金融海嘯都是）；其他 63 次只有 48%、平均 +3.7%；兩個都沒事 26 次只套 9 次（35%）
    回傳 (警訊 True/False/None＝抓不到, 說明)"""
    import requests
    UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/124 Safari/537.36"}

    def get(sym):
        for host in ("query1", "query2"):
            try:
                r = requests.get("https://%s.finance.yahoo.com/v8/finance/chart/%s?range=2y&interval=1d" % (host, sym), headers=UA, timeout=20)
                r.raise_for_status()
                res = r.json()["chart"]["result"][0]
                return {ts: c for ts, c in zip(res["timestamp"], res["indicators"]["quote"][0]["close"]) if c}
            except Exception:
                continue
        return {}
    spx, tnx, irx = get("%5EGSPC"), get("%5ETNX"), get("%5EIRX")
    if len(spx) < 200 or not tnx or not irx:
        return None, "美股／美債資料抓不到，請自己判斷是不是系統性衰退"
    c = [spx[k] for k in sorted(spx)]
    m200 = sum(c[-200:]) / 200
    below = c[-1] < m200
    ks = sorted(set(tnx) & set(irx))[-250:]
    curve = min(tnx[k] - irx[k] for k in ks) if ks else None
    inv = curve is not None and curve < 0
    why = "美股 %s 200 日線（%.0f／%.0f）、近一年美債殖利率曲線%s（最低 %+.2f）" % ("跌破" if below else "還在", c[-1], m200, "倒掛過" if inv else "沒倒掛", curve or 0)
    return below and inv, why


# 國安基金護盤股（rescue_study.py：2000～2026 年 10 次護盤、22 檔曾被買的股票，進場日買、抱 120 天比加權指數多賺）
# 台達電 +31%（9 次贏 7 次）、鴻海 +9%、台積電 +7%（250 天 +19%）、廣達 +5%（250 天 +33%）；金融股大多輸大盤，不列
RESCUE_PICKS = [("2308", "台達電", "+31%"), ("2317", "鴻海", "+9%"), ("2330", "台積電", "+7%"), ("2382", "廣達", "+5%"), ("2454", "聯發科", "+2%，250 天 +22%")]


def rescue_text(data, t):
    """大跌時列出國安基金最常買、護盤後表現最好的幾檔現況"""
    by = {x["id"]: x for x in data["stocks"]}
    out = []
    for sid, nm, ex in RESCUE_PICKS:
        x = by.get(sid)
        if not x or not x["c"][t]:
            continue
        c = x["c"]
        dd = c[t] / max(c[max(0, t - 250):t + 1]) - 1
        sg = dip_signal(x, t) if t >= 21 else ""
        out.append("%s %s（%s，離一年高點 %+.0f%%%s）" % (nm, exits.px(c[t]), "護盤後 120 天比大盤多賺 " + ex, dd * 100, "，🟢 " + sg if sg else ""))
    return "🛡️ 國安基金護盤股（歷次都買、護盤後漲最多）：" + "；".join(out) if out else ""


def nightly(data, reg=None):
    """有大跌事件（30 個交易日內）時回傳報告段落，沒有回傳空字串"""
    D, S = data["dates"], data["stocks"]
    m = next((x["c"] for x in S if x["id"] == "0050"), None)
    if not m:
        return ""
    t = len(D) - 1
    ev = [e for e in events(D, m) if t - e <= WINDOW]
    if not ev:
        return ""
    t0 = ev[-1]
    set_rank(data, t0)
    cand = []
    for s in S:  # 大跌開始後 5 個交易日內任何一天符合都算（連續大跌時後面才跌深的也抓得到）
        for u in range(min(t, t0 + 5), t0 - 1, -1):
            ok, sc, why = pick(s, u, D, m)
            if ok:
                cand.append((sc, s, why))
                break
    cand.sort(key=lambda x: -x[0])
    L = ["🛒 大跌撿好股（3-3-4 分批）：%s 0050 五日 %+.1f%%，第 %d 個交易日" % (D[t0], r5(m, t0) * 100, t - t0 + 1),
         "挑財報健檢過、大跌前在季線上、跌 10%% 以上的好股票（共 %d 檔，列前 %d）；第 1 批 30%%（破整數關卡＋超賣背離）→ 第 2 批 30%%（站穩 5 日線＋融資大退）→ 第 3 批 40%%（帶量長紅突破月線）" % (len(cand), min(TOP, len(cand)))]
    warn, rwhy = reg if reg is not None else regime()
    if warn:
        L.append("⚠️ 系統性衰退警訊：%s。歷史上這種情況大跌後撿了 8 成會再套（2000 網路泡沫、2008 金融海嘯），這波先不撿，名單只列出來觀察" % rwhy)
    else:
        L.append("✅ 判斷是暫時性大跌：%s（歷史上這種情況撿了大多會漲回來）" % rwhy if warn is False else "❔ " + rwhy)
    rt = rescue_text(data, t)
    if rt:
        L.append(rt)
    mb = market_bottom(data, t, t0)
    n = sum(x[1] for x in mb)
    L.append("大盤落地指標 %d／5：%s" % (n, "；".join(("✅" if ok else "⬜") + name + "（" + why + "）" for name, ok, why in mb)))
    L.append("→ " + ("3 個以上止跌訊號，可以照 3-3-4 分批進場" if n >= 3 else "止跌訊號還不夠，不要盲目摸底；中長線可以先小量（第 1 批），短線先等") + "；不開槓桿（不用融資、不用期貨）")
    for sc, s, why in cand[:TOP]:
        got = plan(s, t0, t)
        sg = signals(s, t0, t)
        done = "已到第 %d 批" % len(got) if got else "還沒有買訊"
        today = "；今天：" + "、".join("第 %d 批 %s" % (k, v) for k, v in sorted(sg.items())) if sg else ""
        nxt = ["等破整數關卡＋超賣背離", "等站穩 5 日線＋融資大退", "等帶量長紅突破月線", "三批都到了"][len(got)]
        if warn:
            done, nxt, today = "系統性衰退警訊", "先不買，只觀察", ""
        L.append("・%s %s %s｜%s｜%s，下一步：%s%s" % (s["id"], s["name"], exits.px(s["c"][t]), why, done, nxt, today))
    L.append("跌破這波最低價再低 5% 就不再加碼（汰弱留強）；每檔停損買進前跟你討論。")
    return "\n".join(L)


def grows(s, day):
    """近 4 季 EPS 合計 > 0，而且不比一年前少（還在賺、還在成長）"""
    q = [x for x in (s.get("q") or []) if qpub(x["q"]) <= day]
    if len(q) < 8:
        return False
    e4, e8 = [x["eps"] for x in q[-4:]], [x["eps"] for x in q[-8:-4]]
    return all(x is not None for x in e4 + e8) and sum(e4) > 0 and sum(e4) >= sum(e8)


def dip_signal(s, t):
    """個股的第 1 批訊號：近 10 天跌破現價上面最近的整數關卡＋超賣背離（或 RSI<30 往上勾）"""
    c = s["c"]
    r0, r1 = exits.rsi(c, t), exits.rsi(c, t - 1)
    hook = r1 < 30 and r0 > r1
    lo20 = min(c[t - 20:t])
    div = c[t] <= lo20 and r0 > exits.rsi(c, c.index(lo20, t - 20, t)) + 2
    st = step(c[t])
    lv = math.ceil(c[t] / st) * st
    broke = c[t] < lv and any(c[i] > lv for i in range(t - 10, t))
    return ("跌破整數關卡 %s＋%s（RSI %.0f）" % (exits.px(lv), "超賣背離" if div else "超賣往上勾", r0)) if broke and (div or hook) else ""


def dip_nightly(data, reg=None, look=3):
    """好公司跌深抄底（使用者 2026-11-10 要的台股版；不用等大盤大跌，個股跌深就看）
    好公司：近 4 季 EPS>0 且比一年前多、財報健檢通過、均量 ≥500 張；跌深：比近一年高點跌 25% 以上
    買點：使用者的第 1 批（破整數關卡＋超賣背離）。回測（2026-03～11）：抱 60 天勝率 83%、平均 +31%、最差 −8%；
    跌深 25% 每天買 82%／+29%／最差 −28%；隨便買 63%／+23%／最差 −60%。系統性衰退警訊時只列不買"""
    D, S = data["dates"], data["stocks"]
    t = len(D) - 1
    if t < 260:
        return ""
    warn, rwhy = reg if reg is not None else regime()
    set_rank(data, t)
    hits, watch = [], []
    for s in S:
        c, v = s["c"], s["v"]
        if s["id"].startswith("00") or not c[t] or sum(v[t - 20:t]) / 20 < 500:
            continue
        dd = c[t] / max(c[t - 250:t + 1]) - 1
        if dd > -0.25 or not grows(s, D[t]) or fin_health.check(s, D[t])[0] is not True:
            continue
        sig = next(((u, w) for u in range(t, t - look, -1) for w in [dip_signal(s, u)] if w), None)
        inst = sum((s["fi"][i] or 0) + (s["it"][i] or 0) for i in range(t - 4, t + 1))
        bg = big(s, t, data_rank, 50)
        # 排序：權值股（市值前 50）→ 法人 5 日買超 → 跌得深
        key = (0 if bg else 1, 0 if inst > 0 else 1, dd)
        (hits if sig else watch).append((key, s, sig, dd, inst, bg))
    if not hits and not watch:
        return ""
    L = ["🪝 好公司跌深抄底（比一年高點跌 25%% 以上、還在賺錢成長、財報健檢過）：%d 檔有第 1 批買訊、%d 檔觀察中" % (len(hits), len(watch))]
    if warn:
        L.append("⚠️ 系統性衰退警訊（%s）：先不撿，只觀察" % rwhy)
    tag = lambda bg, inst: ("權值股・" if bg else "") + "法人 5 日 %s 張" % "{:+,}".format(inst)
    for _, s, (u, w), dd, inst, bg in sorted(hits, key=lambda x: x[0])[:8]:
        L.append("・🟢 %s %s %s｜離一年高點 %+.0f%%｜%s｜%s %s%s" % (s["id"], s["name"], exits.px(s["c"][t]), dd * 100, tag(bg, inst), D[u][5:], w,
                                                            "（先不買）" if warn else "，可以買第 1 批 30%"))
    for _, s, _, dd, inst, bg in sorted(watch, key=lambda x: x[0])[:6]:
        L.append("・⚪ %s %s %s｜離一年高點 %+.0f%%｜%s｜等破整數關卡＋超賣背離" % (s["id"], s["name"], exits.px(s["c"][t]), dd * 100, tag(bg, inst)))
    L.append("排序：權值股（市值前 50）→ 法人買超 → 跌得深；只列前 8 檔買訊、6 檔觀察")
    L.append("第 2 批等站穩 5 日線＋融資大退、第 3 批等帶量長紅突破月線；回測第 1 批抱 60 天勝率 83%、平均 +31%、最差 −8%（隨便買 63%、+23%）；每檔停損買進前跟你討論。")
    return "\n".join(L)


def backtest(data, holds=(20, 60)):
    D, S = data["dates"], data["stocks"]
    m = next(x["c"] for x in S if x["id"] == "0050")
    res = {}
    for t0 in events(D, m):
        set_rank(data, t0)
        for s in S:
            ok, sc, _ = pick(s, t0, D, m)
            if not ok:
                continue
            c, o = s["c"], s["o"]
            for H in holds:
                end = t0 + 1 + H
                if end >= len(D) or not c[end]:
                    continue
                lump = c[end] / (o[t0 + 1] or c[t0]) - 1 - 0.006
                res.setdefault(("一次買（隔天開盤）", H), []).append((lump, D[t0]))
                got = plan(s, t0, end)
                if got:
                    w = sum(LOTS[i] for i in range(len(got)))
                    avg = sum(LOTS[b - 1] * p for b, _, p in got) / w
                    res.setdefault(("3-3-4 分批（買到的部分）", H), []).append((c[end] / avg - 1 - 0.006, D[t0]))
                    res.setdefault(("3-3-4 平均買到幾成", H), []).append((w, D[t0]))
    return res


def main():
    path = next((a for a in sys.argv[1:] if not a.startswith("--")), os.path.join(DIR, "data.json"))
    data = json.load(open(path, encoding="utf-8"))
    if "--bt" in sys.argv:
        for (k, H), L in sorted(backtest(data).items(), key=lambda x: (x[0][1], x[0][0])):
            v = [x[0] for x in L]
            if "幾成" in k:
                print("抱 %d 天｜%s：%.0f%%" % (H, k, sum(v) / len(v) * 100))
            else:
                print("抱 %d 天｜%s：%d 筆 勝率 %.0f%% 平均 %+.1f%% 最差 %+.0f%%" % (
                    H, k, len(v), 100 * sum(x > 0 for x in v) / len(v), 100 * sum(v) / len(v), 100 * min(v)))
        return
    print(nightly(data) or "最近 %d 個交易日沒有大跌事件" % WINDOW)


if __name__ == "__main__":
    main()
