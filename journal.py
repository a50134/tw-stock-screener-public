"""
journal.py - 模擬交易日誌＋每日復盤（只給自己：發 Discord，並存一份到私人專案 journal_latest.txt 給 Claude 讀）

流程：
  1. 晚上看報告 → 挑至少 1 檔，告訴 Claude「模擬買 2884 49 512 股，理由…」
  2. Claude 記到私人專案 sop_config.json 的 orders.list：
     {"id": "2884", "price": 49, "qty": 512, "date": "2026-11-03", "sim": true, "n": 1,
      "why": "你的理由", "stop": 45.15, "sell": [52, 54], "half": 52}   # stop／sell／half 可以不填（用系統規則）
  3. 隔天：盤中最低價碰到限價就算成交（開盤就比限價低用開盤價）；n 天內沒碰到算沒買到
  4. 每晚：照 exits.check 的賣出規則模擬（報告說「賣出」→ 隔天開盤賣；「減碼」→ 隔天開盤賣一半）
  5. 每晚復盤，每筆都檢討（資深投資人每天做的事）：
     - 今天表現：跟大盤（0050）、同產業比，是強還是弱
     - 損益：未實現、進場後最多賺多少／最多賠多少（看停損停利設得合不合理）
     - 進場檢討：買在當天高低區間的哪裡、有沒有追高
     - 理由還在嗎：進場時的理由今天還成立幾項
     - 計畫執行：離停損、目標多遠，系統建議續抱或賣
     - 結束的單：賺賠原因、學到什麼（記到 lessons.json）
  6. 累計成績：勝率、平均賺賠、期望值（每筆平均賺多少）
"""
import json
import os
import statistics as st

import analysis
import exits

DIR = os.path.dirname(os.path.abspath(__file__))
FEE = 0.001425


def fee(amt, q, disc):
    return max(1 if q < 1000 else 20, int(amt * FEE * disc / 10)) if amt > 0 else 0


def tax_rate(sid):
    return 0.001 if sid.startswith("00") else 0.003


def sim_orders(cfg):
    oc = cfg.get("orders") or {}
    lst = (oc.get("list") if isinstance(oc, dict) else oc) or []
    return [o for o in lst if o.get("sim") and not str(o.get("side", "b")).startswith("s")]


def cut(s, j):
    """把股票資料截到第 j 天（模擬「當天晚上」看到的樣子）"""
    x = dict(s)
    for k in ("o", "h", "l", "c", "v", "fi", "it", "dl", "mg", "sh"):
        if isinstance(s.get(k), list):
            x[k] = s[k][:j + 1]
    return x


def simulate(o, s, dates, disc, prof=None):
    """回傳一筆模擬單從下單到今天的完整過程"""
    px, q, n = float(o["price"]), int(o.get("qty") or 1000), int(o.get("n") or 1)
    T = len(dates) - 1
    t0 = next((i for i, d in enumerate(dates) if d >= o["date"]), None)
    R = {"o": o, "st": "pend", "exits": [], "q": 0}
    if t0 is None:
        return R
    for t in range(t0, min(t0 + n, T + 1)):
        if s["l"][t] <= px:
            fill = s["o"][t] if s["o"][t] <= px else px
            R.update(st="open", t=t, fill=fill, q=q, cost=fill * q + fee(fill * q, q, disc), edge=s["l"][t] == px and s["o"][t] > px)
            break
    else:
        if t0 + n - 1 <= T:
            R.update(st="miss", lo=min(s["l"][t0:t0 + n]))
        return R
    plan = {}
    if o.get("sell"):
        plan["sell"] = o["sell"]
    if o.get("stop"):
        plan["stop"] = o["stop"]
    if o.get("half"):
        plan["half"] = o["half"]
    left, sold_half, pending = q, False, None
    real = 0.0
    for j in range(R["t"], T + 1):
        if pending and left > 0:  # 前一晚決定要賣：今天開盤賣
            qq = left if pending[0] == "all" else max(1, left // 2)
            p = s["o"][j]
            amt = p * qq
            pnl = amt - fee(amt, qq, disc) - int(amt * tax_rate(s["id"])) - R["cost"] / q * qq
            real += pnl
            left -= qq
            R["exits"].append({"t": j, "px": p, "q": qq, "why": pending[1], "pnl": pnl})
            if pending[0] == "half":
                sold_half = True
            pending = None
        if left <= 0:
            break
        h = {"cost": R["fill"], "date": dates[R["t"]], "qty": left, "sold": q - left if sold_half else 0, "plan": plan}
        lv, act, rs, _, P = exits.check(cut(s, j), dates[:j + 1], h, prof)
        if j == R["t"]:
            R["plan0"] = P
        if lv == 3:
            pending = ("all", rs[0] if rs else act)
        elif lv == 2 and not sold_half:
            pending = ("half", rs[0] if rs else act)
        R["now"] = (lv, act, rs, P)
    c = s["c"][T]
    if left <= 0 and R["exits"]:  # 結束的單只算到出場（出場那天開盤就賣了）
        e = R["exits"][-1]
        hi = max(s["h"][R["t"]:e["t"]] + [e["px"]])
        lo = min(s["l"][R["t"]:e["t"]] + [e["px"]])
    else:
        hi = max(s["h"][R["t"]:T + 1])
        lo = min(s["l"][R["t"]:T + 1])
    R.update(left=left, real=real, mfe=(hi / R["fill"] - 1) * 100, mae=(lo / R["fill"] - 1) * 100, pending=pending)
    if left > 0:
        mv = c * left
        R["unreal"] = mv - fee(mv, left, disc) - int(mv * tax_rate(s["id"])) - R["cost"] / q * left
    else:
        R["unreal"] = 0.0
        R["st"] = "closed"
    R["pnl"] = R["real"] + R["unreal"]
    R["ret"] = R["pnl"] / R["cost"] * 100
    return R


def entry_review(s, R):
    t, f = R["t"], R["fill"]
    h, l = s["h"][t], s["l"][t]
    pos = (f - l) / (h - l) * 100 if h > l else 50
    m20 = analysis.ma(s["c"], 20, t - 1) if t > 20 else None
    bias = (f / m20 - 1) * 100 if m20 else 0
    t_ = "成交在當天高低區間的 %.0f%%" % pos + ("（買在相對低點，好）" if pos <= 35 else "（買在當天高點附近，偏追價）" if pos >= 75 else "")
    if bias > 8:
        t_ += "；比月線高 %.0f%%，有追高" % bias
    if R.get("edge"):
        t_ += "；最低價剛好碰到限價，實際可能排不到"
    return t_, pos, bias


def reasons_now(s, t_entry, t):
    """進場時的理由 vs 今天"""
    a = set(analysis.facts(cut(s, t_entry - 1), t_entry - 1)["why"]) if t_entry > 60 else set()
    b = set(analysis.facts(s, t)["why"])
    key = lambda x: x.split("（")[0].split(" ")[0][:6]
    ka, kb = {key(x): x for x in a}, {key(x): x for x in b}
    keep = [ka[k] for k in ka if k in kb]
    gone = [ka[k] for k in ka if k not in kb]
    new = [kb[k] for k in kb if k not in ka]
    return keep, gone, new


def lesson_of(s, R, pos, bias):
    """結束的單：學到什麼（固定規則）"""
    L = []
    held = (R["exits"][-1]["t"] - R["t"]) if R["exits"] else 0
    if R["pnl"] < 0:
        if held <= 3:
            L.append("買進 %d 天內就停損：進場太急或停損太近，下次等站穩（收盤站上進場那天高點）再買" % held)
        if pos >= 75:
            L.append("買在當天高點附近（%.0f%%）：下次限價掛低一點，或等拉回" % pos)
        if bias > 8:
            L.append("進場時比月線高 %.0f%%：追高，下次等回到月線附近" % bias)
        if R["mfe"] >= 5:
            L.append("曾經賺 %.1f%% 最後卻賠錢：賺 5%% 以上時可以先賣一半或把停損拉到成本" % R["mfe"])
        if not L:
            L.append("照計畫停損，紀律正確；虧損是正常成本")
    else:
        if R["mfe"] - R["ret"] > 8:
            L.append("最高賺 %.1f%%，出場只剩 %.1f%%：可以用移動停利保住更多" % (R["mfe"], R["ret"]))
        else:
            L.append("照計畫出場，賺 %.1f%%" % R["ret"])
        if pos <= 35:
            L.append("買在當天相對低點（%.0f%%），限價掛低有用" % pos)
    return L


def market_chg(data, t):
    for s in data["stocks"]:
        if s["id"] == "0050" and len(s["c"]) > t:
            return (s["c"][t] / s["c"][t - 1] - 1) * 100
    try:  # data.json 沒有 0050 就用全市場行情（market_hist.json）
        hist = json.load(open(os.path.join(DIR, "market_hist.json"), encoding="utf-8"))["hist"]
        d0, d1 = data["dates"][t - 1], data["dates"][t]
        a, b = hist[d0]["0050"][3], hist[d1]["0050"][3]
        return (b / a - 1) * 100
    except Exception:
        return None


def ind_chg(data, ind, t):
    xs = [(s["c"][t] / s["c"][t - 1] - 1) * 100 for s in data["stocks"] if s.get("industry") == ind and len(s["c"]) > t and s["c"][t - 1]]
    return st.mean(xs) if len(xs) >= 3 else None


def daily_review(data, cfg, profiles=None, save_lessons=True):
    """每晚的模擬交易復盤；回傳文字（沒有模擬單就提醒挑股票）"""
    profiles = profiles or {}
    orders = sim_orders(cfg)
    D = data["dates"]
    T = len(D) - 1
    disc = float(((cfg.get("orders") or {}).get("disc") if isinstance(cfg.get("orders"), dict) else None) or 2.8)
    by = {s["id"]: s for s in data["stocks"]}
    L = ["📝 模擬交易復盤（%s 收盤）" % D[T]]
    mk = market_chg(data, T)
    if mk is not None:
        L.append("大盤（0050）今天 %+.1f%%" % mk)
    done, opened, lessons = [], [], []
    for o in orders:
        s = by.get(str(o["id"]))
        if not s:
            L.append("・%s：資料裡沒有這檔（明天會補抓）" % o["id"])
            continue
        R = simulate(o, s, D, disc, profiles.get(s["id"]))
        nm = "%s %s" % (s["id"], s["name"])
        if R["st"] == "pend":
            L.append("⏳ %s：限價 %s × %s，等 %s 開盤" % (nm, exits.px(float(o["price"])), _lots(o), o["date"]))
            continue
        if R["st"] == "miss":
            if D.index(next(d for d in D if d >= o["date"])) + int(o.get("n") or 1) - 1 == T:  # 今天才確定沒買到
                L.append("❌ %s：限價 %s 沒買到（最低 %s）。檢討：限價掛太低，或這檔太強不回頭；強勢股可以掛靠近收盤價" % (
                    nm, exits.px(float(o["price"])), exits.px(R["lo"])))
            continue
        ent, pos, bias = entry_review(s, R)
        if R["st"] == "closed":
            done.append(R)
            last = R["exits"][-1]
            if last["t"] < T:  # 之前就結束的單，不再逐筆檢討
                continue
        else:
            opened.append(R)
        L.append("")
        L.append("【%s】模擬買 %s × %s 股（%s 成交）%s" % (nm, exits.px(R["fill"]), R["q"], D[R["t"]][5:].replace("-", "/"),
                                                  "｜✅ 已結束" if R["st"] == "closed" else "｜持有 %d 天" % (T - R["t"])))
        if o.get("why"):
            L.append("・你的理由：%s" % o["why"])
        chg = (s["c"][T] / s["c"][T - 1] - 1) * 100
        ic = ind_chg(data, s.get("industry"), T)
        rel = []
        if mk is not None:
            rel.append("大盤 %+.1f%%" % mk)
        if ic is not None:
            rel.append("%s平均 %+.1f%%" % (s.get("industry", "同產業"), ic))
        better = mk is not None and chg > mk + 0.3
        worse = mk is not None and chg < mk - 0.3
        L.append("・今天：收 %s（%+.1f%%）%s%s" % (exits.px(s["c"][T]), chg, "，" + "、".join(rel) if rel else "",
                                            " → 比大盤強" if better else " → 比大盤弱" if worse else ""))
        L.append("・損益：%s %s 元（%+.1f%%）；進場後最多賺 %+.1f%%、最多賠 %+.1f%%" % (
            "已實現" if R["st"] == "closed" else "目前", "{:+,.0f}".format(R["pnl"]), R["ret"], R["mfe"], R["mae"]))
        for e in R["exits"]:
            L.append("・出場：%s 開盤賣 %s × %d 股（%s），%s 元" % (D[e["t"]][5:].replace("-", "/"), exits.px(e["px"]), e["q"], e["why"][:40], "{:+,.0f}".format(e["pnl"])))
        L.append("・進場檢討：%s" % ent)
        keep, gone, new = reasons_now(s, R["t"], T)
        if keep or gone or new:
            L.append("・理由還在嗎：進場時 %d 項，今天還在 %d 項%s%s" % (
                len(keep) + len(gone), len(keep), "；消失：" + "、".join(x.split("（")[0] for x in gone[:3]) if gone else "",
                "；新增：" + "、".join(x.split("（")[0] for x in new[:3]) if new else ""))
        f = analysis.facts(s, T)
        tech = [x for x in (analysis.dmi_text(f.get("dmi")), analysis.macd_text(f.get("macd"))) if x]
        if tech:
            L.append("・技術面：%s" % "；".join(tech))
        if R["st"] != "closed":
            lv, act, rs, P = R["now"]
            L.append("・計畫：停損 %s（還有 %+.1f%%）、目標 %s（還差 %+.1f%%）｜系統建議：%s%s" % (
                exits.px(P["stop"]), (P["stop"] / s["c"][T] - 1) * 100, exits.px(P["t1"]), (P["t1"] / s["c"][T] - 1) * 100, act,
                "（%s）" % rs[0][:40] if rs else ""))
            if R.get("pending"):
                L.append("・➜ 明天開盤模擬%s：%s" % ("全部賣出" if R["pending"][0] == "all" else "賣一半", R["pending"][1][:50]))
            tips = []
            if R["mae"] < -5 and R["ret"] < 0:
                tips.append("已經賠超過 5%，確認是不是理由消失了，不要凹單")
            if R["mfe"] > 8 and R["ret"] < R["mfe"] / 2:
                tips.append("賺的回吐一半以上，考慮把停損拉到成本")
            if gone and not keep:
                tips.append("進場理由都不在了，就算沒到停損也要考慮出場")
            if worse and chg < -2:
                tips.append("今天明顯比大盤弱，注意是不是有個股利空")
            if tips:
                L.append("・提醒：" + "；".join(tips))
        else:
            ls = lesson_of(s, R, pos, bias)
            L.append("・學到什麼：" + "；".join(ls))
            for x in ls:
                lessons.append({"date": D[T], "id": s["id"], "type": "模擬" + ("賺" if R["pnl"] >= 0 else "賠"), "lesson": "%s：%s" % (nm, x)})
    # 累計成績
    if done:
        r = [x["ret"] for x in done]
        win = [x for x in r if x > 0]
        loss = [x for x in r if x <= 0]
        exp = st.mean(r)
        L.append("")
        L.append("📊 模擬累計：已結束 %d 筆，勝率 %.0f%%，平均賺 %s、平均賠 %s，每筆期望值 %+.1f%%（%s）" % (
            len(r), len(win) / len(r) * 100, "%+.1f%%" % st.mean(win) if win else "—", "%+.1f%%" % st.mean(loss) if loss else "—", exp,
            "正的：這套做法長期會賺" if exp > 0 else "負的：要檢討選股或停損停利"))
        if len(r) < 20:
            L.append("　（筆數還少，累積 20 筆以上才看得準）")
    if opened:
        L.append("持有中 %d 筆，合計 %s 元" % (len(opened), "{:+,.0f}".format(sum(x["pnl"] for x in opened))))
    nxt = [o for o in orders if o["date"] > D[T]]
    if not nxt:
        L.append("")
        L.append("👉 明天還沒有模擬單：從今晚名單挑至少 1 檔，告訴 Claude「模擬買 代號 價格 股數，理由…」")
    if save_lessons and lessons:
        try:
            import review
            review.save_lessons(lessons)
        except Exception:
            pass
    if len(L) <= 2 and not nxt and not orders:
        return "📝 模擬交易：目前沒有模擬單。\n👉 從今晚名單挑至少 1 檔，告訴 Claude「模擬買 代號 價格 股數，理由…」"
    return "\n".join(L)


def _lots(o):
    q = int(o.get("qty") or 1000)
    return "%d 股" % q


if __name__ == "__main__":
    import sys
    d = json.load(open(sys.argv[1] if len(sys.argv) > 1 else os.path.join(DIR, "data.json"), encoding="utf-8"))
    cfg = json.load(open(sys.argv[2] if len(sys.argv) > 2 else os.path.join(DIR, "sop_config.json"), encoding="utf-8"))
    print(daily_review(d, cfg, analysis._ld("stock_profiles.json", {}), save_lessons=False))
