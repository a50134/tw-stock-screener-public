"""
addwatch.py - 加碼計畫監控（只給自己，發 Discord）：等低點、看訊號再加碼

設定在私人專案 sop_config.json 的 add_plans：
  {"1605": {"lots": [[27.5, 3], [25.6, 3], [24, 4]],   # 分批價位與張數
            "note": "循環股等回升，跌到低檔再加碼"}}
每晚判斷這檔現在在哪個階段，並列出起漲前常見的訊號有沒有出現：
  - 🔻 下跌中：−DI > +DI 且 ADX ≥ 20 → 不要接刀，到價也先等
  - ⏸ 打底盤整：ADX < 20（沒有方向）→ 計算已經盤整幾天，和這檔過去盤整多久比
  - 🚀 起漲訊號：ADX 從 20 以下回升到 20 以上、+DI > −DI、收盤站上月線 → 可以照計畫分批加碼
  - 籌碼：外資 5 日／20 日、投信連買、融資 20 日增減（減少＝籌碼沉澱）、千張大戶週變化
  - 這檔自己的歷史：過去每次「打底後 ADX 回升＋多方」之後 20 天漲跌
"""
import analysis
import exits


def dmi_series(s):
    c, h, l = s["c"], s["h"], s["l"]
    return [analysis.dmi(h, l, c, t) if t >= 35 else None for t in range(len(c))]


def bases(s, dm, t_end=None):
    """找出過去的盤整段（ADX < 20 連續 10 天以上），以及盤整結束時是不是轉多（ADX 回升到 20 以上且 +DI > −DI）"""
    T = len(s["c"]) - 1 if t_end is None else t_end
    out, i = [], 35
    while i <= T:
        if dm[i] and dm[i]["adx"] < 20:
            j = i
            while j + 1 <= T and dm[j + 1] and dm[j + 1]["adx"] < 20:
                j += 1
            if j - i + 1 >= 10:
                up = j + 1 <= T and dm[j + 1] and dm[j + 1]["pdi"] > dm[j + 1]["mdi"]
                out.append({"a": i, "b": j, "days": j - i + 1, "up": bool(up), "end": j + 1 if j + 1 <= T else None})
            i = j + 1
        else:
            i += 1
    return out


def stage(s, dm, t):
    d = dm[t]
    if not d:
        return "資料不足", ""
    c = s["c"]
    m20 = analysis.ma(c, 20, t)
    recent_up = any(dm[k] and dm[k - 1] and dm[k - 1]["adx"] < 20 <= dm[k]["adx"] for k in range(t - 4, t + 1))
    if recent_up and d["pdi"] > d["mdi"] and c[t] > m20:
        return "🚀 起漲訊號", "ADX 從 20 以下回升到 %.0f、+DI %.0f > −DI %.0f、站上月線 %s" % (d["adx"], d["pdi"], d["mdi"], exits.px(m20))
    if d["adx"] < 20:
        k = t
        while k > 35 and dm[k - 1] and dm[k - 1]["adx"] < 20:
            k -= 1
        return "⏸ 打底盤整", "ADX %.0f（沒有方向），已經盤整 %d 個交易日" % (d["adx"], t - k + 1)
    if d["mdi"] > d["pdi"]:
        return "🔻 下跌中", "−DI %.0f > +DI %.0f、ADX %.0f%s → 不要接刀，等 ADX 回落到 20 以下開始打底" % (
            d["mdi"], d["pdi"], d["adx"], "還在變大" if d["adx"] > d["adx_prev"] else "開始變小")
    return "📈 上漲中", "+DI %.0f > −DI %.0f、ADX %.0f" % (d["pdi"], d["mdi"], d["adx"])


def review(s, plan, prof=None):
    t = len(s["c"]) - 1
    c = s["c"]
    dm = dmi_series(s)
    st, why = stage(s, dm, t)
    L = ["🎯 加碼計畫監控：%s %s（收 %s）" % (s["id"], s["name"], exits.px(c[t]))]
    if plan.get("note"):
        L.append("・你的計畫：%s" % plan["note"])
    L.append("・階段：%s｜%s" % (st, why))
    # 這檔過去的盤整與之後的表現
    bs = [b for b in bases(s, dm) if b["b"] < t - 1]
    if bs:
        ds = [b["days"] for b in bs]
        ups = [b for b in bs if b["up"] and b["end"] and b["end"] + 20 <= t]
        rets = [(c[b["end"] + 20] / c[b["end"]] - 1) * 100 for b in ups]
        L.append("・這檔過去 %d 次盤整（ADX<20）：最短 %d、最長 %d、平均 %d 個交易日（約 %d～%d 週）%s" % (
            len(ds), min(ds), max(ds), sum(ds) / len(ds), min(ds) // 5, max(ds) // 5 + 1,
            "；盤整後轉多 %d 次，之後 20 天平均 %+.0f%%（%s）" % (len(rets), sum(rets) / len(rets), "、".join("%+.0f%%" % x for x in rets)) if rets else ""))
    # 起漲訊號檢查表
    d = dm[t] or {}
    m20 = analysis.ma(c, 20, t)
    fi = s.get("fi") or [0] * len(c)
    it = s.get("it") or [0] * len(c)
    f5, f20 = sum(fi[t - 4:t + 1]), sum(fi[t - 19:t + 1])
    k = 0
    while t - k >= 0 and it[t - k] > 0:
        k += 1
    mg = s.get("mg") or []
    mgc = (mg[t] / mg[t - 20] - 1) * 100 if len(mg) > t and mg[t] and mg[t - 20] else None
    hw = [x for x in (s.get("hw") or []) if x.get("big") is not None]
    md = analysis.macd(c, t) or {}
    chk = [
        (d.get("adx", 99) < 20 or st.startswith("🚀"), "下跌動能消退（ADX 回落到 20 以下）"),
        (st.startswith("🚀"), "ADX 從 20 以下回升，而且 +DI > −DI（起漲）"),
        (c[t] > m20, "收盤站上月線 %s" % exits.px(m20)),
        (bool(md) and md.get("hist", 0) > md.get("hist_prev", 0), "MACD 綠柱縮短或翻紅（跌勢減緩）"),
        (f5 > 0, "外資 5 日買超（目前 %s 張，20 日 %s 張）" % (analysis.zh(f5), analysis.zh(f20))),
        (k >= 3, "投信連買 3 天以上（目前連買 %d 天）" % k),
        (mgc is not None and mgc < 0, "融資 20 日減少，籌碼沉澱（%s）" % ("%+.0f%%" % mgc if mgc is not None else "—")),
        (len(hw) >= 2 and hw[-1]["big"] > hw[-2]["big"], "千張大戶持股增加（%s）" % ("%.1f%% → %.1f%%" % (hw[-2]["big"], hw[-1]["big"]) if len(hw) >= 2 else "—")),
    ]
    n = sum(1 for g, _ in chk if g)
    L.append("・起漲前訊號 %d/%d：%s" % (n, len(chk), "　".join(("☑" if g else "☐") + x for g, x in chk)))
    # 分批價位
    lots = plan.get("lots") or []
    if lots:
        parts = []
        for p, q in lots:
            parts.append("%s 買 %d 張（%s）" % (exits.px(p), q, "✅ 已到價" if s["l"][t] <= p else "還差 %+.1f%%" % ((p / c[t] - 1) * 100)))
        L.append("・分批價位：" + "；".join(parts))
    # 建議
    hit = any(s["l"][t] <= p for p, _ in lots)
    if st.startswith("🔻"):
        act = "還在下跌，就算到價也先不要買；等 ADX 回落、開始盤整再說"
    elif st.startswith("🚀"):
        act = "起漲訊號出現：可以照計畫買第一批%s" % ("（已到價）" if hit else "，不一定要等到最低的價位")
    elif st.startswith("⏸"):
        act = "打底中：到價可以先買一小批，其餘等起漲訊號（ADX 回升＋站上月線）再買" if hit else "打底中：還沒到價，耐心等；也可能沒跌到你的價位就起漲，起漲訊號出現時再決定要不要提前買"
    else:
        act = "上漲中：不追高，等回到月線附近"
    L.append("・➜ " + act)
    cyc = str((prof or {}).get("cyc", ""))
    news = {"銅": "LME 銅價連漲、突破前高", "鎳": "鎳價回升", "不銹鋼": "華新每月初公布的不鏽鋼盤價調漲（持平或調降＝還弱）", "電網": "台電強韌電網標案得標"}
    watch = [v for k_, v in news.items() if k_ in cyc + str((prof or {}).get("drv", ""))]
    if watch:
        L.append("・要盯的新聞：" + "、".join(watch) + "（晚上報告「持股相關新聞」會幫你標利多利空）")
    return "\n".join(L)


def nightly(data, cfg, profiles=None):
    plans = cfg.get("add_plans") or {}
    if not plans:
        return ""
    by = {s["id"]: s for s in data["stocks"]}
    out = [review(by[sid], p, (profiles or {}).get(sid)) for sid, p in plans.items() if sid in by and len(by[sid]["c"]) > 80]
    return "\n\n".join(out)


if __name__ == "__main__":
    import json
    import sys
    d = json.load(open(sys.argv[1], encoding="utf-8"))
    cfg = json.load(open(sys.argv[2], encoding="utf-8"))
    print(nightly(d, cfg, analysis._ld("stock_profiles.json", {})))
