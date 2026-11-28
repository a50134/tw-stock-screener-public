"""
rev_hist.py - 全市場月營收歷史（2026-11-28 使用者要的：「補月營收資料」，給「年底營收進度」等策略回測用）
資料：公開資訊觀測站「每月營業收入彙總表」（上市 sii、上櫃 otc；國內公司 _0、外國公司（KY）_1）
     每個月一頁就有當時全部公司 → 包含之後下市的公司，沒有倖存者偏差
存法：輸出資料夾/rev.json.gz：{"YYYY-MM": {代號: [當月營收, 今年累計營收]}}（千元）；rev_meta.json：{"fail": {頁面: 次數}}
已抓過的月份不重抓（最近 2 個月每次重抓，因為公司會更正）；最多跑 MAX 分鐘
用法：python rev_hist.py 輸出資料夾 [從哪一年=2014] [最多幾分鐘=40]
"""
import datetime as dt
import gzip
import html
import json
import os
import re
import sys
import time
import urllib.request

OUT = sys.argv[1] if len(sys.argv) > 1 else "hist"
START = int(sys.argv[2]) if len(sys.argv) > 2 else 2014
MAX = float(sys.argv[3]) if len(sys.argv) > 3 else 40
UA = {"User-Agent": "Mozilla/5.0"}


def fetch(url):
    for k in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=60) as r:
                b = r.read()
            for enc in ("utf-8", "big5", "cp950"):
                try:
                    return b.decode(enc)
                except UnicodeDecodeError:
                    pass
            return b.decode("big5", "replace")
        except Exception as e:
            if k == 2:
                print(url, "抓取失敗：", str(e)[:100], flush=True)
            time.sleep(5 * (k + 1))
    return None


def num(s):
    s = s.replace(",", "").strip()
    try:
        return float(s)
    except ValueError:
        return None


def parse(text):
    """→ {代號: [當月營收, 今年累計]}；欄位：代號 名稱 當月 上月 去年當月 上月% 去年% 當月累計 去年累計 前期% 備註"""
    out = {}
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", text, re.S | re.I):
        tds = [html.unescape(re.sub(r"<[^>]+>", "", x)).strip() for x in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        if len(tds) >= 8 and re.fullmatch(r"\d{4}[A-Z]?", tds[0]):
            rev, cum = num(tds[2]), num(tds[7])
            if rev is not None:
                out[tds[0]] = [rev, cum]
    return out


def main():
    os.makedirs(OUT, exist_ok=True)
    p, mp = os.path.join(OUT, "rev.json.gz"), os.path.join(OUT, "rev_meta.json")
    R = json.load(gzip.open(p, "rt", encoding="utf-8")) if os.path.exists(p) else {}
    meta = json.load(open(mp, encoding="utf-8")) if os.path.exists(mp) else {"fail": {}, "pages": {}}
    meta.setdefault("pages", {})
    today = dt.date.today()
    last = (today.replace(day=1) - dt.timedelta(days=1)).replace(day=1)  # 上個月（每月 10 日前公布）
    months, m = [], last
    while m.year >= START:
        months.append(m)
        m = (m - dt.timedelta(days=1)).replace(day=1)
    recent = {months[0].strftime("%Y-%m"), months[1].strftime("%Y-%m")} if len(months) > 1 else set()
    t0, n, first = time.time(), 0, True
    for m in months:
        ym = m.strftime("%Y-%m")
        for mk in ("sii", "otc"):
            for kind in ("0", "1"):
                page = "%s_%s_%s" % (ym, mk, kind)
                if (meta["pages"].get(page) and ym not in recent) or meta["fail"].get(page, 0) >= 3:
                    continue
                if (time.time() - t0) / 60 > MAX:
                    break
                url = "https://mops.twse.com.tw/nas/t21/%s/t21sc03_%d_%d_%s.html" % (mk, m.year - 1911, m.month, kind)
                text = fetch(url)
                rows = parse(text) if text else {}
                if first:
                    print("第一頁：", url, "長度", len(text or ""), "抓到", len(rows), "家", (text or "")[:120].replace("\n", " "), flush=True)
                    first = False
                if rows:
                    R.setdefault(ym, {}).update(rows)
                    meta["pages"][page] = len(rows)
                    meta["fail"].pop(page, None)
                elif kind == "1" and text and "查無" in text:
                    meta["pages"][page] = 0  # 那個月沒有外國公司的表
                else:
                    meta["fail"][page] = meta["fail"].get(page, 0) + 1
                n += 1
                time.sleep(2)
        if n and n % 24 == 0:
            json.dump(R, gzip.open(p, "wt", encoding="utf-8"), separators=(",", ":"))
            json.dump(meta, open(mp, "w", encoding="utf-8"))
            print("月營收進度：%s，%.0f 分鐘" % (ym, (time.time() - t0) / 60), flush=True)
    with gzip.open(p, "wt", encoding="utf-8") as f:
        json.dump(R, f, separators=(",", ":"))
    json.dump(meta, open(mp, "w", encoding="utf-8"))
    ks = sorted(R)
    print("月營收：本次抓 %d 頁；共 %d 個月（%s～%s）、%d 家；失敗 %d 頁" % (
        n, len(ks), ks[0] if ks else "—", ks[-1] if ks else "—", len({c for v in R.values() for c in v}), len(meta["fail"])), flush=True)


if __name__ == "__main__":
    main()
