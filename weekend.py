"""
weekend.py - 週末／連假綜合：把最後一個交易日收盤後到今晚的新聞整理成一段，接在報告後面

週日晚上（或連假最後一天晚上）daily_run.py 會呼叫：
  國際新聞：macro.json 依日期分組，列出每天的風險新聞
  個股新聞：最後名單（sop_plan.json）裡的股票，抓收盤後到今天的新聞，標記利多／利空
利多、利空字詞和網頁「條件選股室」用同一份（直接從 stock-screener.html 讀出來）。
"""
import datetime as dt
import json
import os
import re

DIR = os.path.dirname(os.path.abspath(__file__))
WD = "一二三四五六日"


def words(name):
    """從網頁程式讀出字詞清單（NPOS、NNEG、MPOS、MNEG），兩邊判斷一致"""
    html = open(os.path.join(DIR, "stock-screener.html"), encoding="utf-8").read()
    m = re.search(r"\b%s=\[([^\]]*)\]" % name, html)
    return re.findall(r"'([^']+)'", m.group(1)) if m else []


def score(title, pos, neg):
    t = title.lower()
    return sum(w.lower() in t for w in pos) - sum(w.lower() in t for w in neg)


def day_label(d):
    x = dt.date.fromisoformat(d[:10])
    return "%d/%d（%s）" % (x.month, x.day, WD[x.weekday()])


def build(last, today, get, max_stocks=30):
    """last：最後一個交易日；today：報告日；get：fetch_finmind.get。回傳文字（沒有內容回傳空字串）"""
    since = last.isoformat()
    L = ["🗓️ 週末綜合（%s ～ %s）" % (day_label(since), day_label(today.isoformat()))]

    # 國際新聞：依日期分組，每天列風險新聞前 3 則
    mpos, mneg = words("MPOS"), words("MNEG")
    mp = os.path.join(DIR, "macro.json")
    macro = json.load(open(mp, encoding="utf-8")).get("macro", []) if os.path.exists(mp) else []
    macro = [n for n in macro if n.get("d", "")[:10] >= since]
    if macro:
        L.append("國際新聞（共 %d 則）" % len(macro))
        by = {}
        for n in macro:
            by.setdefault(n["d"][:10], []).append(n)
        for d in sorted(by):
            ns = by[d]
            bad = [n for n in ns if score(n["title"], mpos, mneg) < 0]
            good = [n for n in ns if score(n["title"], mpos, mneg) > 0]
            L.append("・%s %d 則：風險 %d、正面 %d" % (day_label(d), len(ns), len(bad), len(good)))
            for n in bad[:3]:
                L.append("  ⚠️ " + n["title"])
    else:
        L.append("國際新聞：這段期間沒有抓到")

    # 個股新聞：最後名單的股票
    pp = os.path.join(DIR, "sop_plan.json")
    rows = json.load(open(pp, encoding="utf-8")).get("rows", []) if os.path.exists(pp) else []
    npos, nneg = words("NPOS"), words("NNEG")
    out = []
    for r in rows[:max_stocks]:
        sid, name = str(r.get("id")), r.get("name", "")
        news = [n for n in get("TaiwanStockNews", sid, since) if n.get("title") and str(n.get("date", ""))[:10] >= since]
        if not news:
            continue
        seen, uniq = set(), []
        for n in sorted(news, key=lambda x: str(x.get("date", "")), reverse=True):
            if n["title"] not in seen:
                seen.add(n["title"])
                uniq.append(n)
        sc = [score(n["title"], npos, nneg) for n in uniq]
        tag = lambda v: "利多" if v > 0 else "利空" if v < 0 else "中性"
        out.append("・%s %s：%d 則（利多 %d／利空 %d）" % (sid, name, len(uniq), sum(v > 0 for v in sc), sum(v < 0 for v in sc)))
        for n, v in list(zip(uniq, sc))[:3]:
            out.append("  %s %s｜%s" % (str(n.get("date", ""))[5:10].replace("-", "/"), tag(v), n["title"]))
    if rows:
        L.append("名單個股新聞（%d 檔有新聞）" % sum(1 for x in out if x.startswith("・")))
        L.extend(out or ["・名單裡的股票這段期間沒有新聞"])
    L.append("（新聞依標題字詞粗略分類，請點開原文確認）")
    return "\n".join(L)
