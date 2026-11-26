"""
hist.py - 全市場 10 年以上日 K 與法人買賣超（上市＋上櫃、含已下市的公司），給回測用
（2026-11-26 使用者同意：現在回測只有 270 檔、1 年半，大跌只碰過幾次，結果容易是運氣；補齊後每條規則都能用幾十次大跌驗證）

資料：證交所 MI_INDEX＋T86、櫃買中心日行情＋三大法人（共用 market.fetch_day，不用金鑰）
     每天的「全市場快照」本來就包含當時還在交易、之後下市的公司 → 沒有倖存者偏差
     價格是原始收盤價（沒有還原除權息）：回測時單日漲跌超過 11% 的要當成除權息或減資跳過
存法：輸出資料夾/YYYY.json.gz：{日期: {代號: [開, 高, 低, 收, 張數, 外資, 投信]}}
     輸出資料夾/mg_YYYY.json.gz：{日期: {代號: 融資餘額張數}}（證交所 MI_MARGN、櫃買融資融券餘額；2026-11-26 加）
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


def margin_day(d):
    """一天的融資餘額（張）：上市 MI_MARGN＋上櫃融資融券餘額。回傳 ({代號: 張數}, 有沒有上櫃)；休市或抓不到回傳 (None, False)"""
    ymd, roc = d.strftime("%Y%m%d"), "%d/%02d/%02d" % (d.year - 1911, d.month, d.day)
    j = market.get("https://www.twse.com.tw/rwd/zh/marginTrading/MI_MARGN?date=%s&selectType=ALL&response=json" % ymd)
    if j.get("stat") != "OK":
        return None, False
    tabs = j.get("tables") or ([{"data": j.get("data"), "fields": j.get("fields")}] if j.get("data") else [])
    tabs = [t for t in tabs if any(market.keep_id(str(r[0]).strip()) for r in (t.get("data") or [])[:50])]  # 有股票代號的表
    tab = max(tabs, key=lambda t: len(t.get("data") or []), default=None)  # 個股明細是最大的那張表
    out = {}
    for r in (tab or {}).get("data") or []:  # [0] 代號 [1] 名稱 [2] 融資買進 [3] 賣出 [4] 現金償還 [5] 前日餘額 [6] 今日餘額（張）
        code = str(r[0]).strip()
        if market.keep_id(code) and len(r) > 6:
            v = market.num(r[6])
            if v is not None:
                out[code] = v
    time.sleep(3)
    otc = False
    try:
        o = market.get("https://www.tpex.org.tw/web/stock/margin_trading/margin_balance/margin_bal_result.php?l=zh-tw&o=json&d=%s" % roc)
        rows = o.get("aaData") or next((t.get("data") for t in (o.get("tables") or []) if t.get("data")), None) or []
        for r in rows:  # [0] 代號 [1] 名稱 [2] 前資餘額 [3] 資買 [4] 資賣 [5] 現償 [6] 資餘額（張）
            code = str(r[0]).strip()
            if market.keep_id(code) and len(r) > 6:
                v = market.num(r[6])
                if v is not None:
                    out[code] = v
                    otc = True
    except Exception as e:
        print(d, "上櫃融資抓取失敗：", str(e)[:100], flush=True)
    time.sleep(3)
    return (out or None), otc


def margins(days, budget):
    """把已有行情的日子補上融資餘額 → mg_YYYY.json.gz：{日期: {代號: 融資餘額張數}}；最多跑 budget 分鐘"""
    t0 = time.time()
    mp = os.path.join(OUT, "mg_meta.json")
    meta = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {"fail": {}, "no_otc": []}
    mg = {}
    for y in sorted({d[:4] for d in days}):
        p = os.path.join(OUT, "mg_%s.json.gz" % y)
        if os.path.exists(p):
            with gzip.open(p, "rt", encoding="utf-8") as f:
                mg[y] = json.load(f)
    have = {k for v in mg.values() for k in v}
    todo = [k for k in sorted(days, reverse=True) if (k not in have or k in meta["no_otc"]) and meta["fail"].get(k, 0) < 3]
    print("融資：已有 %d 天，還要抓 %d 天" % (len(have), len(todo)), flush=True)
    n, err, dirty = 0, 0, set()

    def flush():
        for y in dirty:
            p = os.path.join(OUT, "mg_%s.json.gz" % y)
            with gzip.open(p + ".tmp", "wt", encoding="utf-8", compresslevel=9) as f:
                json.dump(mg[y], f, separators=(",", ":"))
            os.replace(p + ".tmp", p)
        json.dump(meta, open(mp, "w", encoding="utf-8"), separators=(",", ":"))
        dirty.clear()

    for k in todo:
        if (time.time() - t0) / 60 > budget:
            print("融資：時間到，先存檔", flush=True)
            break
        try:
            rows, otc = margin_day(dt.date.fromisoformat(k))
            err = 0
        except Exception as e:
            err += 1
            print(k, "融資抓取失敗：", str(e)[:100], flush=True)
            if err >= 8:
                print("融資：連續失敗太多次，先停", flush=True)
                break
            time.sleep(30)
            continue
        if not rows:
            meta["fail"][k] = meta["fail"].get(k, 0) + 1
            continue
        mg.setdefault(k[:4], {})[k] = rows
        dirty.add(k[:4])
        nos = set(meta["no_otc"])
        (nos.discard if otc else nos.add)(k)
        meta["no_otc"] = sorted(nos)
        n += 1
        if n % SAVE_EVERY == 0:
            flush()
            print("融資進度：本次 %d 天，最新 %s，%.0f 分鐘" % (n, k, (time.time() - t0) / 60), flush=True)
    flush()
    print("融資：本次抓了 %d 天，共 %d 天" % (n, len({k for v in mg.values() for k in v})), flush=True)


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
        if (time.time() - t0) / 60 > MAX * 0.6:  # 留 4 成時間給融資
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
    try:  # 2026-11-26 使用者同意：融資餘額 10 年歷史（驗證「斷頭後法人接手」）
        margins(got, MAX - (time.time() - t0) / 60)
    except Exception as e:
        print("融資補抓失敗，略過：", type(e).__name__, str(e)[:100])


if __name__ == "__main__":
    main()
