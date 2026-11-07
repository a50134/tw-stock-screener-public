"""
tdcc.py - 集保大戶持股（臺灣集中保管結算所「集保戶股權分散表」，每週更新，免費、不用帳號）

資料：https://opendata.tdcc.com.tw/getOD.ashx?id=1-5（全部股票「最新一週」的持股分級）
開放資料只有最新一週，所以每晚抓一次、自己存成歷史（tdcc_hist.json，放在 site-data 分支），
再填進 data.json 每檔的 hw：[{d: 日期, big: 千張大戶持股 %, ret: 50 張以下散戶持股 %, bn: 千張大戶人數,
  bl: 千張大戶持有張數, hn: 總股東人數, sh: 集保總張數（約等於股本）}]，並用最新一週的總張數補上 shares（股本，張）
（網頁版的「大戶持股連續增加」等條件、晚上報告的籌碼分析都用這份）

持股分級：1～8 級＝1 股～5 萬股（50 張以下，散戶）；15 級＝100 萬股以上（千張大戶）；16 差異數調整；17 合計（總股東人數、總股數）

用法：python tdcc.py                    # 抓最新一週存進歷史
      python tdcc.py --merge data.json  # 再把歷史填進 data.json
"""
import csv
import io
import json
import os
import sys

import requests

DIR = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(DIR, "tdcc_hist.json")
URL = "https://opendata.tdcc.com.tw/getOD.ashx?id=1-5"
KEEP = 60  # 保留約一年多的週資料


def fetch():
    """回傳 (日期 YYYY-MM-DD, {代號: (千張大戶%, 散戶%, 千張大戶人數, 千張大戶張數, 總股東人數, 總張數)})"""
    r = requests.get(URL, timeout=120, headers={"User-Agent": "Mozilla/5.0"})
    r.raise_for_status()
    text = r.content.decode("utf-8-sig", errors="replace")
    rows = list(csv.reader(io.StringIO(text)))
    head = rows[0]
    col = lambda k: next(i for i, x in enumerate(head) if k in x)
    iD, iS, iL, iN, iP = col("日期"), col("代號"), col("分級"), col("人數"), col("比例")
    iQ = next((i for i, x in enumerate(head) if x.strip().startswith("股數")), None)
    out, day = {}, None
    for x in rows[1:]:
        if len(x) <= iP:
            continue
        try:
            lv, pct, n = int(x[iL]), float(x[iP]), int(x[iN].replace(",", ""))
            q = int(x[iQ].replace(",", "")) if iQ is not None else 0
        except ValueError:
            continue
        sid = x[iS].strip()
        day = day or x[iD].strip()
        a = out.setdefault(sid, [0.0, 0.0, 0, 0, 0, 0])
        if lv == 15:
            a[0], a[2], a[3] = pct, n, round(q / 1000)
        elif 1 <= lv <= 8:
            a[1] += pct
        elif lv == 17:
            a[4], a[5] = n, round(q / 1000)
    if not day:
        raise RuntimeError("集保資料是空的")
    d = "%s-%s-%s" % (day[:4], day[4:6], day[6:8])
    return d, {k: (round(v[0], 2), round(v[1], 2), v[2], v[3] or None, v[4] or None, v[5] or None) for k, v in out.items()}


def load(path=HIST):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {"dates": [], "s": {}}


def update(path=HIST):
    """抓最新一週加進歷史；同一週已經有就不重複"""
    h = load(path)
    d, now = fetch()
    if d in h["dates"]:  # 這週已經有了：用新抓的覆蓋（補上後來才加的欄位，例如股東人數、張數）
        i = h["dates"].index(d)
        for sid, v in now.items():
            a = h["s"].setdefault(sid, [None] * len(h["dates"]))
            a += [None] * (len(h["dates"]) - len(a))
            a[i] = list(v)
        json.dump(h, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
        print("集保大戶：%s 這週已經有了，更新欄位（%d 檔）" % (d, len(now)))
        return h
    h["dates"].append(d)
    n = len(h["dates"])
    for sid in set(h["s"]) | set(now):
        a = h["s"].setdefault(sid, [])
        a += [None] * (n - 1 - len(a))  # 之前沒有資料的週補空白
        a.append(list(now[sid]) if sid in now else None)
    if n > KEEP:
        h["dates"] = h["dates"][-KEEP:]
        h["s"] = {k: v[-KEEP:] for k, v in h["s"].items() if any(v[-KEEP:])}
    json.dump(h, open(path, "w", encoding="utf-8"), ensure_ascii=False, separators=(",", ":"))
    print("集保大戶：新增 %s 這週（%d 檔），歷史共 %d 週" % (d, len(now), len(h["dates"])))
    return h


def series(h, sid):
    a = h["s"].get(sid) or []
    g = lambda v, i: v[i] if len(v) > i else None  # 舊的週資料只有前 3 欄
    return [{"d": d, "big": v[0], "ret": v[1], "bn": v[2], "bl": g(v, 3), "hn": g(v, 4), "sh": g(v, 5)} for d, v in zip(h["dates"], a) if v]


def merge(data_path, path=HIST):
    """把集保歷史填進 data.json 每檔的 hw（ETF、沒有資料的略過）"""
    h = load(path)
    if not h["dates"]:
        print("沒有集保歷史，略過")
        return 0
    data = json.load(open(data_path, encoding="utf-8"))
    n = 0
    for s in data["stocks"]:
        hw = series(h, s["id"])
        if hw:
            s["hw"] = hw
            n += 1
            sh = next((x["sh"] for x in reversed(hw) if x.get("sh")), None)
            if sh and not s.get("shares"):
                s["shares"] = sh  # 股本（張）：給「法人買超占股本」等條件用
    json.dump(data, open(data_path, "w", encoding="utf-8"), ensure_ascii=False)
    print("集保大戶：%d 檔填進 %s（最新 %s）" % (n, os.path.basename(data_path), h["dates"][-1]))
    return n


if __name__ == "__main__":
    update()
    if "--merge" in sys.argv:
        merge(sys.argv[sys.argv.index("--merge") + 1])
