"""
brief.py - 精簡版晚上報告（LINE 群發、Discord 本文用）：一檔一行，每檔都有買賣建議
完整版（每檔理由、上下游、法人、目標價）放在 Discord 附檔與網頁版
"""
import analysis

WEB = "https://claude.ai/artifact/76qrctNEtvfXHEMB9StVeF"


def line(r):
    """一檔一行：代號 名稱 收盤｜建議｜策略"""
    z = "%s～%s" % (analysis.px(r["lo"]), analysis.px(r["hi"]))
    act = ("🟢 %s 可買" % z) if r.get("state") == "ok" else ("🟡 等跌到 %s" % z)
    return "・%s %s %s｜%s，停損 %s%s｜%s" % (
        r["id"], r["name"], analysis.px(r["prev"]), act, analysis.px(r["stop"]),
        "，目標 %s" % analysis.px(r["t1"]) if r.get("t1") else "", "、".join((r.get("strategies") or [])[:2]) + ("等" if len(r.get("strategies") or []) > 2 else ""))


def pick(plan, top_ok=8, top_wait=5):
    """精簡版推薦的股票（早上開盤檢查也只看這些）：回傳 (可買前幾檔, 等拉回前幾檔, 其餘)"""
    rows = [r for r in plan.get("rows", []) if r.get("lo") and r.get("stop") and r.get("state") != "hold"]  # 先觀望的不推薦、早上也不檢查
    key = lambda r: -(r.get("score") or 0)
    ok = sorted([r for r in rows if r.get("state") == "ok"], key=key)
    wait = sorted([r for r in rows if r.get("state") != "ok"], key=key)
    return ok[:top_ok], wait[:top_wait], ok[top_ok:] + wait[top_wait:]


def build(plan, data=None, profiles=None, cycle="", top_ok=8, top_wait=5, top_detail=3):
    rows = [r for r in plan.get("rows", []) if r.get("lo") and r.get("stop")]
    if not rows and not cycle:
        return ""
    ok, wait, rest = pick(plan, top_ok, top_wait)
    L = ["📈 條件選股室｜%s 收盤｜國際風險：%s" % (plan.get("date", ""), plan.get("risk", "—")),
         "共 %d 檔入選，下面依健檢分數列出最值得看的" % len(rows), ""]
    if ok:
        L.append("🟢 可買（前 %d 檔）" % len(ok))
        L += [line(r) for r in ok]
    if wait:
        L += ["", "🟡 等拉回再買（前 %d 檔）" % len(wait)]
        L += [line(r) for r in wait]
    if rest:
        L += ["", "⚪ 其他 %d 檔：分數較低，先不建議（%s）" % (len(rest), "、".join(r["name"] for r in rest[:12]) + ("…" if len(rest) > 12 else ""))]
    allh = [r for r in plan.get("rows", []) if r.get("state") == "hold"]
    hold = [r for r in allh if not str(r.get("hold_why", "")).startswith("循環股")]
    cyc = [r for r in allh if str(r.get("hold_why", "")).startswith("循環股")]
    if hold:
        L += ["", "⚪ 風險偏高先觀望（%s）：只因量價突破／穩健動能入選的 %d 檔先不追（%s）" % (hold[0].get("hold_why", ""), len(hold), "、".join(r["name"] for r in hold[:10]) + ("…" if len(hold) > 10 else ""))]
    if cyc:
        L += ["", "⚪ 循環股在高檔先觀望（已到近 5 年平均高點附近，低點買、高點賣）：%s" % "、".join(r["name"] for r in cyc[:10])]
    if cycle:
        L += ["", cycle]
    if data and profiles:  # 重點 3 檔：一句業務＋一句為何可能漲
        by = {s["id"]: s for s in data["stocks"]}
        t = len(data["dates"]) - 1
        top3 = [r for r in ok if not str(r["id"]).startswith("00") and r["id"] in by][:top_detail]
        if top3:
            L += ["", "📌 重點 %d 檔為什麼可能漲" % len(top3)]
            for r in top3:
                f = analysis.facts(by[r["id"]], t)
                p = profiles.get(r["id"]) or {}
                why = "；".join(f["why"][:2]) or "數據面沒有明顯訊號"
                L.append("・%s %s：%s。%s%s" % (r["id"], r["name"], p.get("biz", "（公司資料待補）"), why,
                                              "；題材：" + p["drv"] if p.get("drv") else ""))
    L += ["", "推薦總表與前幾檔「為什麼可以買」看下面的圖片；全部股票的詳細說明按「打開完整報告」（Word）",
          "依固定規則計算，不是投資建議。"]
    return "\n".join(L)
