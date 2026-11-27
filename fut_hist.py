"""
fut_hist.py - 期交所期貨／選擇權籌碼長期歷史（2026-11-27 使用者想知道「散戶多空指標、跟散戶反著做會不會比較賺」）
資料要收齊才回測（使用者規則），所以先把期交所原始資料從 2007 年起補齊：
  台指期 TXF：外資淨未平倉口數（三大法人－區分各期貨契約）
  小台指 MTX：三大法人合計淨未平倉、全市場未沖銷契約數（期貨每日交易行情，一般盤、不含價差單）
    → 散戶多空比 = −三大法人淨未平倉 ÷ 全市場未平倉
  選擇權：未平倉賣權／買權比（pcRatio）
注意：期交所「三大法人」下載只給最近約 3 年；更早的外資台指期、小台法人用 FinMind 補（2018 年起），2018 年前沒有公開來源
存法：輸出資料夾/fut.json：{"days": {日期: {"tx_f", "mtx_inst", "mtx_oi", "pcr"}}, "done": [已補完的月份]}
每個月一段（期交所下載的日期區間限制），當月每次都重抓；最多跑 MAX 分鐘就存檔，下次接著補
用法：python fut_hist.py 輸出資料夾 [從哪一年=2007] [最多幾分鐘=30]
"""
import csv
import datetime as dt
import io
import json
import os
import sys
import time
import urllib.parse
import urllib.request

OUT = sys.argv[1] if len(sys.argv) > 1 else "hist"
START = int(sys.argv[2]) if len(sys.argv) > 2 else 2007
MAX = float(sys.argv[3]) if len(sys.argv) > 3 else 30
UA = {"User-Agent": "Mozilla/5.0"}
BASE = "https://www.taifex.com.tw/cht/3/"


def csv_rows(path, form):
    """POST 下載期交所 CSV（big5）→ (表頭, 資料列)；失敗重試 2 次"""
    body = urllib.parse.urlencode(form).encode()
    for k in range(3):
        try:
            req = urllib.request.Request(BASE + path, data=body, headers=dict(UA, **{"Content-Type": "application/x-www-form-urlencoded"}))
            with urllib.request.urlopen(req, timeout=60) as r:
                rows = list(csv.reader(io.StringIO(r.read().decode("big5", "replace"))))
            rows = [x for x in rows if x and any(c.strip() for c in x)]
            return ([c.strip() for c in rows[0]] if rows else []), rows[1:]
        except Exception as e:
            if k == 2:
                print(path, form.get("queryStartDate"), "抓取失敗：", str(e)[:100], flush=True)
            time.sleep(5)
    return [], []


def day(s):
    try:
        return dt.date.fromisoformat(s.strip().replace("/", "-")).isoformat()
    except ValueError:
        return None


def num(s):
    try:
        return float(str(s).replace(",", "").strip())
    except ValueError:
        return None


def col(head, *keys):
    return next((i for i, x in enumerate(head) if all(k in x for k in keys)), None)


def inst(a, b, cid):
    """{日期: {身份別: 淨未平倉口數}}"""
    head, rows = csv_rows("futContractsDateDown", {"queryStartDate": a, "queryEndDate": b, "commodityId": cid})
    iw, inet = col(head, "身份"), col(head, "未平倉", "口數", "淨額")
    out = {}
    for r in rows:
        if iw is None or inet is None or len(r) <= max(iw, inet):
            continue
        d, v = day(r[0]), num(r[inet])
        if d and v is not None:
            out.setdefault(d, {})[r[iw].strip()] = int(v)
    return out, head


def total_oi(a, b, cid="MTX"):
    """全市場未沖銷契約數（一般盤、不含價差單）{日期: 口數}"""
    head, rows = csv_rows("futDataDown", {"down_type": "1", "commodity_id": cid, "queryStartDate": a, "queryEndDate": b})
    idate, imon, ioi, isess = col(head, "日期"), col(head, "到期月份"), col(head, "未沖銷"), col(head, "時段")
    out = {}
    for r in rows:
        if None in (idate, imon, ioi) or len(r) <= max(idate, imon, ioi):
            continue
        if "/" in r[imon] or (isess is not None and len(r) > isess and r[isess].strip() not in ("一般", "")):
            continue
        d, v = day(r[idate]), num(r[ioi])
        if d and v:
            out[d] = out.get(d, 0) + int(v)
    return out, head


def pcr(a, b):
    head, rows = csv_rows("pcRatioDown", {"queryStartDate": a, "queryEndDate": b})
    ic = col(head, "未平倉", "比")
    out = {}
    for r in rows:
        if ic is not None and len(r) > ic:
            d, v = day(r[0]), num(r[ic])
            if d and v:
                out[d] = v / 100
    return out, head


def finmind_fill(F):
    """期交所三大法人下載只給最近約 3 年：更早的外資台指期、小台法人用 FinMind（2018 年起）補（只補缺的日子）"""
    tok = (os.environ.get("FINMIND_TOKEN") or "").strip()
    if not tok:
        print("沒有 FINMIND_TOKEN，略過 FinMind 補舊資料", flush=True)
        return
    sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
    import fetch_finmind
    fetch_finmind.TOKEN = tok
    for sid, key, who in (("TX", "tx_f", ("外資",)), ("MTX", "mtx_inst", ("外資", "投信", "自營"))):
        miss = [d for d, x in F["days"].items() if key not in x and d >= "2018-01-01"]
        if not miss:
            continue
        rows = fetch_finmind.get("TaiwanFuturesInstitutionalInvestors", sid, "2018-01-01", wait=False) or []
        net = {}
        for r in rows:
            n = r.get("institutional_investors") or ""
            lo, sh = r.get("long_open_interest_balance_volume"), r.get("short_open_interest_balance_volume")
            if any(w in n for w in who) and lo is not None and sh is not None and r.get("date"):
                net[r["date"]] = net.get(r["date"], 0) + lo - sh
        n = 0
        for d in miss:
            if d in net:
                F["days"][d][key] = net[d]
                n += 1
        print("FinMind 補 %s：%d 天（FinMind 共 %d 天）" % (key, n, len(net)), flush=True)


def main():
    os.makedirs(OUT, exist_ok=True)
    p = os.path.join(OUT, "fut.json")
    F = json.load(open(p, encoding="utf-8")) if os.path.exists(p) else {"days": {}, "done": []}
    done = set(F["done"])
    today = dt.date.today()
    months = []
    m = dt.date(START, 1, 1)
    while m <= today:
        months.append(m)
        m = (m.replace(day=28) + dt.timedelta(days=4)).replace(day=1)
    cur = today.strftime("%Y-%m")
    todo = [m for m in reversed(months) if m.strftime("%Y-%m") not in done or m.strftime("%Y-%m") == cur]  # 從最近往回補
    print("期貨歷史：已補 %d 個月，還要抓 %d 個月" % (len(done), len(todo)), flush=True)
    t0, n, first = time.time(), 0, True
    for m in todo:
        if (time.time() - t0) / 60 > MAX:
            print("期貨歷史：時間到，先存檔", flush=True)
            break
        e = min((m.replace(day=28) + dt.timedelta(days=4)).replace(day=1) - dt.timedelta(days=1), today)
        a, b = m.strftime("%Y/%m/%d"), e.strftime("%Y/%m/%d")
        tx, h1 = inst(a, b, "TXF")
        time.sleep(1.5)
        mi, _ = inst(a, b, "MXF")
        time.sleep(1.5)
        oi, h2 = total_oi(a, b, "MTX")
        time.sleep(1.5)
        pc, h3 = pcr(a, b)
        time.sleep(1.5)
        if first:
            print("欄位：法人", h1[:15], "｜每日行情", h2[:20], "｜P/C", h3, flush=True)
            first = False
        for d in set(tx) | set(mi) | set(oi) | set(pc):
            x = F["days"].setdefault(d, {})
            fx = next((v for k, v in (tx.get(d) or {}).items() if "外資" in k), None)
            if fx is not None:
                x["tx_f"] = fx
            if mi.get(d):
                x["mtx_inst"] = sum(mi[d].values())
            if oi.get(d):
                x["mtx_oi"] = oi[d]
            if pc.get(d):
                x["pcr"] = pc[d]
        key = m.strftime("%Y-%m")
        got = sum(1 for d in F["days"] if d.startswith(key))
        if key != cur and (got or m.year < 2007):
            done.add(key)
        n += 1
        if n % 6 == 0:
            F["done"] = sorted(done)
            json.dump(F, open(p, "w", encoding="utf-8"), separators=(",", ":"))
            print("期貨歷史進度：%s，%d 天" % (key, len(F["days"])), flush=True)
    F["done"] = sorted(done)
    try:
        finmind_fill(F)
    except Exception as e:
        print("FinMind 補舊資料失敗：", type(e).__name__, str(e)[:100], flush=True)
    json.dump(F, open(p, "w", encoding="utf-8"), separators=(",", ":"))
    D = sorted(F["days"])
    full = lambda k: sum(1 for d in D if k in F["days"][d])  # noqa: E731
    print("期貨歷史：共 %d 天（%s～%s）；外資台指期 %d 天、小台法人 %d 天、小台未平倉 %d 天、P/C %d 天" % (
        len(D), D[0] if D else "—", D[-1] if D else "—", full("tx_f"), full("mtx_inst"), full("mtx_oi"), full("pcr")), flush=True)


if __name__ == "__main__":
    main()
