"""
watch.py - 自選觀察：sop_config.json 的 state.watch 清單，每晚追蹤走勢、法人買賣、營收與近 3 天新聞
（放在只推給自己的那一則，不放進群發）
"""
import datetime as dt

import analysis
import weekend


def bottom_signal(s, t):
    """爆量下影線落底訊號（2026-11-24 錢線百分百毓棠老師；回測：市值前 150 檔跌深後出現，20 天 65% 賺、平均 +8%）
    條件：近 10 天內曾從 20 日高點跌 15% 以上，且今天成交量 ≥ 前 5 天平均 2 倍、下影線 ≥ 股價 3% 且比 K 棒實體長。
    回傳提醒文字，沒有就回傳空字串"""
    o, h, l, c, v = s["o"], s["h"], s["l"], s["c"], s["v"]
    if t < 30 or not c[t] or not all(v[t - 5:t + 1]):
        return ""
    deep = any(c[k] and c[k] / max(h[k - 19:k + 1]) - 1 <= -0.15 for k in range(t - 9, t + 1))
    av5 = sum(v[t - 5:t]) / 5
    low_sh = min(o[t], c[t]) - l[t]
    if not (deep and av5 and v[t] >= 2 * av5 and low_sh >= 0.03 * c[t] and low_sh > abs(c[t] - o[t])):
        return ""
    return ("・🟢 落底訊號：今天爆量下影線（成交量是前 5 天平均的 %.1f 倍、下影線 %.1f%%，低點 %s 有人大量接）。"
            "過去大型股跌深後出現這個訊號，買了 1 個月內約 65%% 賺、平均 +8%%，但之後還可能再跌 9%%：可以明天掛 %s 附近買第 1 批（分批，不要一次買滿）"
            % (v[t] / av5, low_sh / c[t] * 100, analysis.px(l[t]), analysis.px(c[t])))


def build(data, ids, profiles=None, get=None, news_days=3, plan_rows=None):
    """回傳文字；沒有自選股回傳空字串。get：fetch_finmind.get（抓個股新聞用，None 就不抓）"""
    if not ids:
        return ""
    profiles = profiles or {}
    by = {s["id"]: s for s in data["stocks"]}
    t = len(data["dates"]) - 1
    since = (dt.date.fromisoformat(data["asOf"]) - dt.timedelta(days=news_days)).isoformat()
    npos, nneg = weekend.words("NPOS"), weekend.words("NNEG")
    L = ["👀 自選觀察（%s 收盤，%d 檔）" % (data["asOf"], len(ids))]
    for sid in ids:
        s = by.get(str(sid))
        if not s or t < 60:
            L.append("【%s】今晚沒有資料" % sid)
            continue
        f = analysis.facts(s, t)
        L.append("【%s %s】收 %s（今日 %s）" % (sid, s["name"], analysis.px(f["close"]), analysis.fmt(f["chg1"])))
        L.append("・走勢：5 日 %s、20 日 %s；一年區間 %s～%s，在 %d%% 位置"
                 % (analysis.fmt(f["chg5"]), analysis.fmt(f["chg20"]), analysis.px(f["lo"]), analysis.px(f["hi"]), f["pos"]))
        fi, it = s.get("fi") or [0], s.get("it") or [0]
        L.append("・法人：今日外資 %s、投信 %s 張；近 10 日外資 %s、投信 %s 張"
                 % (analysis.zh(fi[-1]), analysis.zh(it[-1]), analysis.zh(f["fi10"]), analysis.zh(f["it10"])))
        if f["rev_yoy"]:
            m, y = f["rev_yoy"][-1]
            L.append("・營收：%s月年增 %s" % (m[5:].lstrip("0"), analysis.fmt(y)))
        if f["why"]:
            L.append("・訊號：" + "；".join(f["why"]))
        bs = bottom_signal(s, t)
        if bs:
            L.append(bs)
        p = profiles.get(str(sid))
        if p:
            L.append("・題材：%s｜風險：%s" % (p["drv"], p["risk"]))
        L.append("・建議：" + analysis.advise(s, t, (plan_rows or {}).get(str(sid))))
        if get:
            try:
                news = [n for n in get("TaiwanStockNews", str(sid), since) if n.get("title") and str(n.get("date", ""))[:10] >= since]
                seen, uniq = set(), []
                for n in sorted(news, key=lambda x: str(x.get("date", "")), reverse=True):
                    if n["title"] not in seen:
                        seen.add(n["title"])
                        uniq.append(n)
                for n in uniq[:3]:
                    v = weekend.score(n["title"], npos, nneg)
                    L.append("  %s %s｜%s" % (str(n.get("date", ""))[5:10].replace("-", "/"), "利多" if v > 0 else "利空" if v < 0 else "中性", n["title"]))
                if not uniq:
                    L.append("・近 %d 天沒有新聞" % news_days)
            except Exception as e:
                L.append("・新聞抓取失敗：%s" % str(e)[:40])
    L.append("自選觀察只追蹤、不代表建議買進；想買時跟我說，我會照交易計畫給買進區間與停損。")
    return "\n".join(L)
