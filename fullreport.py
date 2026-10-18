"""
fullreport.py - 完整版報告（Word 檔）：全部入選股票都列出、每檔詳細說明＋買賣建議
產生 report_full.json，再由 build_docx.js 轉成「條件選股室_日期.docx」（當 Discord 附檔）

用法：python fullreport.py   （讀 data.json、sop_plan.json、sop_config.json、stock_profiles.json）
"""
import json
import os
import subprocess

import analysis
import review

DIR = os.path.dirname(os.path.abspath(__file__))


def stock_item(s, t, prof, row=None, hold=None):
    """一檔的詳細內容：標題＋逐行說明（沿用 analysis.block）"""
    lines = analysis.block(s, analysis.facts(s, t), prof, row, hold).split("\n")
    return {"head": lines[0], "lines": [x.lstrip("・") for x in lines[1:]], "advice": analysis.advise(s, t, row) if not hold else "見持股賣出提醒"}


def build(data, cfg, plan, profiles, private=True):
    by = {s["id"]: s for s in data["stocks"]}
    t = len(data["dates"]) - 1
    rows = [r for r in plan.get("rows", []) if r.get("lo") and r.get("stop") and r["id"] in by]
    key = lambda r: -(r.get("score") or 0)
    ok = sorted([r for r in rows if r.get("state") == "ok"], key=key)
    wait = sorted([r for r in rows if r.get("state") != "ok"], key=key)
    lab = lambda r, d: "⚪ 先觀望" if r.get("state") == "hold" else d
    R = {"date": data["asOf"], "risk": plan.get("risk", "—"), "count": len(rows), "summary": [], "sections": []}
    for grp, label in ((ok, "🟢 可買"), (wait, "🟡 等拉回")):
        for r in grp:
            R["summary"].append({"id": r["id"], "name": r["name"], "close": analysis.px(r["prev"]), "act": lab(r, label),
                                 "zone": "%s～%s" % (analysis.px(r["lo"]), analysis.px(r["hi"])), "stop": analysis.px(r["stop"]),
                                 "t1": analysis.px(r["t1"]) if r.get("t1") else "—", "grade": "%s %s" % (r.get("grade", ""), r.get("score", "")),
                                 "strat": "、".join(r.get("strategies") or [])})
    macro = [n.get("title", "") for n in (data.get("macro") or [])[:8]]
    if macro:
        R["sections"].append({"title": "國際情勢（今晚新聞）", "intro": "國際風險：%s" % R["risk"], "items": [], "bullets": macro})
    if private:
        import exits
        xt, _ = exits.build(data, cfg, profiles)
        if xt:
            R["sections"].append({"title": "🔔 持股賣出提醒（只有你看得到）", "intro": "", "items": [], "bullets": xt.split("\n")[1:]})
    cyc = review.cycle_alerts(data, profiles)
    if cyc:
        cl = cyc.split("\n")
        R["sections"].append({"title": "🔄 循環股谷底轉強", "intro": cl[1] if len(cl) > 1 else "", "items": [], "bullets": [x.strip("・ ") for x in cl[2:]]})
    for grp, title, intro in ((ok, "🟢 可買（依健檢分數排序）", "價格在參考買進區間內可以分批買，收盤跌破停損就出場；國際風險高時只買一半。"),
                              (wait, "🟡 等拉回再買", "現在價格偏高，等跌回買進區間再買；不要追高。")):
        if grp:
            R["sections"].append({"title": title, "intro": intro, "bullets": [],
                                  "items": [stock_item(by[r["id"]], t, profiles.get(r["id"]), r) for r in grp]})
    wl = [str(x) for x in ((cfg.get("state") or {}).get("watch") or []) if str(x) in by] if private else []
    if wl:
        rm = {r["id"]: r for r in rows}
        R["sections"].append({"title": "👀 自選觀察", "intro": "你指定追蹤的股票，不一定在今晚的選股名單裡。", "bullets": [],
                              "items": [stock_item(by[i], t, profiles.get(i), rm.get(i)) for i in wl]})
    return R


def main(private=True):
    """private=True：完整版（含你的持股提醒）；False：分享版（給家人，不含持股）。回傳 Word 檔路徑"""
    ld = lambda n, d=None: json.load(open(os.path.join(DIR, n), encoding="utf-8")) if os.path.exists(os.path.join(DIR, n)) else d
    R = build(ld("data.json"), ld("sop_config.json", {}), ld("sop_plan.json", {}), ld("stock_profiles.json", {}), private=private)
    js = os.path.join(DIR, "report_full%s.json" % ("" if private else "_share"))
    json.dump(R, open(js, "w", encoding="utf-8"), ensure_ascii=False)
    out = os.path.join(DIR, "條件選股室_%s%s.docx" % (R["date"], "" if private else "_分享版"))
    subprocess.run(["node", os.path.join(DIR, "build_docx.js"), js, out], check=True)
    print(out)
    return out


if __name__ == "__main__":
    main()
