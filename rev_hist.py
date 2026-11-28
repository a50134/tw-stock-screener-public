"""
rev_hist.py - 全市場月營收歷史（2026-11-28 使用者要的：「補月營收資料」，給「年底營收進度」等策略回測用）
資料：FinMind TaiwanStockMonthRevenue（一檔一次，2014 年起）。代號清單用 hist/meta.json（2014 年起出現過的全部上市櫃股票，含已下市）
     公開資訊觀測站彙總表從 GitHub 連不上（拒絕連線／舊網址 404），2026-11-28 改用 FinMind
存法：輸出資料夾/rev.json.gz：{"YYYY-MM": {代號: 當月營收（元）}}；rev_meta.json：{"done": {代號: 抓的月份}, "empty": [FinMind 沒資料的代號]}
FinMind 每小時有請求上限：碰到就等 10 分鐘（時間夠的話），最多跑 MAX 分鐘，下次接著補
補完之後：每個月 11 日後，還在交易的公司重抓一次（拿到上個月營收）
用法：FINMIND_TOKEN=… python rev_hist.py 輸出資料夾 [從哪一年=2014] [最多幾分鐘=150]
"""
import datetime as dt
import gzip
import json
import os
import sys
import time

import requests

OUT = sys.argv[1] if len(sys.argv) > 1 else "hist"
START = int(sys.argv[2]) if len(sys.argv) > 2 else 2014
MAX = float(sys.argv[3]) if len(sys.argv) > 3 else 150
API = "https://api.finmindtrade.com/api/v4/data"
TOKEN = (os.environ.get("FINMIND_TOKEN") or "").strip()


def get(sid, t0):
    """→ (資料列, 狀態)；狀態：ok／limit／fail"""
    params = {"dataset": "TaiwanStockMonthRevenue", "data_id": sid, "start_date": "%d-01-01" % START}
    if TOKEN:
        params["token"] = TOKEN
    for k in range(3):
        try:
            r = requests.get(API, params=params, timeout=40)
            j = r.json() if r.headers.get("content-type", "").startswith("application/json") else {}
            if r.status_code == 200 and j.get("status") == 200:
                return j.get("data") or [], "ok"
            msg = str(j.get("msg", r.status_code))
            if r.status_code == 402 or "limit" in msg.lower():
                return [], "limit"
        except requests.RequestException:
            pass
        time.sleep(3 * (k + 1))
    return [], "fail"


def save(R, meta, p, mp):
    with gzip.open(p + ".tmp", "wt", encoding="utf-8") as f:
        json.dump(R, f, separators=(",", ":"))
    os.replace(p + ".tmp", p)
    json.dump(meta, open(mp, "w", encoding="utf-8"), separators=(",", ":"))


def main():
    os.makedirs(OUT, exist_ok=True)
    p, mp = os.path.join(OUT, "rev.json.gz"), os.path.join(OUT, "rev_meta.json")
    R = {}
    if os.path.exists(p):
        with gzip.open(p, "rt", encoding="utf-8") as f:
            R = json.load(f)
    meta = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {}
    if "done" not in meta:  # 舊版（公開資訊觀測站）的紀錄不要了
        meta = {"done": {}, "empty": []}
    names = json.load(open(os.path.join(OUT, "meta.json"), encoding="utf-8"))["names"]
    today = dt.date.today()
    cur = today.strftime("%Y-%m")
    recent = (today - dt.timedelta(days=15)).isoformat()
    codes = sorted(c for c in names if not c.startswith("0") and len(c) == 4)  # 一般股票（排除 ETF、權證）
    empty = set(meta["empty"])
    todo = [c for c in codes if c not in meta["done"] and c not in empty]
    if not todo and today.day >= 11:  # 補完了：每月 11 日後，還在交易的公司重抓一次
        todo = [c for c in codes if c not in empty and names[c][3] >= recent and meta["done"].get(c, "") < cur]
    print("月營收：已抓 %d 檔、FinMind 沒資料 %d 檔，這次要抓 %d 檔（代號共 %d 檔，含已下市）%s" % (
        len(meta["done"]), len(empty), len(todo), len(codes), "" if TOKEN else "；沒有 FINMIND_TOKEN"), flush=True)
    t0, n, fails = time.time(), 0, 0
    for c in todo:
        left = MAX - (time.time() - t0) / 60
        if left < 1:
            print("月營收：時間到，先存檔", flush=True)
            break
        rows, st = get(c, t0)
        if st == "limit":
            save(R, meta, p, mp)
            if left < 13:
                print("月營收：碰到 FinMind 每小時上限，時間不夠等，先停", flush=True)
                break
            print("月營收：碰到 FinMind 每小時上限，等 10 分鐘（本次已抓 %d 檔）" % n, flush=True)
            time.sleep(600)
            rows, st = get(c, t0)
            if st != "ok":
                print("月營收：還是不行，先停", flush=True)
                break
        if st == "fail":
            fails += 1
            if fails >= 10:
                print("月營收：連續失敗太多次，先停", flush=True)
                break
            continue
        fails = 0
        got = 0
        for r in rows:
            y, m, v = r.get("revenue_year"), r.get("revenue_month"), r.get("revenue")
            if y and m and v is not None:
                R.setdefault("%04d-%02d" % (int(y), int(m)), {})[c] = v
                got += 1
        if got:
            meta["done"][c] = cur
        else:
            empty.add(c)
            meta["empty"] = sorted(empty)
        n += 1
        if n % 50 == 0:
            save(R, meta, p, mp)
            print("月營收進度：本次 %d 檔，%.0f 分鐘" % (n, (time.time() - t0) / 60), flush=True)
    meta["empty"] = sorted(empty)
    save(R, meta, p, mp)
    ks = sorted(R)
    dl = sum(1 for c in meta["done"] if names.get(c, [0, 0, 0, "9999"])[3] < recent)
    print("月營收：本次抓 %d 檔；共 %d 檔有資料（其中已下市 %d 檔）、%d 個月（%s～%s）；FinMind 沒資料 %d 檔" % (
        n, len(meta["done"]), dl, len(ks), ks[0] if ks else "—", ks[-1] if ks else "—", len(empty)), flush=True)


if __name__ == "__main__":
    main()
