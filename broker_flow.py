"""
broker_flow.py - 查詢個股主力進出（前 15 大買超／賣超券商分點），資料來自富邦證券公開頁面

用法：
  python broker_flow.py 2609 3711          # 近一日
  python broker_flow.py 2609 --days 5      # 近五日
  python broker_flow.py                    # 不給代號：讀 report_line.txt（最近一次每日報告的篩選名單）
  python broker_flow.py 2609 --out broker.txt   # 另存成文字檔（可再用 send_report.py 發送）
  python broker_flow.py --brief --out broker_brief.txt   # 只要結論（給 LINE／Discord）
  python broker_flow.py --json broker.json       # 產生給網頁匯入的資料（近一日＋近五日）

只在需要時手動執行；不要放進自動排程大量抓取。
"""
import html
import json
import re
import ssl
import sys
import time
import urllib.request

PERIOD = {1: "", 5: "_2"}  # 富邦頁面：預設近一日，_2 為近五日
FOREIGN = re.compile(r"摩根|美林|高盛|瑞銀|花旗|麥格理|野村|港商|新加坡|法銀|巴黎|德意志|匯豐|瑞士|大和|星展|美商")


def fetch(sid, days):
    url = "https://fubon-ebrokerdj.fbs.com.tw/z/zc/zco/zco_%s%s.djhtm" % (sid, PERIOD[days])
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.urlopen(req, timeout=30, context=ssl.create_default_context()) as r:
        return r.read().decode("big5", "replace")


def num(s):
    s = s.replace(",", "").replace("%", "").strip()
    return float(s) if re.fullmatch(r"-?[\d.]+", s) else None


def parse(page):
    rows = re.findall(r"<tr[^>]*>(.*?)</tr>", page, re.S | re.I)
    cells = [[html.unescape(re.sub(r"<[^>]+>", "", c)).strip() for c in re.findall(r"<td[^>]*>(.*?)</td>", r, re.S | re.I)] for r in rows]
    buy, sell, info = [], [], {}
    for c in cells:
        if len(c) == 10 and c[0] != "買超券商":
            if c[0] and num(c[3]) is not None:
                buy.append({"name": c[0], "net": num(c[3]), "pct": num(c[4])})
            if c[5] and num(c[8]) is not None:
                sell.append({"name": c[5], "net": num(c[8]), "pct": num(c[9])})
        elif len(c) == 4 and c[0] in ("合計買超張數", "平均買超成本"):
            info[c[0]], info[c[2]] = num(c[1]), num(c[3])
    m = re.search(r"最後更新日：([\d/]+)", page)
    t = re.search(r"<title>(.*?)</title>", page, re.S | re.I)
    name = re.search(r"([^\s>]+)\(\d{4,6}\)", page)
    return {"date": m.group(1) if m else "", "name": name.group(1) if name else "", "buy": buy, "sell": sell, "info": info,
            "title": t.group(1).strip() if t else ""}


def stats(d):
    b, s, i = d["buy"], d["sell"], d["info"]
    if not b and not s:
        return None
    tb, ts = i.get("合計買超張數") or sum(x["net"] for x in b), i.get("合計賣超張數") or sum(x["net"] for x in s)
    conc = sum(x["pct"] or 0 for x in b) - sum(x["pct"] or 0 for x in s)
    fnet = sum(x["net"] for x in b if FOREIGN.search(x["name"])) - sum(x["net"] for x in s if FOREIGN.search(x["name"]))
    return {"net": round(tb - ts), "buy_total": tb, "sell_total": ts, "conc": round(conc, 2), "foreign": round(fnet),
            "buy_avg": i.get("平均買超成本"), "sell_avg": i.get("平均賣超成本"),
            "buy": [{"name": x["name"], "net": x["net"], "foreign": bool(FOREIGN.search(x["name"]))} for x in b[:15]],
            "sell": [{"name": x["name"], "net": x["net"], "foreign": bool(FOREIGN.search(x["name"]))} for x in s[:15]]}


def verdict(conc):
    return "偏多" if conc >= 5 else "偏空" if conc <= -5 else "不明顯"


def brief_line(sid, name, d1, d5):
    v = verdict(d5["conc"])
    icon = {"偏多": "🔺", "偏空": "🔻", "不明顯": "➖"}[v]
    return "{} {} {}：近五日主力{}（{:+,} 張、集中度 {:+.1f}%，其中外資券商 {:+,} 張）；近一日 {:+,} 張".format(
        icon, sid, name, v, d5["net"], d5["conc"], d5["foreign"], d1["net"])


def summarize(sid, d, days):
    b, s, i = d["buy"], d["sell"], d["info"]
    if not b and not s:
        return "%s：查無主力進出資料（代號錯誤或非上市櫃股票）" % sid
    tb, ts = i.get("合計買超張數") or sum(x["net"] for x in b), i.get("合計賣超張數") or sum(x["net"] for x in s)
    conc = sum(x["pct"] or 0 for x in b) - sum(x["pct"] or 0 for x in s)
    fnet = sum(x["net"] for x in b if FOREIGN.search(x["name"])) - sum(x["net"] for x in s if FOREIGN.search(x["name"]))
    tag = lambda x: x["name"] + ("(外)" if FOREIGN.search(x["name"]) else "")
    L = ["【%s %s】近%s日主力進出（資料日 %s）" % (sid, d["name"], "一" if days == 1 else "五", d["date"]),
         "主力買賣超 %+d 張（前15買超 %d／前15賣超 %d），集中度 %+.2f%%" % (tb - ts, tb, ts, conc),
         "主力平均成本：買超 %s／賣超 %s；前15名中外資券商合計 %+d 張" % (i.get("平均買超成本"), i.get("平均賣超成本"), fnet),
         "買超前5：" + "、".join("%s +%d" % (tag(x), x["net"]) for x in b[:5]),
         "賣超前5：" + "、".join("%s -%d" % (tag(x), x["net"]) for x in s[:5]),
         "判讀：" + ("主力偏多，籌碼往少數券商集中" if conc >= 5 else "主力偏空，籌碼在出貨" if conc <= -5 else "主力方向不明顯")]
    return "\n".join(L)


def codes_from_report(path="report_line.txt"):
    try:
        with open(path, encoding="utf-8") as f:
            return re.findall(r"^[🟢🟡🔴⚪]\s*(\d{4,6})\s", f.read(), re.M)
    except FileNotFoundError:
        return []


def main():
    args, opt, codes = sys.argv[1:], {}, []
    it = iter(args)
    for a in it:
        if a in ("--days", "--out", "--json"):
            opt[a] = next(it, "")
        else:
            codes.append(a)
    days = int(opt.get("--days", 1))
    brief, jpath = "--brief" in codes, opt.get("--json")
    codes = [c for c in codes if c != "--brief"]
    if days not in PERIOD:
        sys.exit("--days 只支援 1 或 5")
    out = opt.get("--out")
    if not codes:
        codes = codes_from_report()
        if not codes:
            sys.exit("請給股票代號，或先產生每日報告（report_line.txt）")
    if brief or jpath:  # 近一日＋近五日都抓
        res, lines, date = {}, [], ""
        for n, sid in enumerate(codes):
            try:
                if n:
                    time.sleep(1.5)
                p1 = parse(fetch(sid, 1))
                time.sleep(1.5)
                p5 = parse(fetch(sid, 5))
                d1, d5 = stats(p1), stats(p5)
                if not (d1 and d5):
                    lines.append("❔ %s：查無主力進出資料" % sid)
                    continue
                date = p1["date"].replace("/", "-")
                res[sid] = {"name": p1["name"], "date": date, "d1": d1, "d5": d5, "verdict": verdict(d5["conc"])}
                lines.append(brief_line(sid, p1["name"], d1, d5))
            except Exception as e:
                lines.append("❔ %s：查詢失敗（%s）" % (sid, type(e).__name__))
        if jpath:
            with open(jpath, "w", encoding="utf-8") as f:
                json.dump({"source": "富邦證券", "date": date, "broker": res}, f, ensure_ascii=False, indent=1)
        text = ("📊 主力進出結論（資料日 %s）\n" % date + "\n".join(lines)
                + "\n（前 15 大券商分點；集中度 ≥ +5% 偏多、≤ −5% 偏空。不是投資建議）")
        if out:
            with open(out, "w", encoding="utf-8") as f:
                f.write(text)
        sys.stdout.reconfigure(encoding="utf-8")
        print(text)
        return
    parts = []
    for n, sid in enumerate(codes):
        if n:
            time.sleep(1.5)  # 放慢速度，避免對網站造成負擔
        try:
            parts.append(summarize(sid, parse(fetch(sid, days)), days))
        except Exception as e:
            parts.append("%s：查詢失敗（%s）" % (sid, type(e).__name__))
    text = "📊 主力進出（富邦證券資料，前 15 大券商分點）\n\n" + "\n\n".join(parts) + "\n\n主力買賣超只看前 15 大券商，單日方向參考價值有限，請搭配連續多日觀察。"
    if out:
        with open(out, "w", encoding="utf-8") as f:
            f.write(text)
    sys.stdout.reconfigure(encoding="utf-8")
    print(text)


if __name__ == "__main__":
    main()
