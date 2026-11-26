"""
hist.py - 全市場 10 年以上日 K 與法人買賣超（上市＋上櫃、含已下市的公司），給回測用
（2026-11-26 使用者同意：現在回測只有 270 檔、1 年半，大跌只碰過幾次，結果容易是運氣；補齊後每條規則都能用幾十次大跌驗證）

資料：證交所 MI_INDEX＋T86、櫃買中心日行情＋三大法人（共用 market.fetch_day，不用金鑰）
     每天的「全市場快照」本來就包含當時還在交易、之後下市的公司 → 沒有倖存者偏差
     價格是原始收盤價（沒有還原除權息）：回測時單日漲跌超過 11% 的要當成除權息或減資跳過
存法：輸出資料夾/YYYY.json.gz：{日期: {代號: [開, 高, 低, 收, 張數, 外資, 投信]}}
     輸出資料夾/meta.json：{"names": {代號: [名稱, 市場, 第一天, 最後一天]}, "closed": [休市日], "no_otc": [上櫃沒抓到的日子]}
從最近往回補，每次執行最多跑 MAX 分鐘就存檔結束，下次接著補（GitHub 每次最多 6 小時）；補完之後每次只補新的日子

用法：python hist.py 輸出資料夾 [從哪一年=2014] [最多幾分鐘=330]
"""
import datetime as dt
import gzip
import json
import os
import sys
import time

import market

OUT = sys.argv[1] if len(sys.argv) > 1 else "hist"
START = int(sys.argv[2]) if len(sys.argv) > 2 else 2014
MAX = float(sys.argv[3]) if len(sys.argv) > 3 else 330
SAVE_EVERY = 20


def load(year):
    p = os.path.join(OUT, "%d.json.gz" % year)
    if not os.path.exists(p):
        return {}
    with gzip.open(p, "rt", encoding="utf-8") as f:
        return json.load(f)


def save(year, data):
    p = os.path.join(OUT, "%d.json.gz" % year)
    with gzip.open(p + ".tmp", "wt", encoding="utf-8", compresslevel=9) as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    os.replace(p + ".tmp", p)


def main():
    os.makedirs(OUT, exist_ok=True)
    mp = os.path.join(OUT, "meta.json")
    meta = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {"names": {}, "closed": [], "no_otc": []}
    tries = meta.setdefault("otc_try", {})  # 上櫃沒抓到的日子重試次數（最多 3 次，舊資料網站可能本來就沒有）
    closed, no_otc = set(meta["closed"]), set(meta["no_otc"])
    years = {}
    have = set()
    for y in range(START, dt.date.today().year + 1):
        years[y] = load(y)
        have |= set(years[y])
    today = dt.date.today()
    last = today if dt.datetime.now().hour >= 17 else today - dt.timedelta(days=1)  # 今天收盤資料 17 點後才齊
    todo = []
    d = last
    while d.year >= START:
        k = d.isoformat()
        if d.weekday() < 5 and k not in closed and (k not in have or (k in no_otc and tries.get(k, 0) < 3)):
            todo.append(d)
        d -= dt.timedelta(days=1)
    total_days = sum(1 for y in years.values() for _ in y)
    print("已有 %d 個交易日、休市 %d 天；還要抓 %d 天（從 %s 往回到 %d 年）" % (total_days, len(closed), len(todo), last, START), flush=True)
    t0, n, dirty, err = time.time(), 0, set(), 0

    def flush():
        for y in dirty:
            save(y, years[y])
        meta["closed"], meta["no_otc"] = sorted(closed), sorted(no_otc)
        json.dump(meta, open(mp, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        dirty.clear()

    for d in todo:
        if (time.time() - t0) / 60 > MAX:
            print("時間到，先存檔，下次接著補", flush=True)
            break
        k = d.isoformat()
        try:
            rows, names = market.fetch_day(d)
        except Exception as e:
            err += 1
            print(k, "抓取失敗：", str(e)[:120], flush=True)
            if err >= 8:  # 一直失敗（被擋或網站維護）：先停，下次再試
                print("連續失敗太多次，先停", flush=True)
                break
            time.sleep(30)
            continue
        err = 0
        if rows is None:
            closed.add(k)
        else:
            years.setdefault(d.year, {})[k] = rows
            dirty.add(d.year)
            if not any(v[1] == "上櫃" for v in names.values()):
                no_otc.add(k)
                tries[k] = tries.get(k, 0) + 1
            else:
                no_otc.discard(k)
            for c, (nm, mk) in names.items():
                e = meta["names"].get(c)
                if not e:
                    meta["names"][c] = [nm, mk, k, k]
                else:
                    e[2], e[3] = min(e[2], k), max(e[3], k)
                    if k == e[3]:
                        e[0], e[1] = nm, mk  # 名稱用最新的
            n += 1
        if n and n % SAVE_EVERY == 0 and dirty:
            flush()
            print("進度：本次 %d 天，最新抓到 %s，%.0f 分鐘" % (n, k, (time.time() - t0) / 60), flush=True)
    flush()
    got = set(k for v in years.values() for k in v)
    left = sum(1 for d in todo if d.isoformat() not in got and d.isoformat() not in closed)
    print("本次抓了 %d 個交易日；全部共 %d 個交易日、%d 檔（含已下市）；剩約 %d 天沒抓%s" % (
        n, len(got), len(meta["names"]), left, "（全部補完，之後只補新的日子）" if not left else ""), flush=True)
    if no_otc:
        print("上櫃沒抓到的日子 %d 天（下次重抓）" % len(no_otc))


if __name__ == "__main__":
    main()
