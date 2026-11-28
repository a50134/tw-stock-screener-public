"""
research/full_bt.py - 資料收齊後的總回測（2026-11-28；使用者規則：資料沒收齊不下結論）
資料：hist-data 分支 hist/（2014-01 起全市場上市＋上櫃日 K、外資投信、融資，含已下市公司；fut.json 期貨 2007 起、法人 2018-06 起）
回測方式（每一項都一樣）：
  訊號當天收盤後才知道 → 隔天開盤買、抱 N 天收盤賣；只算均量 500 張以上；同一檔 N 天內只算第一次（避免重複算）
  期間內有單日漲跌超過 11% 的（除權息、減資）跳過
  比較基準：同一天所有符合條件股票的平均（扣掉大盤當時好壞，看訊號本身有沒有多賺）
  大盤用 0050（拆股已還原、沒含配息）
用法：python research/full_bt.py hist資料夾
"""
import collections
import glob
import gzip
import json
import os
import sys

import numpy as np

H = sys.argv[1] if len(sys.argv) > 1 else "hist"
N = 20
MINV = 500


def load():
    px = {}
    for f in sorted(glob.glob(os.path.join(H, "20*.json.gz"))):
        with gzip.open(f, "rt", encoding="utf-8") as g:
            px.update(json.load(g))
    mg = {}
    for f in sorted(glob.glob(os.path.join(H, "mg_20*.json.gz"))):
        with gzip.open(f, "rt", encoding="utf-8") as g:
            mg.update(json.load(g))
    D = sorted(px)
    codes = sorted({c for d in D for c in px[d]})
    ix = {c: i for i, c in enumerate(codes)}
    T, S = len(D), len(codes)
    A = np.full((7, T, S), np.nan, dtype=np.float32)
    M = np.full((T, S), np.nan, dtype=np.float32)
    for t, d in enumerate(D):
        for c, r in px[d].items():
            j = ix[c]
            for k in range(7):
                if r[k] is not None:
                    A[k, t, j] = r[k]
        for c, v in (mg.get(d) or {}).items():
            if c in ix and v is not None:
                M[t, ix[c]] = v
    F = json.load(open(os.path.join(H, "fut.json"), encoding="utf-8"))["days"]
    meta = json.load(open(os.path.join(H, "meta.json"), encoding="utf-8"))
    return D, codes, A, M, F, meta


D, CODES, A, MG, FUT, META = load()
O, HI, LO, C, V, FI, IT = A
T, S = C.shape
YR = np.array([int(d[:4]) for d in D])
nn = lambda x: np.nan_to_num(x, nan=0.0)  # noqa: E731
prevC = np.vstack([np.full((1, S), np.nan), C[:-1]])
JUMP = np.abs(C / prevC - 1) > 0.11
JC = np.vstack([np.zeros((1, S)), np.cumsum(np.nan_to_num(JUMP), axis=0)])  # JC[t] = 0..t-1 的跳空次數


def ma(x, n):
    """n 日平均（不足 n 天是 nan）"""
    cs = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(nn(x), axis=0)])
    cnt = np.vstack([np.zeros((1, x.shape[1])), np.cumsum(~np.isnan(x), axis=0)])
    out = np.full(x.shape, np.nan, dtype=np.float64)
    s = cs[n:] - cs[:-n]
    k = cnt[n:] - cnt[:-n]
    out[n - 1:] = np.where(k == n, s / np.maximum(k, 1), np.nan)
    return out


def lag(x, k):
    out = np.full(x.shape, np.nan, dtype=np.float64)
    out[k:] = x[:-k]
    return out


def rmax(x, n):
    out = np.full(x.shape, np.nan)
    for t in range(n - 1, x.shape[0]):
        out[t] = np.nanmax(x[t - n + 1:t + 1], axis=0)
    return out


def rmin(x, n):
    out = np.full(x.shape, np.nan)
    for t in range(n - 1, x.shape[0]):
        out[t] = np.nanmin(x[t - n + 1:t + 1], axis=0)
    return out


AV20 = lag(ma(V, 20), 1)  # 前 20 天均量（不含今天）
LIQ = AV20 >= MINV
ETF = np.array([c.startswith("00") for c in CODES])


def fwd(n=N):
    """R[t] = 第 t 天訊號 → t+1 開盤買、t+n 收盤賣的報酬；有除權息跳空、沒成交的是 nan"""
    R = np.full((T, S), np.nan)
    if T > n + 1:
        e = O[1:T - n + 1]  # t+1 開盤
        x = C[n:T]  # t+n 收盤
        jumps = JC[n + 1:T + 1] - JC[1:T - n + 1]  # t+1～t+n 有沒有除權息跳空
        R[:T - n] = np.where((jumps == 0) & (e > 0) & (x > 0), x / e - 1, np.nan)
    return R


R20, R60, R5 = fwd(20), fwd(60), fwd(5)
BASE_OK = LIQ & ~ETF[None, :]
BASE20 = np.array([np.nanmean(np.where(BASE_OK[t], R20[t], np.nan)) if BASE_OK[t].any() else np.nan for t in range(T)])


def market():
    """0050 還原拆股的收盤／開盤序列"""
    j = CODES.index("0050")
    c, o = C[:, j].astype(float), O[:, j].astype(float)
    ac, ao = c.copy(), o.copy()  # 拆股日（單日變動超過 11%）之前的價格乘上比例
    for t in range(1, T):
        if c[t] and c[t - 1] and abs(c[t] / c[t - 1] - 1) > 0.11:
            k = c[t] / c[t - 1]
            ac[:t] *= k
            ao[:t] *= k
    return ac, ao


MC, MO = market()


def mfwd(n, entry="open"):
    """大盤（0050）第 t 天訊號 → 隔天開盤買、t+n 收盤賣"""
    r = np.full(T, np.nan)
    for t in range(T - n):
        r[t] = MC[t + n] / (MO[t + 1] if entry == "open" else MC[t]) - 1
    return r


M5, M20, M60 = mfwd(5), mfwd(20), mfwd(60)


def pct(v):
    return "%.0f%%" % (v * 100)


def stat_stock(name, sig, R=R20, dedupe=N, note=""):
    """sig: (T,S) bool。印出次數、勝率、平均、同日全部股票、多賺、各年"""
    sig = sig & BASE_OK
    rows = []
    last = np.full(S, -10 ** 9)
    for t in range(T):
        js = np.nonzero(sig[t])[0]
        for j in js:
            if t - last[j] < dedupe or np.isnan(R[t, j]):
                continue
            last[j] = t
            rows.append((t, j, R[t, j]))
    if not rows:
        print("【%s】0 次" % name)
        return None
    r = np.array([x[2] for x in rows])
    base = np.array([BASE20[x[0]] if R is R20 else np.nan for x in rows])
    win = (r > 0).mean()
    by = collections.defaultdict(list)
    for (t, j, x), b in zip(rows, base):
        by[YR[t]].append(x - b if not np.isnan(b) else np.nan)
    yrs = {y: np.nanmean(v) for y, v in by.items() if len(v) >= 10}
    good = sum(1 for v in yrs.values() if v > 0)
    codes = {x[1] for x in rows}
    dl = sum(1 for j in codes if META["names"].get(CODES[j], [0, 0, 0, D[-1]])[3] < D[-6])
    ex = np.nanmean(r - base) if R is R20 else np.nan
    print("【%s】%d 次（%d 檔，其中已下市 %d 檔）：勝率 %s、平均 %+.1f%%、中位數 %+.1f%%；同一天全部股票 %+.1f%% → 多賺 %+.1f%%；"
          "%d 年裡 %d 年比全部好%s" % (name, len(r), len(codes), dl, pct(win), r.mean() * 100, np.median(r) * 100,
                                  np.nanmean(base) * 100, ex * 100, len(yrs), good, ("；" + note) if note else ""), flush=True)
    return dict(n=len(r), win=win, mean=r.mean(), ex=ex, years=len(yrs), good=good)


def stat_mkt(name, sig, R=M20, ref=None):
    """sig: (T,) bool → 大盤之後 N 天"""
    ok = sig & ~np.isnan(R)
    allr = R[~np.isnan(R) & (ref if ref is not None else True)]
    r = R[ok]
    if not len(r):
        print("【%s】0 次" % name)
        return None
    by = collections.defaultdict(list)
    ep, last = [], -10 ** 9
    for t in np.nonzero(ok)[0]:
        by[YR[t]].append(R[t])
        if t - last > 20:  # 隔 20 天以上才算新的一波
            ep.append(R[t])
        last = t
    ep = np.array(ep)
    print("【%s】%d 天（%d 波）：大盤之後上漲 %s、平均 %+.1f%%（每波第一天：%s、%+.1f%%）｜同期所有日子 %s、%+.1f%%；%d 個年份有訊號" % (
        name, len(r), len(ep), pct((r > 0).mean()), r.mean() * 100, pct((ep > 0).mean()), ep.mean() * 100,
        pct((allr > 0).mean()), allr.mean() * 100, len(by)), flush=True)
    return dict(n=len(r), win=(r > 0).mean(), mean=r.mean())


def rank_past(x, look=250):
    """x[t] 在過去 look 天（不含今天）排第幾（0～1）"""
    out = np.full(len(x), np.nan)
    for t in range(look, len(x)):
        h = x[t - look:t]
        h = h[~np.isnan(h)]
        if len(h) >= look * 0.8 and not np.isnan(x[t]):
            out[t] = (h < x[t]).mean()
    return out


def header():
    yrs = "%s～%s" % (D[0], D[-1])
    dl = sum(1 for v in META["names"].values() if v[3] < D[-6])
    print("資料：%s，%d 個交易日、%d 檔（含已下市 %d 檔）；只算均量 %d 張以上、非 ETF" % (yrs, T, S, dl, MINV))
    print("全部股票隨便買抱 20 天：勝率 %s、平均 %+.1f%%" % (
        pct(np.nanmean(np.where(BASE_OK, R20 > 0, np.nan)[~np.isnan(np.where(BASE_OK, R20, np.nan))])),
        np.nanmean(np.where(BASE_OK, R20, np.nan)) * 100))
    print("0050 隨時買抱 20 天：上漲 %s、平均 %+.1f%%\n" % (pct(np.nanmean(M20[~np.isnan(M20)] > 0)), np.nanmean(M20) * 100))


# ---------- 大盤層級的資料 ----------
FD = [FUT.get(d, {}) for d in D]
TXF = np.array([x.get("tx_f", np.nan) for x in FD], dtype=float)
MI = np.array([x.get("mtx_inst", np.nan) for x in FD], dtype=float)
MOI = np.array([x.get("mtx_oi", np.nan) for x in FD], dtype=float)
PCR = np.array([x.get("pcr", np.nan) for x in FD], dtype=float)
MKT_FI = np.nansum(np.where(ETF[None, :], 0, FI), axis=1)
MKT_MG = np.nansum(MG, axis=1)
M5D = np.array([MC[t] / MC[t - 5] - 1 if t >= 5 else np.nan for t in range(T)])
M60H = np.array([MC[t] / np.nanmax(MC[max(0, t - 59):t + 1]) - 1 for t in range(T)])


def part_retail():
    print("=== ① 散戶多空比（小台：−三大法人淨未平倉÷全市場未平倉），2018-06 起 ===")
    rr = -MI / MOI
    p = rank_past(rr)
    has = ~np.isnan(p)
    print("有資料 %d 天（%s～）" % (has.sum(), D[np.argmax(has)]))
    for lo, hi, nm in ((0.9, 1.01, "散戶非常偏多（一年來前 10%）"), (0.7, 0.9, "散戶偏多（前 10～30%）"), (0.3, 0.7, "中間"),
                       (0.1, 0.3, "散戶偏空（後 10～30%）"), (-0.01, 0.1, "散戶非常偏空（後 10%）")):
        s = has & (p >= lo) & (p < hi)
        stat_mkt(nm + "：5 天", s, M5, has)
        stat_mkt(nm + "：20 天", s, M20, has)
    # 策略：跟散戶反著做 → 散戶偏多（前 30%）時空手、其他時間抱 0050；對照一直抱
    for th, nm in ((0.7, "散戶前 30% 偏多時空手"), (0.9, "散戶前 10% 偏多時空手")):
        hold = np.zeros(T, bool)
        eq, bh = 1.0, 1.0
        pk_e, pk_b, dd_e, dd_b = 1.0, 1.0, 0.0, 0.0
        days_in = 0
        start = np.argmax(has)
        for t in range(start, T - 1):
            r = MC[t + 1] / MC[t] - 1
            if np.isnan(r):
                continue
            inmkt = not (p[t] >= th)
            if inmkt:
                eq *= 1 + r
                days_in += 1
            bh *= 1 + r
            pk_e, pk_b = max(pk_e, eq), max(pk_b, bh)
            dd_e, dd_b = min(dd_e, eq / pk_e - 1), min(dd_b, bh / pk_b - 1)
        print("・%s（收盤判斷、隔天起算）：總報酬 %+.0f%%、最大跌幅 %.0f%%、在場 %d%% 的日子；一直抱 0050：%+.0f%%、最大跌幅 %.0f%%" % (
            nm, (eq - 1) * 100, dd_e * 100, days_in * 100 / max(1, T - 1 - start), (bh - 1) * 100, dd_b * 100))
    print()


def part_futopt():
    print("=== ② 期貨籌碼燈號（暫停中）：外資台指期 5 天加減碼（2018-06 起）、選擇權 P/C 比（2014 起） ===")
    fd5 = TXF - lag(TXF[:, None], 5)[:, 0]
    fp = rank_past(fd5)
    pp = rank_past(PCR)
    hf, hp = ~np.isnan(fp), ~np.isnan(pp)
    stat_mkt("外資 5 天大加碼（前 10%）", hf & (fp >= 0.9), M20, hf)
    stat_mkt("外資 5 天大減碼（後 10%）", hf & (fp < 0.1), M20, hf)
    stat_mkt("P/C 比偏高（前 10%）", hp & (pp >= 0.9), M20, hp)
    stat_mkt("P/C 比偏低（後 10%）", hp & (pp < 0.1), M20, hp)
    drop = M5D <= -0.03
    stat_mkt("0050 5 天跌 3%＋外資加碼（前 30%）", hf & drop & (fp >= 0.7), M20, hf)
    stat_mkt("0050 5 天跌 3%＋外資減碼（後 30%）", hf & drop & (fp < 0.3), M20, hf)
    for y0, y1 in ((2018, 2021), (2022, 2026)):
        per = (YR >= y0) & (YR <= y1)
        stat_mkt("  %d～%d 外資大加碼" % (y0, y1), hf & per & (fp >= 0.9), M20, hf & per)
        stat_mkt("  %d～%d P/C 偏高" % (y0, y1), hp & per & (pp >= 0.9), M20, hp & per)
    print()


def part_drop():
    print("=== ③ 大盤急跌先觀望（暫停中）：0050 5 天跌 3% 以上 ===")
    drop = M5D <= -0.03
    stat_mkt("0050 5 天跌 3% 以上 → 0050", drop, M20)
    strong = (C >= rmax(C, 20) * 0.97) & (C > ma(C, 60))  # 代表「追強勢」的選股：收盤在 20 天高點 3% 內、站上季線
    stat_stock("急跌時的強勢股（20 天高點附近＋季線上）", strong & drop[:, None])
    stat_stock("平常的強勢股", strong & ~drop[:, None])
    stat_stock("急跌時所有股票", BASE_OK & drop[:, None], dedupe=20)
    print()


def part_handoff():
    print("=== ④ 斷頭後法人接手（暫停中，林漢偉）、反彈日站回前一天高點（陳威良） ===")
    mg3 = MG / lag(MG, 3) - 1
    inst3 = nn(FI) + nn(IT)
    inst3 = inst3 + lag(inst3, 1) + lag(inst3, 2)
    deep = (M60H <= -0.10)[:, None]
    stat_stock("① 大盤離高點 −10%＋融資 3 天減 10%＋法人 3 天買超", deep & (mg3 <= -0.10) & (inst3 > 0))
    stat_stock("  對照：大盤離高點 −10%＋融資 3 天減 10%（法人沒買）", deep & (mg3 <= -0.10) & (inst3 <= 0))
    stat_stock("  對照：大盤離高點 −10% 全部股票", deep & BASE_OK)
    reb = np.zeros(T, bool)
    for t in range(6, T):
        reb[t] = MC[t - 1] / MC[t - 6] - 1 <= -0.05 and MC[t] / MC[t - 1] - 1 >= 0.015
    reb = reb[:, None]
    over = C > lag(HI, 1)
    cond = (nn(IT) > 0) & (MG < lag(MG, 5))
    stat_stock("② 反彈日（0050 前 5 天跌 5%、今天漲 1.5%）收盤站回前一天高點＋投信買＋融資減", reb & over & cond)
    stat_stock("  反彈日站回前一天高點（不管法人融資）", reb & over)
    stat_stock("  反彈日沒站回前一天高點", reb & ~over & BASE_OK)
    print()


def part_tv():
    print("=== ⑤ 財經節目說法 ===")
    c1, o1, h1 = lag(C, 1), lag(O, 1), lag(HI, 1)
    engulf = (O < c1) & (C > O) & (c1 < o1) & (C > h1) & (V >= 1.5 * AV20)
    stat_stock("大量多頭吞噬（開低翻紅、收過前一根黑 K 高點、量 1.5 倍）", engulf)
    # 3 天不破低：訊號日之後 3 天最低都不破訊號日低點 → 第 3 天收盤才確認，第 4 天開盤買
    low3 = np.fmin(np.fmin(lag(LO, 1), lag(LO, 2)), lag(LO, 3))
    conf = lag(engulf.astype(float), 3) == 1
    stat_stock("大量多頭吞噬＋之後 3 天不破低（第 4 天買）", conf & (low3 >= lag(LO, 3)))
    # 抗跌：0050 從 20 天高點跌 5% 以上時，個股自己從 20 天高點的跌幅比 0050 小
    m20dd = np.array([MC[t] / np.nanmax(MC[max(0, t - 19):t + 1]) - 1 for t in range(T)])
    pull = (m20dd <= -0.05)[:, None]
    sdd = C / rmax(C, 20) - 1
    stat_stock("大盤回檔 5% 時跌得比大盤少的（抗跌）", pull & (sdd > m20dd[:, None]))
    stat_stock("  大盤回檔 5% 時跌得比大盤多的", pull & (sdd <= m20dd[:, None]))
    # 李永年止跌：外資（全市場）連 3 天買超＋全市場融資 3 天沒增加，大盤離 60 天高點 −5% 以上時
    f3 = np.array([t >= 2 and MKT_FI[t] > 0 and MKT_FI[t - 1] > 0 and MKT_FI[t - 2] > 0 for t in range(T)])
    mgflat = np.array([t >= 3 and MKT_MG[t] <= MKT_MG[t - 3] for t in range(T)])
    weak = M60H <= -0.05
    stat_mkt("李永年止跌（大盤離高點 −5%＋外資連 3 天買＋融資 3 天沒增加）", weak & f3 & mgflat, M20, weak)
    stat_mkt("  只有外資連 3 天買（大盤離高點 −5%）", weak & f3, M20, weak)
    # 地板股：量 ≥ 20 日均量 2.5 倍＋年線下 15%
    ma240 = ma(C, 240)
    under = C <= ma240 * 0.85
    stat_stock("地板股（爆量 2.5 倍＋年線下 15%）", under & (V >= 2.5 * AV20))
    stat_stock("  只看年線下 15%", under)
    # 大跌後 5 日線上揚、回測 5 日線沒破
    ma5 = ma(C, 5)
    fell = C / rmax(C, 20) - 1 <= -0.15
    fell10 = lag(fell.astype(float), 1) == 1
    for k in range(2, 11):
        fell10 = fell10 | (lag(fell.astype(float), k) == 1)
    retest = fell10 & (ma5 > lag(ma5, 1)) & (LO <= ma5 * 1.01) & (C >= ma5)
    stat_stock("大跌 15% 後 5 日線上揚、回測 5 日線沒破", retest)
    stat_stock("  大跌 15% 後站回 5 日線", fell10 & (C > ma5) & (lag(C, 1) <= lag(ma5, 1)))
    # 爆量下影線（大跌 10% 後）
    body = np.abs(C - O)
    shadow = np.fmin(O, C) - LO
    hammer = (shadow >= 2 * body) & ((HI - LO) / c1 >= 0.03) & (V >= 2 * AV20) & (C / rmax(C, 10) - 1 <= -0.10)
    stat_stock("爆量下影線（10 天跌 10% 後）", hammer)
    # 外資 3 日均買超突破 5 日均買超
    f3m, f5m = ma(FI, 3), ma(FI, 5)
    cross = (f3m > f5m) & (lag(f3m, 1) <= lag(f5m, 1)) & (f3m > 0)
    stat_stock("外資 3 日均買超向上突破 5 日均", cross)
    print()


def part_cgo():
    print("=== ⑥ 未實現資本利得（CGO，TEJ 因子）：股價比 250 天成交量加權平均成本高越多 ===")
    pv = np.vstack([np.zeros((1, S)), np.cumsum(nn(C) * nn(V), axis=0)])
    vv = np.vstack([np.zeros((1, S)), np.cumsum(nn(V), axis=0)])
    rp = np.full((T, S), np.nan)
    rp[250:] = (pv[251:] - pv[1:-250]) / np.maximum(vv[251:] - vv[1:-250], 1)
    cgo = C / rp - 1
    res = collections.defaultdict(list)
    for t in range(260, T - 21, 20):  # 每 20 天重新排一次
        ok = BASE_OK[t] & ~np.isnan(cgo[t]) & ~np.isnan(R20[t])
        if ok.sum() < 100:
            continue
        x, r = cgo[t][ok], R20[t][ok]
        q = np.quantile(x, [0.2, 0.8])
        res["top"].append(np.mean(r[x >= q[1]]))
        res["bot"].append(np.mean(r[x <= q[0]]))
        res["all"].append(np.mean(r))
        res["yr"].append(YR[t])
    top, bot, al = map(np.array, (res["top"], res["bot"], res["all"]))
    yrs = sorted(set(res["yr"]))
    good = sum(1 for y in yrs if np.mean(top[np.array(res["yr"]) == y]) > np.mean(al[np.array(res["yr"]) == y]))
    print("每 20 天換一次、%d 期：帳上最賺的前 20%% 平均 %+.1f%%（贏全部 %d%% 的期數）、最賠的後 20%% %+.1f%%、全部 %+.1f%%；%d 年裡 %d 年前 20%% 比全部好" % (
        len(top), top.mean() * 100, round((top > al).mean() * 100), bot.mean() * 100, al.mean() * 100, len(yrs), good))
    print()


if __name__ == "__main__":
    header()
    for f in (part_retail, part_futopt, part_drop, part_handoff, part_tv, part_cgo):
        try:
            f()
        except Exception as e:
            import traceback
            traceback.print_exc()
            print(f.__name__, "失敗：", e, flush=True)
