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


# 國安基金進場日（有新的護盤要加進來）。rescue_study.path_study（2000～2025 年 9 次，加權指數收盤）：
# 前 20 天從進場前低點平均彈 13%（中位 12%）、最高點平均在第 13 天；之後平均回跌 13%，5 次跌破進場前低點（第二隻腳）；
# 120 天內最低點只有 3 次在進場 5 天內、6 次在 20 天以後。2000-10、2008-09（系統性衰退）回跌 27%、34%
RESCUE_DATES = ["2026-11-09"]


def rescue_phase(data, t):
    """國安基金進場後 20 個交易日內：現在在「先彈→回跌→再起」的哪一段、離賣點買點多遠；到回跌買點時列出該買的護盤股
    價位用 0050 算（加權指數的替身）。高點區＝從低點彈 13% 以上或站上 10 日線；回跌買點＝從這波高點回跌 6%（錢線奎國老師的 15%／6% 說法，
    回測順利的 4 次回跌 0～5%、不順的 5 次 13～34%，所以只買第 2 批、留錢）；跌破低點＝第二隻腳"""
    D = data["dates"]
    by = {x["id"]: x for x in data["stocks"]}
    m = (by.get("0050") or {}).get("c")
    ev = [d for d in RESCUE_DATES if d <= D[t]]
    if not m or not ev:
        return ""
    i = next((k for k, d in enumerate(D) if d >= ev[-1]), None)
    if i is None or t - i > 20 or i < 10:
        return ""
    j0 = min(range(i - 10, i + 1), key=lambda k: m[k] or 9e9)  # 進場前 10 天（含進場日）的最低收盤
    lo = m[j0]
    pk = max(m[j0:t + 1])
    b, dn = (m[t] / lo - 1) * 100, (m[t] / pk - 1) * 100
    ma10 = sum(m[t - 9:t + 1]) / 10
    hx = (by.get("0050") or {}).get("h") or []
    eh = hx[i] if len(hx) > i and hx[i] else None  # 國安基金進場那天的盤中高點（錢線 11/11：長線一定會過，拉回到這裡就是買點）
    above = eh is not None and any(m[u] and m[u] > eh * 1.02 for u in range(i + 1, t + 1))
    # 買點＝「拉回到進場日高點」和「從高點回跌 6%」哪個先到（回測 9 次：先到的就買，120 天平均 +9.7%；只等回跌 6% 只買到 3 次、+0.8%）
    buy = max(pk * 0.94, eh if above else 0)
    lvl = ("進場日高點 %s 或回跌 6%% 的 %s，哪個先到" % (exits.px(eh), exits.px(pk * 0.94))) if above else "回跌 6%% 的 %s" % exits.px(pk * 0.94)
    head = "⏳ 國安基金進場第 %d 個交易日｜0050 %s：從低點 %s 反彈 %+.1f%%、離這波高點 %+.1f%%、10 日線 %s" % (
        t - i + 1, exits.px(m[t]), exits.px(lo), b, dn, exits.px(ma10))
    hist = "（歷史 9 次：平均先彈 13%、第 13 天左右最高，再回跌；順利的 4 次只回 0～5%，其餘 5 次回 13% 以上並跌破低點）"
    picks = []
    for sid, nm, ex in RESCUE_PICKS:  # 回測護盤後 120 天比大盤多賺最多的排前面
        x = by.get(sid)
        if x and x["c"][t]:
            c = x["c"]
            d1 = (c[t] / max(c[j0:t + 1]) - 1) * 100
            picks.append("%s %s（離這波高點 %+.0f%%）" % (nm, exits.px(c[t]), d1))
    what = "、".join(picks)
    tbl = rescue_table(by, t, j0, i)
    if m[t] < lo:
        return head + "\n　🔴 已跌破進場前低點＝第二隻腳進行中：先不買，等大盤落地指標 3 項以上再分批（最後 40% 資金留給這裡）" + hist + tbl
    if m[t] <= buy:
        why = "拉回到國安基金進場日高點 %s" % exits.px(eh) if above and buy == eh and dn > -6 else "從高點回 6% 以上"
        return (head + "\n　🟢 回跌買點到了（%s、還沒破低點 %s）：可以買第 2 批 30%%，不要一次買滿，留 40%% 防跌破低點" % (why, exits.px(lo))
                + "\n　👉 買什麼（國安基金必買、護盤後漲最多的排前面）：" + what + hist + tbl)
    if b >= 13 or (m[t] >= ma10 and dn > -3):
        return (head + "\n　🟠 已到第一波高點區（彈 13%% 以上或站上 10 日線）：短線不追高、手上短線有賺的可以先收一些；回跌買點在 0050 %s，跌破 %s 是第二隻腳" % (
            lvl, exits.px(lo)) + hist + tbl)
    return (head + "\n　🟡 正在回跌或還沒彈夠：回跌買點在 0050 %s（離較近的 %s 還差 %.1f%%），到了再買第 2 批；跌破 %s 是第二隻腳" % (
        lvl, exits.px(buy), (m[t] / buy - 1) * 100, exits.px(lo)) + hist + tbl)


STOP_PCT = 0.15  # 護盤股、抄底（逆勢買）停損買進價 −15%＋分 3 批（使用者 2026-11-13 決定；回測抄底第 1 批：−8% 抱 60 天勝率 35%、+6.9%，−15% 48%、+7.8%，−20% 60%、+13.4%，跌深股常先再跌 8～15% 才反彈）


def tick(p):
    """價格調成台股的跳動單位（例如 1191.4 → 1190、232.32 → 232.5）"""
    u = 0.01 if p < 10 else 0.05 if p < 50 else 0.1 if p < 100 else 0.5 if p < 500 else 1 if p < 1000 else 5
    return exits.px(round(round(p / u) * u, 2))


def rescue_table(by, t, j0, i0=None):
    """護盤股買賣表（使用者 2026-11-12 要的）：每檔買進區、停損、目標、現在在哪
    買進區＝這檔自己這波高點回跌 4～8%（對應 0050 回跌 6%）；停損＝買進價 −15%（逆勢買，分 3 批）；
    目標 1＝月線（太近就用買進區上緣 +10%）、目標 2＝季線（太近就用目標 1 +8%）
    先站上月線（settle_bt.py 回測 9 次護盤、184 筆）：進場後 5 天內站上月線的抱 120 天比大盤多賺 +4.5%，
    10 天內都沒站上的 −5.6%、72% 輸大盤 → 🌙 排前面、⚠️ 落後的不買"""
    L = ["　📋 護盤股買賣表（買點要等 0050 回跌買點 🟢 才動手；停損買進價 −15%、分 3 批 30／30／40 買；🌙 先站上月線的排前面）："]
    rows = []
    for k, (sid, nm, ex) in enumerate(RESCUE_PICKS):
        x = by.get(sid)
        if not x or not x["c"][t]:
            continue
        c = x["c"]
        pk = max(v for v in c[j0:t + 1] if v)
        lo_, hi_ = pk * 0.92, pk * 0.96
        mid = (lo_ + hi_) / 2
        m20, m60 = sum(c[t - 19:t + 1]) / 20, sum(c[t - 59:t + 1]) / 60
        t1 = m20 if m20 > hi_ * 1.05 else hi_ * 1.10
        t2 = m60 if m60 > t1 * 1.03 else t1 * 1.08
        z = c[t]
        if z > hi_:
            now = "還要跌 %.0f%% 才到" % ((z / hi_ - 1) * 100)
        elif z >= lo_:
            now = "🟢 已在買進區"
        else:
            now = "⚠️ 跌破買進區，等止穩（大盤沒破低再買）"
        moon, rank = "", 1
        if i0 is not None:
            ma20 = lambda u: sum(c[u - 19:u + 1]) / 20
            day = next((u - i0 for u in range(i0, min(t, i0 + 10) + 1) if c[u] and c[u] > ma20(u)), None)
            if day is not None:
                moon, rank = "🌙 第 %d 天站上月線（比較強）" % (day + 1), 0
            elif t - i0 >= 10:
                moon, rank = "⚠️ 落後：10 天內沒站上月線（回測 72%% 輸大盤，不買）", 2
            else:
                moon = "還沒站上月線 %s（差 %.0f%%）" % (tick(m20), (m20 / z - 1) * 100)
        rows.append((rank, k, "　・%s %s｜%s買進 %s～%s｜停損 %s（−15%%）｜目標 %s → %s｜%s｜護盤後 120 天比大盤多賺 %s" % (
            nm, exits.px(z), moon + "｜" if moon else "", tick(lo_), tick(hi_), tick(mid * (1 - STOP_PCT)), tick(t1), tick(t2), now, ex)))
    L += [x[2] for x in sorted(rows)]
    L.append("　賣法：到目標 1 或連續長上影線先賣一半，剩下抱到目標 2；0050 跌破進場前低點、個股跌破停損、或新聞「國安基金退場」就出場。金融股護盤後大多輸大盤，不列。")
    return "\n" + "\n".join(L) if len(L) > 2 else ""


SETTLE_SHORT = 70000  # 外資台指期淨空單門檻（口）


def third_wed(y, m):
    import datetime as dt
    d = dt.date(y, m, 1)
    d += dt.timedelta(days=(2 - d.weekday()) % 7)
    return d + dt.timedelta(days=14)


def settle_line(day, net=None):
    """月結算提醒（使用者 2026-11-12 同意；settle_bt.py 回測 2018 年起 101 次結算）：
    外資台指期淨空單 7 萬口以上時，結算前 3 天大盤平均 −0.7%、3 天內最多跌 −1.7%（其他時候 −0.9%），結算後 5 天平均 +0.5～1.2%。
    效果不大、樣本少（7 萬口以上只有 4 次），所以只提醒、不改推薦。day＝資料日（YYYY-MM-DD）；net＝外資淨未平倉（負＝淨空單），None 就自己抓"""
    import datetime as dt
    d0 = dt.date.fromisoformat(day)
    s = third_wed(d0.year, d0.month)
    if s <= d0:
        y, m = (d0.year + (d0.month == 12), d0.month % 12 + 1)
        s = third_wed(y, m)
    left = sum(1 for k in range(1, (s - d0).days + 1) if (d0 + dt.timedelta(days=k)).weekday() < 5)  # 還有幾個交易日（不含國定假日）
    if left > 3:
        return ""
    if net is None:
        try:
            import fetch_finmind
            fetch_finmind.TOKEN = fetch_finmind.TOKEN or (os.environ.get("FINMIND_TOKEN") or "").strip()
            rows = fetch_finmind.get("TaiwanFuturesInstitutionalInvestors", "TX", (d0 - dt.timedelta(days=10)).isoformat(), wait=False)
            f = sorted((r for r in rows if r.get("institutional_investors") == "外資"), key=lambda r: r["date"])
            net = f[-1]["long_open_interest_balance_volume"] - f[-1]["short_open_interest_balance_volume"] if f else None
        except Exception:
            net = None
    if net is None or net > -SETTLE_SHORT:
        return ""
    return ("📅 月結算提醒：%s（週三）台指期結算，還剩 %d 個交易日；外資淨空單 %s 口（7 萬口以上）\n"
            "　回測 2018 年起：空單這麼多時，結算前 3 天大盤常被壓低約 1～2%%，結算後 5 天平均反彈 +0.5～1%%。想買的可以等結算後再買；只是參考，不影響推薦。") % (
        "%d/%d" % (s.month, s.day), left, "{:,}".format(-net))


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
    rp = rescue_phase(data, t)
    if rp:
        L.append(rp)
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
    L.append("跌破這波最低價再低 5% 就不再加碼（汰弱留強）；停損：買進價 −15%（逆勢買波動大，−8% 容易在反彈前被洗掉，所以分 3 批、每批少買）。")
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


MG_MAX = 5.0  # 融資餘額佔股本 5% 以上不撿（回測：抄底訊號裡最差的 −49% 都在這群；剔除後最差 −8%、抱 60 天勝率 80% → 85%）


def mg_ratio(s, t):
    """融資餘額佔股本（%）；融資限額約股本 25%，所以 5% ≈ 使用率 20%"""
    mg = s.get("mg") or []
    return 100.0 * mg[t] / float(s["shares"]) if len(mg) > t and mg[t] and s.get("shares") else 0


def vol_flush(s, t):
    """低檔爆量：離季線跌 20% 以上、當天量是 20 日均量 2 倍以上、收紅
    回測（2010 年起 281 筆）：抱 60 天勝率 73%、平均 +15.7%；暫時性大跌的年份（2015、2020、2025）勝率 80～98%，空頭年（2022）只有 38%"""
    c, o, v = s["c"], s["o"], s["v"]
    w = c[t - 59:t + 1]
    if t < 60 or not all(w) or not o[t]:
        return ""
    dev, av = c[t] / (sum(w) / 60) - 1, sum(v[t - 20:t]) / 20
    return "離季線 %+.0f%%、量 %.1f 倍收紅" % (dev * 100, v[t] / av) if dev <= -0.20 and av and v[t] >= 2 * av and c[t] > o[t] else ""


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
    hits, watch, skip_mg = [], [], 0
    for s in S:
        c, v = s["c"], s["v"]
        if s["id"].startswith("00") or not c[t] or sum(v[t - 20:t]) / 20 < 500:
            continue
        dd = c[t] / max(c[t - 250:t + 1]) - 1
        if dd > -0.25 or not grows(s, D[t]) or fin_health.check(s, D[t])[0] is not True:
            continue
        if mg_ratio(s, t) >= MG_MAX:  # 高融資股：一反彈融資就賣，不撿
            skip_mg += 1
            continue
        fl = "" if warn else next(("%s %s" % (D[u][5:], w) for u in range(t, t - look, -1) for w in [vol_flush(s, u)] if w), "")
        sig = next(((u, w) for u in range(t, t - look, -1) for w in [dip_signal(s, u)] if w), None)
        inst = sum((s["fi"][i] or 0) + (s["it"][i] or 0) for i in range(t - 4, t + 1))
        bg = big(s, t, data_rank, 50)
        # 排序：權值股（市值前 50）→ 法人 5 日買超 → 跌得深
        key = (0 if fl else 1, 0 if bg else 1, 0 if inst > 0 else 1, dd)
        (hits if sig else watch).append((key, s, sig, dd, inst, bg, fl))
    if not hits and not watch:
        return ""
    L = ["🪝 好公司跌深抄底（比一年高點跌 25%% 以上、還在賺錢成長、財報健檢過）：%d 檔有第 1 批買訊、%d 檔觀察中" % (len(hits), len(watch))]
    if warn:
        L.append("⚠️ 系統性衰退警訊（%s）：先不撿，只觀察" % rwhy)
    tag = lambda bg, inst: ("權值股・" if bg else "") + "法人 5 日 %s 張" % "{:+,}".format(inst)
    fire = lambda fl: "｜🔥 低檔爆量（%s）" % fl if fl else ""
    for _, s, (u, w), dd, inst, bg, fl in sorted(hits, key=lambda x: x[0])[:8]:
        L.append("・🟢 %s %s %s｜離一年高點 %+.0f%%｜%s｜%s %s%s%s" % (s["id"], s["name"], exits.px(s["c"][t]), dd * 100, tag(bg, inst), D[u][5:], w,
                                                              "（先不買）" if warn else "，可以買第 1 批 30%", fire(fl)))
    for _, s, _, dd, inst, bg, fl in sorted(watch, key=lambda x: x[0])[:6]:
        L.append("・⚪ %s %s %s｜離一年高點 %+.0f%%｜%s｜等破整數關卡＋超賣背離%s" % (s["id"], s["name"], exits.px(s["c"][t]), dd * 100, tag(bg, inst), fire(fl)))
    L.append("排序：🔥 低檔爆量 → 權值股（市值前 50）→ 法人買超 → 跌得深；只列前 8 檔買訊、6 檔觀察%s" % ("；另有 %d 檔融資佔股本 %g%% 以上，不撿" % (skip_mg, MG_MAX) if skip_mg else ""))
    if any(x[-1] for x in hits + watch):
        L.append("🔥 低檔爆量＝離季線跌 20% 以上、量 2 倍以上收紅：2010 年起回測抱 60 天勝率 73%、平均 +15.7%（空頭年只有 38%，所以衰退警訊亮時不標）；最差一筆 −56%，一定要設停損。")
    L.append("第 2 批等站穩 5 日線＋融資大退、第 3 批等帶量長紅突破月線；回測第 1 批抱 60 天勝率 83%、平均 +31%（隨便買 63%、+23%）；停損：買進價 −15%（−8% 會在反彈前被洗掉：勝率剩 35%），所以分 3 批、每批少買。")
    return "\n".join(L)


def intraday_levels(data, reg=None):
    """給盤中提醒用的 0050 價位（每晚算好存進 sop_plan.json 的 levels，2026-11-13 使用者要的）：
    年線（正2 出場線）、正2 能不能買、國安基金進場後的回跌買點和第二隻腳低點"""
    D = data["dates"]
    by = {x["id"]: x for x in data["stocks"]}
    x = by.get("0050")
    if not x:
        return {}
    c = x["c"]
    t = len(D) - 1
    cc = [v for v in c if v]
    adj = [cc[0]]
    for i in range(1, len(cc)):
        r = cc[i] / cc[i - 1] - 1
        adj.append(adj[-1] * (1 + (0 if abs(r) > 0.25 else r)))
    out = {"date": D[t], "close": c[t]}
    if len(adj) >= 241:
        out["yline"] = round(sum(adj[-240:]) / 240 * cc[-1] / adj[-1], 2)
        out["lev_ok"] = bool(not (reg and reg[0]) and c[t] >= out["yline"])
    ev = [d for d in RESCUE_DATES if d <= D[t]]
    i = next((k for k, d in enumerate(D) if ev and d >= ev[-1]), None)
    if i is not None and 10 <= i and t - i <= 20:
        j0 = min(range(i - 10, i + 1), key=lambda k: c[k] or 9e9)
        lo, pk = c[j0], max(c[j0:t + 1])
        hx = x.get("h") or []
        eh = hx[i] if len(hx) > i and hx[i] else None
        above = eh is not None and any(c[u] and c[u] > eh * 1.02 for u in range(i + 1, t + 1))
        out["rescue"] = {"buy": round(max(pk * 0.94, eh if above else 0), 2), "eh": eh if above else None, "dn6": round(pk * 0.94, 2),
                         "lo": lo, "day": t - i + 1}
    return out


def lev_line(data, reg=None):
    """0050 正2（00631L）能不能買（2026-11-11 使用者要的；lev_bt.py 回測 2010 年起）
    回測：0050 在年線上才抱正2 年化 +18.7%、最大跌幅 −38%（一直抱正2 +27.9%／−55%、一直抱 0050 +15.8%／−34%）；
    大跌隔天就買比等回跌、等站回均線好（抱 60 天勝率 76%、平均 +15.9%）。
    反1（00632R）怎麼抱都賠（一直抱年化 −17.6%、年線下才抱 −7.3%、衰退警訊亮才抱 −2.1%），所以只提醒不要買"""
    S = data["stocks"]
    x = next((s for s in S if s["id"] == "0050"), None)
    if not x:
        return ""
    c = [v for v in x["c"] if v]
    adj = [c[0]]  # 分割（例如 2025-06 一拆四）接成連續價格
    for i in range(1, len(c)):
        r = c[i] / c[i - 1] - 1
        adj.append(adj[-1] * (1 + (0 if abs(r) > 0.25 else r)))
    if len(adj) < 241:
        return ""
    k = c[-1] / adj[-1]
    y = sum(adj[-240:]) / 240 * k
    q = sum(adj[-60:]) / 60 * k
    gap = (c[-1] / y - 1) * 100
    warn = reg[0] if reg else None
    big = r5(adj, len(adj) - 1) <= TRIG or any(r5(adj, len(adj) - 1 - i) <= TRIG for i in range(1, 3))
    if warn:
        head = "🔴 0050 正2：系統性衰退警訊亮，不買；手上有的出場"
    elif c[-1] < y:
        head = "🔴 0050 正2：0050 收盤 %s 跌破年線 %s，不買；手上有的出場（站回年線再說）" % (exits.px(c[-1]), exits.px(y))
    else:
        head = "🟢 0050 正2：可以分批買（衰退警訊沒亮、0050 %s 在年線 %s 之上 %+.0f%%%s）" % (
            exits.px(c[-1]), exits.px(y), gap, "；近 3 天剛大跌，回測大跌隔天買抱 60 天勝率 76%" if big else "")
    L = ["📊 " + head]
    if not warn and c[-1] >= y:
        L.append("　做法：分 3 筆、每 1～2 週買一筆（或大盤單日跌 2%% 以上那天買一筆）；金額要能接受中途先賠 3～4 成；0050 收盤跌破年線 %s 就出場%s" % (
            exits.px(y), "；離年線只剩 %.0f%%，要特別小心" % gap if gap < 5 else ""))
    L.append("　0050 反1：不建議。回測 2010 年起怎麼抱都賠（年線下才抱年化 −7%、跌破年線就買抱 60 天勝率 15%），台股長期往上，反1 每天還會耗損")
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
