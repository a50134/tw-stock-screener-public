"""
sizing.py - 依你的資金算「買多少」＋下單前檢查表（只發 Discord，不放進 LINE 群發、不印在公開執行紀錄）

設定在私人專案 sop_config.json 的 risk：
  {"capital": 100000,      # 用來買股票的總資金（可以再加）
   "per_trade_pct": 2,     # 一般股票：每筆最多賠總資金的幾 %（碰到停損時）
   "max_pos_pct": 30,      # 單一股票最多占總資金幾 %
   "max_ind_pct": 30,      # 同一產業最多占總資金幾 %
   "cyclical": "wait"}     # 循環股願意等：不用緊停損，改成分 3 批買、控制總金額，
                           #   最壞情況看「跌到近 5 年平均低點」會賠多少
台股可以買零股（盤中零股），所以張數不足 1 張時用「股」計算。
"""
import analysis
import exits

DFT = {"capital": None, "per_trade_pct": 2, "max_pos_pct": 30, "max_ind_pct": 30, "cyclical": "wait"}


def risk_cfg(cfg):
    r = dict(DFT)
    r.update((cfg or {}).get("risk") or {})
    return r if r.get("capital") else None


def lots(n):
    """股數 → 「1 張 200 股」這種寫法"""
    n = int(n)
    if n <= 0:
        return "0 股"
    z, o = divmod(n, 1000)
    return ("%d 張" % z if z else "") + (" %d 股" % o if o else "") if z else "%d 股" % o


def held(cfg, data):
    """目前持股：{代號: (股數, 成本金額, 產業)}"""
    by = {s["id"]: s for s in (data or {}).get("stocks", [])}
    out = {}
    for sid, h in exits.holdings(cfg).items():
        out[sid] = (h["qty"], h["qty"] * h["cost"], (by.get(sid) or {}).get("industry", ""))
    return out


def plan(s, t, prof, row, cfg, data):
    """回傳 (文字行清單, 摘要 dict)；沒有設定資金回傳 ([], None)"""
    R = risk_cfg(cfg)
    if not R:
        return [], None
    cap = float(R["capital"])
    H = held(cfg, data)
    used = sum(v[1] for v in H.values())
    cash = max(0.0, cap - used)
    ind = s.get("industry", "")
    ind_used = sum(v[1] for k, v in H.items() if v[2] and v[2] == ind and k != s["id"])
    mine = H.get(s["id"], (0, 0.0, ind))[1]
    c = s["c"][t]
    # 多策略共振的股票可以用到單一股票上限；只有 1 個策略選到的先用一半（查個股時 row 是 None，照上限）
    half = row is not None and not row.get("star")
    lim_pos = cap * R["max_pos_pct"] / 100 * (0.5 if half else 1) - mine
    lim_ind = cap * R["max_ind_pct"] / 100 - ind_used - mine
    budget = max(0.0, min(lim_pos, lim_ind, cash))
    L = []
    info = {"cap": cap, "cash": cash, "ind_pct": (ind_used + mine) / cap * 100, "risk_pct": None, "budget": budget}
    z = analysis.cycle_zone(s, t)
    head = "💰 依你的資金（%s 元，已用 %s、可用 %s）" % ("{:,.0f}".format(cap), "{:,.0f}".format(used), "{:,.0f}".format(cash))
    if mine:
        head += "；這檔已持有 %s 元" % "{:,.0f}".format(mine)
    L.append(head)
    if budget < c:
        why = "現金不夠" if cash < c else "這檔已經到單一股票上限 %d%%" % R["max_pos_pct"] if lim_pos <= lim_ind else "同產業（%s）已經到上限 %d%%" % (ind, R["max_ind_pct"])
        L.append("　➜ 先不要加買：%s" % why)
        info["risk_pct"] = 0
        return L, info
    if z and R.get("cyclical") == "wait":
        if z["zone"] == "high":
            L.append("　➜ 循環股已在近 %d 年平均高點 %s 附近，不建議買（低點買、高點賣）" % (z["n"], exits.px(z["hi"])))
            info["risk_pct"] = None
            return L, info
        # 循環股：分 3 批（40%／30%／30%），跌越多買越多；最壞看跌到平均低點的 9 成
        p1 = row["hi"] if row and row.get("hi") else c
        p2 = exits.tick(p1 * 0.9)
        p3 = exits.tick(min(p1 * 0.8, max(z["lo"] * 1.1, p1 * 0.7)))
        n = [int(budget * w / p) for w, p in ((0.4, p1), (0.3, p2), (0.3, p3))]
        cost = n[0] * p1 + n[1] * p2 + n[2] * p3
        q = sum(n)
        worst = min(z["lo"] * 0.9, p3 * 0.9)
        loss = cost - q * worst
        info["risk_pct"] = loss / cap * 100
        L.append("　循環股分 3 批（總共最多 %s 元，占資金 %.0f%%）：①現在 %s 以下買 %s ②跌到 %s 買 %s ③跌到 %s 買 %s" % (
            "{:,.0f}".format(cost), cost / cap * 100, exits.px(p1), lots(n[0]), exits.px(p2), lots(n[1]), exits.px(p3), lots(n[2])))
        L.append("　最壞情況：跌到 %s（%s），三批都買到時帳面約賠 %s 元（資金的 %.0f%%）；循環股你願意等，目標平均高點約 %s" % (
            exits.px(worst), "近 5 年平均低點 %s 再低 1 成" % exits.px(z["lo"]) if worst == z["lo"] * 0.9 else "第三批買進價再跌 1 成",
            "{:,.0f}".format(loss), loss / cap * 100, exits.px(z["hi"])))
        return L, info
    stop = row.get("stop") if row else None
    if not stop:
        stop = exits.tick(c * 0.92)
    entry = row["hi"] if row and row.get("hi") else c
    per = max(entry - stop, entry * 0.01)
    n_risk = int(cap * R["per_trade_pct"] / 100 / per)
    n_cash = int(budget / entry)
    n = min(n_risk, n_cash)
    if n <= 0:
        L.append("　➜ 停損距離太大或資金不夠，先不要買")
        info["risk_pct"] = 0
        return L, info
    loss = n * per
    info["risk_pct"] = loss / cap * 100
    L.append("　建議最多買 %s（約 %s 元，占資金 %.0f%%）；跌到停損 %s 約賠 %s 元（資金的 %.1f%%）%s" % (
        lots(n), "{:,.0f}".format(n * entry), n * entry / cap * 100, exits.px(stop), "{:,.0f}".format(loss), loss / cap * 100,
        "；受「單一股票／產業上限」限制" if n_cash < n_risk else "；受「每筆最多賠 %d%%」限制" % R["per_trade_pct"]))
    if n >= 1000 and n % 1000:
        L.append("　（整張 %s ＋零股 %d 股；零股用盤中零股下單）" % (lots(n // 1000 * 1000), n % 1000))
    return L, info


def wrong_signs(s, prof):
    """「什麼情況代表我看錯」"""
    w = ["收盤跌破停損", "外資＋投信連續 4 天以上賣超", "月營收連 2 個月年減"]
    if analysis.is_cyc(prof):
        w.append("原料報價轉跌（%s）" % ((prof or {}).get("cyc") or "產業報價")[:20])
    return w


def checklist(s, t, f, prof, row, cfg, data, bt=None, weak=None):
    """下單前檢查表：回傳文字行清單（沒有設定資金也會列，只是少「風險」那項的數字）"""
    L = ["✅ 下單前檢查表："]
    ok = 0
    items = []
    if weak is None:
        weak = analysis.market_weak({})
    items.append((not weak, "大盤沒有偏弱" + ("（%s）" % weak if weak else "")))
    kinds = []
    yo = f.get("rev_yoy") or []
    if f.get("rev13") or (yo and yo[-1][1] > 10):
        kinds.append("營收")
    if f.get("fi_streak", 0) >= 3 or f.get("it_streak", 0) >= 3 or (f.get("fi10", 0) > 0 and f.get("it10", 0) > 0):
        kinds.append("籌碼")
    c = s["c"]
    if c[t] > analysis.ma(c, 20, t) > analysis.ma(c, 20, t - 5):
        kinds.append("技術面")
    items.append((len(kinds) >= 2, "至少 2 種理由支持（目前：%s）" % ("、".join(kinds) or "沒有")))
    if bt:
        z = analysis.cycle_zone(s, t)
        good = bt.get("long_ok") or (z is not None and z["pos"] < 50) or bt.get("trend_up")
        items.append((good, "5 年回測：%s" % bt.get("summary", "")))
    try:
        import fin_health
        ok_f, txt_f = fin_health.check(s)
        if ok_f is not None:
            items.append((ok_f, txt_f.replace("✅ ", "").replace("⚠️ ", "")))
    except Exception:
        pass
    sz, info = plan(s, t, prof, row, cfg, data)
    R = risk_cfg(cfg)
    if info:
        items.append((info["risk_pct"] is not None and info["risk_pct"] <= (R["per_trade_pct"] if not analysis.cycle_zone(s, t) else 15),  # 循環股願意等：最壞情況賠 15% 以內
                      "這筆的風險在可接受範圍" + ("（最多賠資金的 %.1f%%）" % info["risk_pct"] if info["risk_pct"] else "")))
        items.append((info["ind_pct"] < R["max_ind_pct"], "同產業持股不超過 %d%%（目前 %.0f%%）" % (R["max_ind_pct"], info["ind_pct"])))
    for g, txt in items:
        ok += bool(g)
        L.append("　%s %s" % ("☑" if g else "☐", txt))
    L.append("　☑ 看錯就出場的訊號：%s" % "、".join(wrong_signs(s, prof)))
    n = len(items)
    L.append("　➜ %d/%d 項符合：%s" % (ok, n, "可以照計畫下單" if ok == n else "還差 %d 項，建議等條件到齊或只買一半" % (n - ok) if ok >= n - 1 else "不建議現在下單"))
    return sz + L


def nightly(data, cfg, plan_rows, profiles, weak=None, top=8):
    """晚上報告（只給自己）：今晚可買的股票，依你的資金各買多少"""
    if not risk_cfg(cfg):
        return ""
    by = {s["id"]: s for s in data["stocks"]}
    rows = [r for r in plan_rows if r.get("state") == "ok" and r["id"] in by and not r["id"].startswith("00")]
    rows.sort(key=analysis.rank)
    if not rows:
        return ""
    L = ["💰 依你的資金：今晚可買的股票各買多少（只有你看得到；⭐共振的最多用到單一股票上限，其他先用一半）"]
    for r in rows[:top]:
        s = by[r["id"]]
        t = len(s["c"]) - 1
        sz, info = plan(s, t, profiles.get(r["id"]), r, cfg, data)
        L.append("・%s%s %s：%s" % (analysis.star(r), r["id"], r["name"], " ".join(x.strip() for x in sz[1:]) or "—"))
    if weak:
        L.append("大盤偏弱（%s）：建議只買上面數量的一半，保留現金。" % weak)
    return "\n".join(L)
