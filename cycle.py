"""
cycle.py - 循環股「近幾年平均低點／平均高點」（低點買、高點賣用）
每檔抓每年的最高價、最低價，取最近 5 個完整年度的平均：
  平均低點附近（+10% 以內）→ 低檔區，可分批買；平均高點附近（−10% 以內）→ 高檔區，分批賣
資料：證交所「個股年成交資訊」FMNPTK（上市）；抓不到（上櫃）改用 FinMind 日K 自己算每年高低
結果存 cycle_bands.json（每月更新一次就夠，cycle.yml 排程）

用法：python cycle.py            # 循環股（stock_profiles.json 寫「循環股」的）＋持股
      python cycle.py 2603 2609  # 只抓指定股票
"""
import datetime as dt
import json
import os
import sys
import time

import requests

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.join(DIR, "cycle_bands.json")
YEARS = 5
UA = {"User-Agent": "Mozilla/5.0"}


def num(x):
    try:
        return float(str(x).replace(",", ""))
    except ValueError:
        return None


def twse_years(sid):
    """上市股票每年最高、最低價 {西元年: [高, 低]}"""
    r = requests.get("https://www.twse.com.tw/rwd/zh/afterTrading/FMNPTK", params={"stockNo": sid, "response": "json"},
                     headers=UA, timeout=30)
    j = r.json()
    if j.get("stat") != "OK" or not j.get("data"):
        return {}
    f = j.get("fields") or []
    ih = next(i for i, x in enumerate(f) if "最高" in x)
    il = next(i for i, x in enumerate(f) if "最低" in x)
    out = {}
    for row in j["data"]:
        y, hi, lo = int(str(row[0]).strip()) + 1911, num(row[ih]), num(row[il])
        if hi and lo:
            out[y] = [hi, lo]
    return out


def finmind_years(sid, first):
    """上櫃等證交所沒有的：用 FinMind 日K 算每年高低"""
    import fetch_finmind
    fetch_finmind.TOKEN = fetch_finmind.TOKEN or os.environ.get("FINMIND_TOKEN", "").strip()
    out = {}
    for d in fetch_finmind.get("TaiwanStockPrice", sid, "%d-01-01" % first):
        y, hi, lo = int(d["date"][:4]), d.get("max"), d.get("min")
        if not hi or not lo:
            continue
        a = out.setdefault(y, [hi, lo])
        a[0], a[1] = max(a[0], hi), min(a[1], lo)
    return out


def band(years, this_year):
    """最近 YEARS 個完整年度的平均高點、平均低點"""
    ys = sorted(y for y in years if y < this_year)[-YEARS:]
    if len(ys) < 3:  # 不到 3 年資料不準，不算
        return None
    return {"avg_hi": round(sum(years[y][0] for y in ys) / len(ys), 2), "avg_lo": round(sum(years[y][1] for y in ys) / len(ys), 2),
            "from": ys[0], "to": ys[-1], "years": {str(y): years[y] for y in sorted(years)}}


def targets():
    prof = json.load(open(os.path.join(DIR, "stock_profiles.json"), encoding="utf-8"))
    ids = [k for k, v in prof.items() if str(v.get("cyc", "")).startswith("循環股")]
    try:
        import exits
        ids += [k for k in exits.holdings(json.load(open(os.path.join(DIR, "sop_config.json"), encoding="utf-8")))
                if str(prof.get(k, {}).get("cyc", "")).startswith(("循環股", "偏循環"))]
    except Exception as e:
        print("讀持股失敗，略過：", e)
    return list(dict.fromkeys(ids))


def main():
    ids = [a for a in sys.argv[1:] if a.isdigit()] or targets()
    this_year = dt.date.today().year
    old = json.load(open(OUT, encoding="utf-8")) if os.path.exists(OUT) else {}
    bands = old.get("bands", {})
    ok = 0
    for i, sid in enumerate(ids):
        ys, src = {}, "twse"
        try:
            ys = twse_years(sid)
        except Exception as e:
            print(sid, "證交所失敗：", e)
        time.sleep(3)  # 證交所每 5 秒最多 3 次
        if len(ys) < 4:
            try:
                ys, src = finmind_years(sid, this_year - YEARS - 1), "finmind"
            except Exception as e:
                print(sid, "FinMind 失敗：", e)
        b = band(ys, this_year)
        if b:
            b["src"] = src
            bands[sid] = b
            ok += 1
            print("%s 近%d年平均低點 %s、平均高點 %s（%s）" % (sid, b["to"] - b["from"] + 1, b["avg_lo"], b["avg_hi"], src), flush=True)
        else:
            print(sid, "資料不足 3 年，略過", flush=True)
    json.dump({"date": dt.date.today().isoformat(), "years": YEARS, "bands": bands}, open(OUT, "w", encoding="utf-8"),
              ensure_ascii=False, indent=1)
    print("完成：%d/%d 檔" % (ok, len(ids)))
    if ok == 0:
        sys.exit(1)


if __name__ == "__main__":
    main()
