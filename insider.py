"""
insider.py - 內部人（董監事、經理人、大股東）申報資料（證交所／櫃買中心開放資料，免費、不用帳號）

兩種資料：
  1. 每日「內部人持股轉讓事前申報」：內部人要賣（轉讓）股票前必須先申報 → 有人申報要賣＝利空提醒
  2. 每月「董事、監察人持股餘額」：董監持股合計比上個月增加＝內部人在買／沒賣；減少＝在賣
開放資料只有最新一天／最新一個月，所以每晚抓一次、自己存成歷史（insider_hist.json，放在 site-data 分支），
再填進 data.json 每檔的 ins：{sell30: 近 30 天申報轉讓張數, n30: 筆數, last: 最近幾筆, dh: [[年月, 董監持股張數], …]}

資料網址從證交所／櫃買中心的 API 說明檔（swagger）自動找（名稱有變也找得到），找不到才用預設網址。

用法：python insider.py                    # 抓最新一天存進歷史
      python insider.py --merge data.json  # 再把歷史填進 data.json
      python insider.py --probe            # 只印找到的網址和欄位名稱（檢查用）
"""
import datetime as dt
import json
import os
import sys

import requests

DIR = os.path.dirname(os.path.abspath(__file__))
HIST = os.path.join(DIR, "insider_hist.json")
UA = {"User-Agent": "Mozilla/5.0", "Accept": "application/json"}
SRC = [  # (名稱, API 根網址, swagger, 預設：事前申報, 預設：董監持股)
    ("上市", "https://openapi.twse.com.tw/v1", "https://openapi.twse.com.tw/v1/swagger.json", "/opendata/t187ap12_L", "/opendata/t187ap11_L"),
    ("上櫃", "https://www.tpex.org.tw/openapi/v1", "https://www.tpex.org.tw/openapi/swagger.json", "/mopsfin_t187ap12_O", "/mopsfin_t187ap11_O"),
]
KEEP_DAYS = 400  # 事前申報保留一年多
KEEP_MONTHS = 36  # 董監持股保留 3 年


def find_paths(swagger_url, d_tr, d_dh):
    """從 swagger 找「事前申報－持股轉讓日報表」和「董事監察人持股餘額」的網址"""
    tr = dh = None
    try:
        sw = requests.get(swagger_url, timeout=60, headers=UA).json()
        for p, m in (sw.get("paths") or {}).items():
            g = m.get("get") or {}
            txt = (g.get("summary") or "") + (g.get("description") or "")
            if "事前申報" in txt and "轉讓日報" in txt and "未轉讓" not in txt and not tr:
                tr = p
            if ("董事" in txt or "董監" in txt) and "持股餘額" in txt and not dh:
                dh = p
    except Exception as e:
        print("  ! 讀不到 API 說明檔，用預設網址：", type(e).__name__)
    return tr or d_tr, dh or d_dh


def get(url):
    r = requests.get(url, timeout=120, headers=UA)
    r.raise_for_status()
    j = r.json()
    return j if isinstance(j, list) else []


def key(row, *must, no=()):
    """找欄位名稱：要包含 must 每個字、不能包含 no 的字"""
    for k in row:
        if all(m in k for m in must) and not any(n in k for n in no):
            return k
    return None


def num(x):
    try:
        return float(str(x).replace(",", "").strip() or 0)
    except ValueError:
        return 0.0


def roc_date(x):
    """1151030 / 115/10/30 / 2026-10-30 → 2026-10-30"""
    s = "".join(ch for ch in str(x) if ch.isdigit())
    if len(s) == 8 and s.startswith("20"):
        return "%s-%s-%s" % (s[:4], s[4:6], s[6:])
    if len(s) == 7:
        return "%d-%s-%s" % (int(s[:3]) + 1911, s[3:5], s[5:])
    return None


def roc_month(x):
    s = "".join(ch for ch in str(x) if ch.isdigit())
    if len(s) == 5:
        return "%d-%s" % (int(s[:3]) + 1911, s[3:])
    if len(s) == 6 and s.startswith("20"):
        return "%s-%s" % (s[:4], s[4:])
    if len(s) == 7:  # 1151001 這種日期
        return "%d-%s" % (int(s[:3]) + 1911, s[3:5])
    return None


def parse_tr(rows, today):
    """事前申報 → [{sid, d, who, role, how, sh(股)}]"""
    out = []
    for r in rows:
        kc = key(r, "代號")
        ksh = key(r, "轉讓股數") or key(r, "股數", no=("目前", "持有", "最大", "設質"))
        if not kc or not ksh:
            continue
        kd = key(r, "申報日期") or key(r, "日期", no=("有效", "期間"))
        kw, kr = key(r, "姓名"), key(r, "身分")
        kh = next((k for k in r if k.endswith("轉讓方式")), None) or key(r, "轉讓方式", no=("股數",))
        sh = num(r[ksh])
        if sh <= 0:
            continue
        out.append({"sid": str(r[kc]).strip(), "d": (roc_date(r[kd]) if kd else None) or today,
                    "who": str(r.get(kw, "")).strip()[:12], "role": str(r.get(kr, "")).strip()[:10],
                    "how": str(r.get(kh, "")).strip()[:10], "sh": sh})
    return out


def parse_dh(rows):
    """董監持股餘額 → (年月, {代號: 董監持股合計(股)})"""
    tot, ym = {}, None
    for r in rows:
        kc = key(r, "代號")
        kh = key(r, "目前持股", no=("設質", "比例", "%")) or key(r, "持股", no=("選任", "設質", "比例", "%"))
        if not kc or not kh:
            continue
        km = key(r, "資料年月") or key(r, "年月") or key(r, "出表日期")
        ym = ym or (roc_month(r[km]) if km else None)
        sid = str(r[kc]).strip()
        tot[sid] = tot.get(sid, 0) + num(r[kh])
    return ym, tot


def load(path=HIST):
    try:
        return json.load(open(path, encoding="utf-8"))
    except Exception:
        return {"tr": [], "dh": {}}


def update(path=HIST, probe=False):
    h = load(path)
    today = dt.date.today().isoformat()
    seen = {(x["sid"], x["d"], x["who"], x["sh"], x["how"]) for x in h["tr"]}
    ntr = ndh = 0
    for name, base, sw, d_tr, d_dh in SRC:
        p_tr, p_dh = find_paths(sw, d_tr, d_dh)
        for label, p in (("事前申報", p_tr), ("董監持股", p_dh)):
            try:
                rows = get(base + p)
            except Exception as e:
                print("  ! %s%s抓取失敗：%s" % (name, label, type(e).__name__))
                continue
            if probe:
                print("%s %s：%s，%d 筆，欄位：%s" % (name, label, p, len(rows), "、".join(rows[0].keys()) if rows else "（空的）"))
            if label == "事前申報":
                for x in parse_tr(rows, today):
                    k = (x["sid"], x["d"], x["who"], x["sh"], x["how"])
                    if k not in seen:
                        seen.add(k)
                        h["tr"].append(x)
                        ntr += 1
            else:
                ym, tot = parse_dh(rows)
                if ym and tot:
                    for sid, v in tot.items():
                        h["dh"].setdefault(sid, {})[ym] = round(v)
                    ndh += len(tot)
    cut = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    h["tr"] = [x for x in h["tr"] if x["d"] >= cut]
    for sid in list(h["dh"]):
        ks = sorted(h["dh"][sid])[-KEEP_MONTHS:]
        h["dh"][sid] = {k: h["dh"][sid][k] for k in ks}
    json.dump(h, open(path, "w", encoding="utf-8"), ensure_ascii=False)
    print("內部人申報：新增事前申報 %d 筆（共 %d 筆）、董監持股 %d 檔" % (ntr, len(h["tr"]), ndh))
    return h


def summary(h, sid, asof=None):
    """單一股票：近 30 天申報轉讓、董監持股近幾個月"""
    asof = asof or dt.date.today().isoformat()
    c30 = (dt.date.fromisoformat(asof) - dt.timedelta(days=30)).isoformat()
    tr = sorted([x for x in h["tr"] if x["sid"] == sid and x["d"] >= c30], key=lambda x: x["d"])
    dh = sorted((h["dh"].get(sid) or {}).items())[-6:]
    if not tr and not dh:
        return None
    return {"sell30": round(sum(x["sh"] for x in tr) / 1000), "n30": len(tr),
            "last": [{"d": x["d"], "who": x["who"], "role": x["role"], "how": x["how"], "lot": round(x["sh"] / 1000)} for x in tr[-3:]],
            "dh": [[k, round(v / 1000)] for k, v in dh]}


def merge(data_path, path=HIST):
    h = load(path)
    d = json.load(open(data_path, encoding="utf-8"))
    asof = d.get("asOf") if len(str(d.get("asOf", ""))) == 10 else None
    n = 0
    for s in d["stocks"]:
        x = summary(h, s["id"], asof)
        if x:
            s["ins"] = x
            n += 1
    json.dump(d, open(data_path, "w", encoding="utf-8"), ensure_ascii=False)
    print("內部人申報：填入 %d 檔" % n)


def text(ins):
    """給報告用的一句話；沒有值得說的回傳空字串"""
    if not ins:
        return ""
    t = []
    if ins.get("n30"):
        t.append("內部人近 30 天申報要賣 %s 張（%d 筆，最近：%s）" % ("{:,}".format(ins["sell30"]), ins["n30"], "、".join(
            "%s %s%s %s張" % (x["d"][5:].replace("-", "/"), x["role"], x["how"] and "（%s）" % x["how"], "{:,}".format(x["lot"])) for x in ins["last"][-2:])))
    dh = ins.get("dh") or []
    if len(dh) >= 2 and dh[-2][1]:
        ch = dh[-1][1] - dh[-2][1]
        if abs(ch) >= max(1, dh[-2][1] * 0.001):
            t.append("董監持股 %s 月比上月%s %s 張" % (dh[-1][0][5:].lstrip("0"), "增加" if ch > 0 else "減少", "{:,}".format(abs(ch))))
        else:
            t.append("董監持股 %s 月跟上月差不多" % dh[-1][0][5:].lstrip("0"))
    return "；".join(t)


if __name__ == "__main__":
    if "--merge" in sys.argv:
        merge(sys.argv[sys.argv.index("--merge") + 1])
    else:
        update(probe="--probe" in sys.argv)
