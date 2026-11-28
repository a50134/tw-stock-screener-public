"""
research/rev_bt.py - 月營收策略回測（2026-11-28；月營收 10 年歷史補齊後）
資料：hist-data 分支 hist/（行情＋法人 2014 起含已下市；rev.json.gz 月營收 FinMind 2014 起，下市公司部分沒有）
訊號日：營收月份的下個月 11 日（或之後第一個交易日）收盤後——所有公司都公布了才用，避免偷看
買法：跟 research/full_bt.py 一樣（隔天開盤買、抱 20／60 天、均量 500 張以上、除權息跳空跳過、跟同一天全部股票比）
用法：python research/rev_bt.py hist資料夾
"""
import datetime as dt
import gzip
import json
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import full_bt as B  # noqa: E402

REV = json.load(gzip.open(os.path.join(B.H, "rev.json.gz"), "rt", encoding="utf-8"))
META = json.load(open(os.path.join(B.H, "rev_meta.json"), encoding="utf-8"))
T, S, C, V = B.T, B.S, B.C, B.V
IX = {c: i for i, c in enumerate(B.CODES)}
DIDX = {d: i for i, d in enumerate(B.D)}


def sigday(y, m):
    """營收月份 y-m → 下個月 11 日起第一個交易日的索引"""
    ny, nm = (y + 1, 1) if m == 12 else (y, m + 1)
    d = dt.date(ny, nm, 11)
    for _ in range(10):
        if d.isoformat() in DIDX:
            return DIDX[d.isoformat()]
        d += dt.timedelta(days=1)
    return None


def rv(y, m, c):
    return (REV.get("%04d-%02d" % (y, m)) or {}).get(c)


def ytd(y, m, c):
    vals = [rv(y, k, c) for k in range(1, m + 1)]
    return sum(vals) if all(v is not None for v in vals) else None


MA20, MA60 = B.ma(C, 20), B.ma(C, 60)
VMIN20 = B.rmin(np.where(np.isnan(V), 0, V), 20)  # 近 20 天每天量的最小值


def events(rule):
    """rule(y, m, c, t, j) → True/False；回傳 (T,S) 訊號矩陣"""
    sig = np.zeros((T, S), bool)
    for y in range(2015, 2027):
        for m in range(1, 13):
            t = sigday(y, m)
            if t is None:
                continue
            for c, j in IX.items():
                if not B.BASE_OK[t, j]:
                    continue
                try:
                    if rule(y, m, c, t, j):
                        sig[t, j] = True
                except (TypeError, ZeroDivisionError):
                    pass
    return sig


def progress(y, m, c):
    a, b = ytd(y, m, c), ytd(y - 1, 12, c)
    return a / b if a is not None and b else None


def ma_ok(t, j):
    return C[t, j] > MA20[t, j] and C[t, j] > MA60[t, j]


def main():
    n_rev = len(META["done"])
    print("月營收：%d 檔有資料（%s～%s）；FinMind 沒資料 %d 檔（多是已下市公司）" % (n_rev, min(REV), max(REV), len(META["empty"])))
    B.header()
    print("=== ① 年底營收進度（今周刊）：11 月累計營收 ≥ 去年全年 91.67%（12 月 11 日後判斷）＋站上 20／60 日線＋量 ===")
    nov = lambda y, m: m == 11  # noqa: E731
    for vol in (5000, 1000, 0):
        s = events(lambda y, m, c, t, j, vol=vol: nov(y, m) and progress(y, m, c) >= 11 / 12 and ma_ok(t, j) and VMIN20[t, j] >= vol)
        B.stat_stock("11 月進度 ≥91.67%%＋均線上＋20 天每天量 ≥%d 張" % vol, s)
        B.stat_stock("  同上，抱 60 天", s, R=B.R60, dedupe=60)
    s = events(lambda y, m, c, t, j: nov(y, m) and ma_ok(t, j) and VMIN20[t, j] >= 5000)
    B.stat_stock("  對照：12 月中均線上＋每天量 ≥5000 張（不看營收）", s)
    s = events(lambda y, m, c, t, j: nov(y, m) and progress(y, m, c) < 11 / 12 and ma_ok(t, j) and VMIN20[t, j] >= 5000)
    B.stat_stock("  對照：同上但營收進度沒達標", s)
    s = events(lambda y, m, c, t, j: nov(y, m) and progress(y, m, c) >= 11 / 12)
    B.stat_stock("  只看 11 月進度 ≥91.67%（不看均線、量）", s)
    s = events(lambda y, m, c, t, j: nov(y, m) and progress(y, m, c) < 11 / 12 and ma_ok(t, j))
    B.stat_stock("  對照：11 月進度沒達標但均線上", s)
    s = events(lambda y, m, c, t, j: nov(y, m) and ma_ok(t, j))
    B.stat_stock("  對照：12 月中所有均線上的股票", s)
    for x in (1.1, 1.2, 1.3):
        s = events(lambda y, m, c, t, j, x=x: nov(y, m) and progress(y, m, c) >= 11 / 12 * x and ma_ok(t, j))
        B.stat_stock("11 月進度 ≥ 去年同期步調 ×%.1f（營收成長 %d%% 以上）＋均線上" % (x, round((x - 1) * 100)), s)
    print()
    print("=== ② 每個月都看營收進度：累計營收 ≥ 去年全年 × 月份/12 × 1.2（成長 20% 的步調）＋均線上 ===")
    s = events(lambda y, m, c, t, j: progress(y, m, c) >= m / 12 * 1.2 and ma_ok(t, j))
    B.stat_stock("每月：營收進度領先 20%＋均線上", s)
    for mm in (3, 6, 9, 11):
        s = events(lambda y, m, c, t, j, mm=mm: m == mm and progress(y, m, c) >= m / 12 * 1.2 and ma_ok(t, j))
        B.stat_stock("  只看 %d 月營收" % mm, s)
    print()
    print("=== ③ 其他營收條件（每月 11 日後判斷） ===")

    def yoy(y, m, c):
        a, b = rv(y, m, c), rv(y - 1, m, c)
        return a / b - 1 if a is not None and b and b > 0 else None

    def high12(y, m, c):
        a = rv(y, m, c)
        prev = [rv(y if m - k > 0 else y - 1, (m - k - 1) % 12 + 1, c) for k in range(1, 12)]
        return a is not None and all(p is not None for p in prev) and a > max(prev)

    s = events(lambda y, m, c, t, j: all((yoy(*((y, m - k) if m - k > 0 else (y - 1, m - k + 12)), c) or -9) > 0.10 for k in range(3)))
    B.stat_stock("營收年增連 3 個月 > 10%", s)
    s = events(lambda y, m, c, t, j: all((yoy(*((y, m - k) if m - k > 0 else (y - 1, m - k + 12)), c) or -9) > 0.10 for k in range(3)) and ma_ok(t, j))
    B.stat_stock("  ＋均線上", s)
    s = events(lambda y, m, c, t, j: high12(y, m, c))
    B.stat_stock("營收創 12 個月新高", s)
    s = events(lambda y, m, c, t, j: high12(y, m, c) and (yoy(y, m, c) or -9) > 0.2 and ma_ok(t, j))
    B.stat_stock("  ＋年增 20%＋均線上", s)
    s = events(lambda y, m, c, t, j: (yoy(y, m, c) or 9) < -0.2)
    B.stat_stock("對照：營收年減 20% 以上", s)


if __name__ == "__main__":
    main()
