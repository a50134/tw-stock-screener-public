"""
deepdive.py - 個股深入分析（查個股加 --deep 時附在後面）

給「想買某一檔」時用，重點是：在哪個價位、哪個時間下單比較不容易賠錢
1. 財報趨勢：近 8 季 EPS、毛利率、營益率，月營收近 12 個月年增率
2. 大事件反應：這檔股票過去遇到美國大選、台灣大選、日圓套利平倉、DeepSeek、關稅、黃仁勳台北演講…
   當天、5 天、20 天的漲跌（跟大盤比）
3. 下單價位：用近 10 年真實紀錄算「掛低 0／3／5／8／10% 的預約單」成交機率、成交後 60 天賺錢機率、最深套多少
   另外用 1 萬次模擬（把 10 年的真實走勢切成 20 天一段隨機接起來）看 120 天後的結果分布
   只看「跟現在位置相似」的日子（股價相對季線的位置），比較貼近現在
4. 下單時間：近 60 天 5 分 K，每天最低點、最高點出現在哪個時段；開盤後平均回落多少（智慧單掛價參考）
5. 適合你的做法：依你的看盤時間（9 點前、午休、下班後）、常用預約單／智慧單、不太想停損，給具體掛單方式

資料：Yahoo Finance（日K 11 年、5 分 K 60 天）＋ FinMind（財報、營收，查個股已經抓好的）
只發 Discord 與私人專案，不印代號到公開紀錄
"""
import datetime as dt
import math
import random
import time

import requests

UA = {"User-Agent": "Mozilla/5.0"}

# 過去的大事件（台股反應的第一個交易日在這天或之後）
EVENTS = [
    ("2016-11-09", "美國大選（川普第一次當選）"),
    ("2018-11-26", "台灣九合一選舉"),
    ("2020-03-09", "新冠疫情股災"),
    ("2020-11-04", "美國大選（拜登當選）"),
    ("2022-11-28", "台灣九合一選舉"),
    ("2024-01-15", "台灣總統大選"),
    ("2024-06-03", "黃仁勳台北 Computex 演講"),
    ("2024-08-05", "日圓套利平倉大跌"),
    ("2024-11-06", "美國大選（川普第二次當選）"),
    ("2025-02-03", "DeepSeek 衝擊（台股年後開盤）"),
    ("2025-04-07", "川普對等關稅大跌"),
    ("2025-05-19", "黃仁勳台北 Computex 演講"),
    ("2025-07-28", "台灣大罷免投票"),
]
DISCOUNTS = (0, 3, 5, 8, 10)  # 預約單掛低幾 %
WAIT = 10    # 預約單最多等幾個交易日
HOLD = 60    # 成交後看幾天
SIMS = 10000
SIM_DAYS = 120
BLOCK = 20


def chart(sym, rng, interval):
    for k, host in enumerate(("query1", "query2", "query1")):
        try:
            r = requests.get("https://%s.finance.yahoo.com/v8/finance/chart/%s?range=%s&interval=%s&includeAdjustedClose=true"
                             % (host, sym, rng, interval), headers=UA, timeout=30)
            r.raise_for_status()
            res = r.json()["chart"]["result"][0]
            if res.get("timestamp"):
                return res
        except Exception:
            time.sleep(1 + 2 * k)
    return None


def daily(sym, years=11):
    """(日期, 開, 高, 低, 收) 還原權值"""
    res = chart(sym, "%dy" % years, "1d")
    if not res:
        return []
    q = res["indicators"]["quote"][0]
    adj = (res["indicators"].get("adjclose") or [{}])[0].get("adjclose") or q["close"]
    out = []
    for i, ts in enumerate(res["timestamp"]):
        c = q["close"][i]
        if not c or not adj[i] or None in (q["open"][i], q["high"][i], q["low"][i]):
            continue
        f = adj[i] / c
        out.append((dt.datetime.utcfromtimestamp(ts + 8 * 3600).strftime("%Y-%m-%d"), q["open"][i] * f, q["high"][i] * f, q["low"][i] * f, adj[i]))
    return out


def intraday(sym):
    """近 60 天 5 分 K：{日期: [(HH:MM, 高, 低, 開), ...]}"""
    res = chart(sym, "60d", "5m")
    if not res:
        return {}
    q = res["indicators"]["quote"][0]
    by = {}
    for i, ts in enumerate(res["timestamp"]):
        if None in (q["high"][i], q["low"][i], q["open"][i]):
            continue
        t = dt.datetime.utcfromtimestamp(ts + 8 * 3600)
        if not ("09:00" <= t.strftime("%H:%M") <= "13:30"):
            continue
        by.setdefault(t.strftime("%Y-%m-%d"), []).append((t.strftime("%H:%M"), q["high"][i], q["low"][i], q["open"][i]))
    return by


def symbol(sid, mkt=None):
    order = (".TWO", ".TW") if mkt == "tpex" else (".TW", ".TWO")
    for suf in order:
        D = daily(sid + suf, 1)
        if len(D) > 100:
            return sid + suf
    return None


def pct(x):
    return "%+.1f%%" % (x * 100)


def ma(c, t, n):
    return sum(c[t - n + 1:t + 1]) / n if t >= n - 1 else None


# ---------- 1. 財報趨勢 ----------
def fundamentals(s):
    L = []
    q = [x for x in (s.get("q") or []) if x.get("eps") is not None][-8:]
    if q:
        L.append("　近 %d 季 EPS：%s" % (len(q), "、".join("%s %.2f" % (x["q"][2:], x["eps"]) for x in q)))
        gm = [x["gm"] for x in q if x.get("gm") is not None]
        om = [x["om"] for x in q if x.get("om") is not None]
        if len(gm) >= 4:
            L.append("　毛利率 %.1f%% → %.1f%%（%s）；營益率 %s" % (
                gm[0], gm[-1], "變好" if gm[-1] > gm[0] + 1 else "變差" if gm[-1] < gm[0] - 1 else "持平",
                "%.1f%% → %.1f%%" % (om[0], om[-1]) if len(om) >= 2 else "—"))
        if len(q) >= 8:
            a, b = sum(x["eps"] for x in q[:4]), sum(x["eps"] for x in q[4:])
            L.append("　近 4 季 EPS 合計 %.2f，前 4 季 %.2f（%s）" % (b, a, pct(b / a - 1) if a > 0 else "前期虧損"))
        if q[-1]["eps"] < 0:
            L.append("　⚠️ 最近一季虧損")
    rev = s.get("rev") or []
    if len(rev) >= 24:
        yo = []
        for i in range(len(rev) - 12, len(rev)):
            if rev[i - 12]["v"]:
                yo.append((rev[i]["m"], rev[i]["v"] / rev[i - 12]["v"] - 1))
        if yo:
            pos = sum(1 for _, y in yo if y > 0)
            L.append("　月營收近 12 個月年增：%d 個月成長，最近 3 個月 %s" % (pos, "、".join("%s %s" % (m[5:], pct(y)) for m, y in yo[-3:])))
            r3 = sum(y for _, y in yo[-3:]) / 3
            r12 = sum(y for _, y in yo) / len(yo)
            L.append("　→ 營收動能%s（近 3 月平均年增 %s，近 12 月 %s）" % (
                "加速" if r3 > r12 + 0.05 else "放慢" if r3 < r12 - 0.05 else "穩定", pct(r3), pct(r12)))
    return L


# ---------- 2. 大事件 ----------
def event_study(D, M):
    """這檔與大盤在每個事件的 當天／5 天／20 天 漲跌"""
    idx = {d[0]: i for i, d in enumerate(D)}
    midx = {d[0]: i for i, d in enumerate(M)}
    dates = [d[0] for d in D]
    rows = []
    for day, name in EVENTS:
        t = next((i for i, d in enumerate(dates) if d >= day), None)
        if t is None or t < 1 or dates[t] > (dt.date.fromisoformat(day) + dt.timedelta(days=7)).isoformat():
            continue
        base = D[t - 1][4]
        r = [D[min(t + k, len(D) - 1)][4] / base - 1 for k in (0, 5, 20)]
        mr = None
        mt = midx.get(dates[t])
        if mt and mt >= 1:
            mb = M[mt - 1][4]
            mr = [M[min(mt + k, len(M) - 1)][4] / mb - 1 for k in (0, 5, 20)]
        rows.append((dates[t], name, r, mr, t + 20 < len(D)))
    L = []
    for d, name, r, mr, done in rows:
        L.append("　%s %s：當天 %s、5 天 %s、20 天 %s%s%s" % (
            d[2:], name, pct(r[0]), pct(r[1]), pct(r[2]) if done else "（未滿）",
            "｜大盤 %s／%s" % (pct(mr[0]), pct(mr[2])) if mr else "",
            "｜比大盤強" if mr and r[2] > mr[2] + 0.02 else "｜比大盤弱" if mr and r[2] < mr[2] - 0.02 else ""))
    drops = [x for x in rows if x[2][0] < -0.03]
    if drops:
        back = sum(1 for x in drops if x[4] and x[2][2] > x[2][0])
        L.append("　→ 大跌當天 %d 次，其中 %d 次 20 天後比當天收盤高（大事件急跌常是分批買點，但要有現金撐）" % (len(drops), back))
    return L


# ---------- 3. 下單價位（真實紀錄＋1 萬次模擬）----------
def entry_study(D):
    c = [d[4] for d in D]
    lo = [d[3] for d in D]
    n = len(D)
    t0 = n - 1
    m60 = ma(c, t0, 60)
    now = c[t0] / m60 - 1 if m60 else 0
    similar = [t for t in range(60, n - WAIT - HOLD) if abs(c[t] / ma(c, t, 60) - 1 - now) <= 0.03]
    allday = list(range(60, n - WAIT - HOLD))
    L = []
    best = None
    if len(similar) < 80:
        L.append("　現在股價在季線%s %.0f%%，10 年只有 %d 天這麼%s（很少見，相似日子太少不另外算）" % (
            "上" if now >= 0 else "下", abs(now) * 100, len(similar), "高" if now >= 0 else "低"))
    for name, days in (("跟現在位置相似的日子", similar), ("10 年所有日子", allday)):
        if len(days) < 80:
            continue
        L.append("　【%s，%d 天】股價在季線%s %.0f%% 時：" % (name, len(days), "上" if now >= 0 else "下", abs(now) * 100) if name.startswith("跟") else "　【%s，%d 天】" % (name, len(days)))
        for k in DISCOUNTS:
            fill, win, ret, dd = 0, 0, [], []
            for t in days:
                lim = c[t] * (1 - k / 100)
                f = next((j for j in range(t + 1, t + 1 + WAIT) if lo[j] <= lim), None)
                if f is None:
                    continue
                px = min(lim, D[f][1]) if k else D[f][1]  # 開盤就低於掛價 → 用開盤價成交
                fill += 1
                end = c[f + HOLD]
                ret.append(end / px - 1)
                win += end > px
                dd.append(min(lo[f:f + HOLD + 1]) / px - 1)
            if not fill:
                continue
            ret.sort()
            dd.sort()
            fr = fill / len(days)
            row = (k, fr, win / fill, sum(ret) / fill, dd[len(dd) // 10], dd[len(dd) // 2])
            L.append("　　掛%s：%d 天內成交 %.0f%%，成交後 60 天賺錢 %.0f%%、平均 %s，套最深中位數 %s、最慘 1 成 %s" % (
                "明天開盤價" if k == 0 else "低 %d%%" % k, WAIT, fr * 100, row[2] * 100, pct(row[3]), pct(row[5]), pct(row[4])))
            # 最佳掛價：只用「跟現在相似」的紀錄（不夠才用 10 年全部）；成交率至少 4 成，賺錢機率＋0.3×成交率最高
            score = row[2] + 0.3 * fr
            if fr >= 0.4 and (best is None or (best[3] == name and score > best[1])):
                best = (k, score, row, name)
    return L, best, now


def monte_carlo(D, seed=7):
    c = [d[4] for d in D]
    r = [c[i] / c[i - 1] for i in range(1, len(c))]
    if len(r) < BLOCK * 10:
        return []
    rnd = random.Random(seed)
    fin, worst = [], []
    nb = SIM_DAYS // BLOCK
    for _ in range(SIMS):
        p, low = 1.0, 1.0
        for _b in range(nb):
            s = rnd.randrange(0, len(r) - BLOCK)
            for x in r[s:s + BLOCK]:
                p *= x
                if p < low:
                    low = p
        fin.append(p)
        worst.append(low)
    fin.sort()
    worst.sort()
    q = lambda a, f: a[int(len(a) * f)]
    L = ["　1 萬次模擬（10 年真實走勢 20 天一段隨機接成 120 天）：",
         "　　120 天後賺錢機率 %.0f%%；結果中間值 %s，好的 1 成 %s 以上、差的 1 成 %s 以下" % (
             sum(1 for x in fin if x > 1) / SIMS * 100, pct(q(fin, 0.5) - 1), pct(q(fin, 0.9) - 1), pct(q(fin, 0.1) - 1)),
         "　　過程中最深套：一半的情況會套到 %s，1 成會套到 %s 以上（不停損就要撐得過這個）" % (pct(q(worst, 0.5) - 1), pct(q(worst, 0.1) - 1)),
         "　　⚠️ 模擬只是重組過去，不能預測新事件；跟上面的真實紀錄一起看"]
    return L, q(worst, 0.1) - 1


# ---------- 4. 下單時間（5 分 K）----------
def time_study(by):
    days = [v for v in by.values() if len(v) >= 30]
    if len(days) < 15:
        return [], None
    buckets = [("09:00-09:15", "09:00", "09:15"), ("09:15-10:00", "09:15", "10:00"), ("10:00-12:00", "10:00", "12:00"),
               ("12:00-13:00", "12:00", "13:00"), ("13:00-13:30", "13:00", "13:31")]
    low_at, high_at, dips = [], [], []
    for bars in days:
        lo = min(bars, key=lambda b: b[2])
        hi = max(bars, key=lambda b: b[1])
        low_at.append(lo[0])
        high_at.append(hi[0])
        op = bars[0][3]
        dips.append(lo[2] / op - 1)
    def dist(ts):
        return [(n, sum(1 for t in ts if a <= t < b) / len(ts)) for n, a, b in buckets]
    dl, dh = dist(low_at), dist(high_at)
    dips.sort()
    fills = [(k, sum(1 for d in dips if d <= -k / 100) / len(dips)) for k in (0.5, 1, 1.5, 2, 3)]
    L = ["　近 %d 天，每天最低點出現時段：%s" % (len(days), "、".join("%s %.0f%%" % (n, p * 100) for n, p in dl)),
         "　每天最高點出現時段：%s" % "、".join("%s %.0f%%" % (n, p * 100) for n, p in dh),
         "　從開盤價往下掛，當天成交機率：%s" % "、".join("低 %.1f%% → %.0f%%" % (k, p * 100) for k, p in fills)]
    top = max(dl, key=lambda x: x[1])
    L.append("　→ 最低點最常出現在 %s（%.0f%% 的日子）" % (top[0], top[1] * 100))
    return L, (dl, dh, fills)


# ---------- 5. 適合你的做法 ----------
def habit(best, wq, tdata, cyc, now, D=None):
    L = []
    c = [d[4] for d in D] if D else []
    t = len(c) - 1
    m20, m20p = (ma(c, t, 20), ma(c, t - 5, 20)) if t >= 30 else (None, None)
    if m20 and c[t] < m20 and m20 < m20p:  # 還在跌：月線下彎、收盤在月線下
        L.append("　⛔ 現在還在下跌（收盤 %s 在月線 %.1f 之下、月線往下）：先不要下單，等收盤站回月線再用下面的方法買；"
                 "真的想先買，只買 1/3、掛低價等（不要市價追）" % (round(c[t], 2), m20))
    if best:
        k = best[0]
        L.append("　📌 預約單價位：%s；過去這樣做 %d 天內成交 %.0f%%、成交後 60 天賺錢 %.0f%%" % (
            "掛太低不容易成交、也沒有比較好，前一晚或 9 點前掛「前一天收盤價」的限價買單買第 1 批（不要用市價）" if k == 0 else
            "前一晚或 9 點前掛「今天收盤價低 %d%%」的限價買單，沒成交每天重掛，最多 %d 個交易日" % (k, WAIT),
            WAIT, best[2][1] * 100, best[2][2] * 100))
    if tdata:
        dl, dh, fills = tdata
        early, first, last = dl[0][1] + dl[1][1], dl[0][1], dl[4][1]
        hi_open = dh[0][1]
        if hi_open >= 0.5:
            L.append("　📌 時間：開盤 15 分鐘常是當天最高點（%.0f%% 的日子），不要開盤用市價搶；限價單掛好等，或午休 12:00～13:30 再看" % (hi_open * 100))
        elif first >= 0.3 and last >= 0.2:
            L.append("　📌 時間：最低點常在開盤 15 分鐘（%.0f%%）或收盤前半小時（%.0f%%）。9 點前掛好預約單，沒成交就 13:00 後再看一次" % (first * 100, last * 100))
        elif early >= 0.5:
            L.append("　📌 時間：最低點多在 10 點前（%.0f%%），9 點前掛好預約單最適合你；中午再看要不要改價" % (early * 100))
        else:
            L.append("　📌 時間：最低點常在 10 點後（10 點前只佔 %.0f%%），可以午休 12:00～13:30 再用智慧單／觸價單買，不用急著開盤搶" % (early * 100))
        f1 = dict(fills).get(1)
        if f1:
            L.append("　📌 智慧單：開盤後掛「開盤價低 1%%」當天成交約 %.0f%%，想多省一點又不錯過可以這樣掛" % (f1 * 100))
    if wq is not None:
        L.append("　📌 不停損的代價：模擬顯示 1 成情況會套到 %s 以上。你不想停損的話：只用閒錢、分 3 批（每批隔 5%% 以上再買）、單檔不超過總資金 2 成" % pct(wq))
        if cyc:
            L.append("　⚠️ 這檔是循環股：景氣反轉時可能跌很久（華新就是例子），建議還是設智慧單「收盤跌破停損價」自動賣，至少留一半保命")
        elif wq < -0.35:
            L.append("　⚠️ 這檔波動很大，不停損很危險；至少設一個「跌 20%% 先賣一半」的智慧單")
    if now > 0.15:
        L.append("　⚠️ 股價在季線上 %.0f%%，偏高；寧可掛低一點等，沒成交就算了" % (now * 100))
    return L


def run(s, prof=None):
    """回傳深入分析文字（錯誤時回傳簡短說明，不中斷查個股）"""
    sid = s["id"]
    sym = symbol(sid, s.get("mkt"))
    out = ["🔬 深入分析：%s %s" % (sid, s.get("name", ""))]
    f = fundamentals(s)
    if f:
        out += ["・財報與營收趨勢："] + f
    if not sym:
        out.append("・Yahoo 抓不到這檔的長期股價，跳過事件／價位／時間分析")
        return "\n".join(out)
    D = daily(sym, 11)
    M = daily("^TWII", 11)
    if len(D) < 300:
        out.append("・上市時間太短，跳過事件與價位分析")
        return "\n".join(out)
    ev = event_study(D, M)
    if ev:
        out += ["・過去大事件時這檔怎麼走（漲跌從事件前一天收盤算）："] + ev
    E, best, now = entry_study(D)
    if E:
        out += ["・預約單掛多少比較好（真實紀錄，掛單最多等 %d 天，成交後看 %d 天）：" % (WAIT, HOLD)] + E
    mc = monte_carlo(D)
    wq = None
    if mc:
        mtext, wq = mc
        out += mtext
    tL, tdata = time_study(intraday(sym))
    if tL:
        out += ["・幾點下單比較好（近 60 天 5 分 K）："] + tL
    import analysis
    cyc = analysis.is_cyc(prof) if prof else False
    h = habit(best, wq, tdata, cyc, now, D)
    if h:
        out += ["・依你的習慣（9 點前／午休／下班後看盤、常用預約單與智慧單、不太想停損）："] + h
    return "\n".join(out)
