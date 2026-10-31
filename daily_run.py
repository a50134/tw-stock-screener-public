"""
daily_run.py - 每日自動報告：抓資料 → 產生 SOP 報告 → 發到 Discord 和 LINE

用法：
  python daily_run.py            # 正常執行（沒開盤的日子會自動跳過，不發送）
  python daily_run.py --dry-run  # 只產生報告，不發送
  python daily_run.py --force    # 沒開盤也照發

設定檔 sop_config.json（可選）：
  universe   要抓的股票代號清單（沒寫就用 fetch_finmind.py 的預設 20 檔）
  state      網頁「每日 SOP」→「複製排程設定」貼上的內容（你的策略、淘汰條件、健檢門檻）
  onlyBuy    true 時報告只列「可買」和「待開盤」
紀錄寫在 logs/ 資料夾。
"""
import datetime as dt
import json
import os
import ssl
import subprocess
import sys
import time
import urllib.request

DIR = os.path.dirname(os.path.abspath(__file__))
LOG_DIR = os.path.join(DIR, "logs")
NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0)
os.makedirs(LOG_DIR, exist_ok=True)
LOG = os.path.join(LOG_DIR, "daily_%s.log" % dt.date.today().strftime("%Y%m%d"))


def log(*a):
    line = "[%s] %s" % (dt.datetime.now().strftime("%H:%M:%S"), " ".join(str(x) for x in a))
    print(line)
    with open(LOG, "a", encoding="utf-8") as f:
        f.write(line + "\n")


def run(cmd, timeout):
    log("執行：", " ".join(cmd))
    env = dict(os.environ, PYTHONIOENCODING="utf-8")
    p = subprocess.run(cmd, cwd=DIR, capture_output=True, text=True, encoding="utf-8", errors="replace", timeout=timeout, env=env,
                       creationflags=NO_WINDOW)  # 背景執行，不跳出命令視窗（視窗被關掉會中斷程式）
    for s in (p.stdout, p.stderr):
        if s.strip():
            log(s.strip()[-3000:])
    if p.returncode != 0:
        raise RuntimeError("%s 失敗（代碼 %s）" % (cmd[1] if len(cmd) > 1 else cmd[0], p.returncode))


def extra_holidays():
    """臨時休市（颱風假等，證交所假日表沒有）：
    1. sop_config.json 的 extra_holidays（手動加，例如 ["2026-10-23"]）
    2. 全市場行情 market_hist.json 裡，平日卻沒有成交資料的日子（自動偵測）"""
    out = set()
    try:
        cfg = json.load(open(os.path.join(DIR, "sop_config.json"), encoding="utf-8"))
        out |= {dt.date.fromisoformat(x) for x in cfg.get("extra_holidays") or []}
    except Exception:
        pass
    try:
        days = sorted(json.load(open(os.path.join(DIR, "market_hist.json"), encoding="utf-8")).get("hist") or {})
        if len(days) >= 2:
            have, d, end = set(days), dt.date.fromisoformat(days[0]), dt.date.fromisoformat(days[-1])
            while d < end:
                if d.weekday() < 5 and d.isoformat() not in have:
                    out.add(d)
                d += dt.timedelta(days=1)
    except Exception:
        pass
    return out


def twse_holidays():
    """證交所休市日（set of date），再加上臨時休市（extra_holidays）；假日表抓不到就只用週末＋臨時休市判斷"""
    return _twse_holidays() | extra_holidays()


def _twse_holidays():
    try:
        req = urllib.request.Request("https://openapi.twse.com.tw/v1/holidaySchedule/holidaySchedule", headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(req, timeout=60, context=ssl.create_default_context()) as r:
            rows = json.loads(r.read().decode("utf-8-sig"))
        out = set()
        for x in rows:  # 「開始交易日」「最後交易日」照常交易；放假、補假、市場無交易才算休市
            name, desc, d = x.get("Name", ""), x.get("Description", ""), str(x.get("Date", ""))
            if "交易日" not in name and ("放假" in desc or "補假" in desc or "無交易" in name):
                out.add(dt.date(int(d[:3]) + 1911, int(d[3:5]), int(d[5:7])))
        return out
    except Exception as e:
        log("查證交所休市日失敗，只用週末判斷：", e)
        return set()


STATE = os.path.join(DIR, "sent_state.json")  # 記錄當天是否已發送（雲端會存回專案，避免重複發送）


def report_day():
    """晚上的報告屬於哪一天：GitHub 排程常延遲，21:07 的排程可能過午夜才跑，
    中午以前執行一律算前一天晚上的那一份（避免週六晚上的排程拖到週日凌晨，誤以為「明天開盤」而發送）。"""
    now = dt.datetime.now()
    return now.date() - dt.timedelta(days=1) if now.hour < 12 else now.date()


def sent_today(kind, day=None):
    try:
        with open(STATE, encoding="utf-8") as f:
            return json.load(f).get(kind) == (day or dt.date.today()).isoformat()
    except (OSError, ValueError):
        return False


def mark_sent(kind, day=None):
    try:
        with open(STATE, encoding="utf-8") as f:
            st = json.load(f)
    except (OSError, ValueError):
        st = {}
    st[kind] = (day or dt.date.today()).isoformat()
    with open(STATE, "w", encoding="utf-8") as f:
        json.dump(st, f)


def is_trading(d, hol):
    return d.weekday() < 5 and d not in hol


def main():
    dry, force = "--dry-run" in sys.argv, "--force" in sys.argv
    cfg_path = os.path.join(DIR, "sop_config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8")) if os.path.exists(cfg_path) else {}
    ids = [str(x) for x in (cfg.get("universe") or [])]
    if cfg.get("state") and cfg["state"].get("watch"):
        ids += [x for x in cfg["state"]["watch"] if x not in ids]
    oc = cfg.get("orders") or {}
    olist = list((oc.get("list") if isinstance(oc, dict) else oc) or []) + list((cfg.get("state") or {}).get("orders") or [])
    ids += list(dict.fromkeys(str(o["id"]) for o in olist if str(o["id"]) not in ids))  # 模擬下單的股票一定要抓
    py = sys.executable.replace("pythonw.exe", "python.exe")  # 子程式用一般 python（在背景、不開視窗）
    try:
        rday = report_day()
        if sent_today("daily", rday) and not force:
            log("今天的報告已經發送過，不重複發送。")
            return
        # 規則：明天有開盤才發；資料用最後一個交易日（今天休市就往前找）
        hol = twse_holidays()
        today = rday  # 報告所屬的那天（過午夜才跑的算前一天）
        tomorrow = today + dt.timedelta(days=1)
        if not is_trading(tomorrow, hol) and not force:
            log("明天（%s）沒有開盤，今晚不發送。" % tomorrow)
            return
        last = today
        while not is_trading(last, hol):
            last -= dt.timedelta(days=1)
        expect = last.isoformat()
        log("今天：", today, "明天開盤；報告基準日（最後收盤日）：", expect)
        try:  # 全市場粗篩（上市、上櫃、ETF）：把符合條件、但不在清單裡的也一起抓；失敗就只用原本清單
            import market_scan
            extra = market_scan.run(skip=ids)
            ids = ids + extra
            log("全市場粗篩另外加抓 %d 檔，今天共抓 %d 檔" % (len(extra), len(ids)))
        except Exception as e:
            log("全市場粗篩失敗（照原本清單跑）：", e)
        for attempt in range(3):
            cache = next((p for p in ("data_prev.json", "data.json") if os.path.exists(os.path.join(DIR, p))), None)
            run([py, "fetch_finmind.py"] + ids + ["--lite"] + (["--cache", cache] if cache else []), timeout=14400)  # 清單＋全市場粗篩約 270 檔：只抓選股需要的資料（個股 6 次、ETF 3 次請求），避免超過 FinMind 額度
            with open(os.path.join(DIR, "data.json"), encoding="utf-8") as f:
                as_of = json.load(f).get("asOf")
            log("FinMind 資料日：", as_of)
            if as_of >= expect or force:
                break
            if attempt < 2:
                log("FinMind 還沒更新到 %s，30 分鐘後重試" % expect)
                time.sleep(1800)
        else:
            raise RuntimeError("FinMind 仍沒有 %s 的資料" % expect)
        try:  # 國際新聞（Google 新聞，不佔 FinMind 額度）；失敗不影響報告
            gap = (today - last).days  # 週日晚上是 2（週五收盤到週日），連假更多
            run([py, "fetch_finmind.py", "--macro", "--news-days", str(max(3, gap + 1))], timeout=600)
        except Exception as e:
            log("國際新聞抓取失敗，略過：", e)
        try:  # 集保大戶持股（每週，集保開放資料）：存進歷史、填進 data.json；失敗不影響報告
            import tdcc
            try:
                tdcc.update()
            except Exception as e:
                log("集保最新一週抓取失敗，用已有的歷史：", e)
            tdcc.merge(os.path.join(DIR, "data.json"))
        except Exception as e:
            log("集保大戶資料失敗，略過：", e)
        try:  # 內部人申報（事前申報轉讓、董監持股）：存進歷史、填進 data.json；失敗不影響報告
            import insider
            try:
                insider.update()
            except Exception as e:
                log("內部人申報抓取失敗，用已有的歷史：", e)
            insider.merge(os.path.join(DIR, "data.json"))
        except Exception as e:
            log("內部人申報資料失敗，略過：", e)
        run(["node", "daily_report.js", "data.json", "sop_config.json"], timeout=900)
        try:  # 大盤偏弱（國際風險高或 0050 跌破季線）時，只因量價突破入選的改成先觀望
            import analysis
            pp = os.path.join(DIR, "sop_plan.json")
            if os.path.exists(pp):
                P = json.load(open(pp, encoding="utf-8"))
                weak = analysis.market_weak(P)
                n = analysis.guard_breakout(P, weak)
                nc = analysis.guard_cycle(P, json.load(open(os.path.join(DIR, "data.json"), encoding="utf-8")))  # 循環股在平均高點附近
                if n or nc:
                    json.dump(P, open(pp, "w", encoding="utf-8"), ensure_ascii=False)
                log("大盤：%s；追強勢（量價突破／穩健動能）改先觀望 %d 檔；循環股在高檔改先觀望 %d 檔" % (weak or "不弱", n, nc))
        except Exception as e:
            log("大盤偏弱檢查失敗，略過：", e)
        PRIV = "report_line_private.txt"  # 只給自己（發 Discord，不佔 LINE 額度）：持股、買賣紀錄；群發的 report_line.txt 不放持股
        open(os.path.join(DIR, PRIV), "w", encoding="utf-8").close()

        def add(names, text, front=False):
            for name in names:
                p = os.path.join(DIR, name)
                old = open(p, encoding="utf-8").read().strip() if os.path.exists(p) else ""
                with open(p, "w", encoding="utf-8") as f:
                    f.write((text + ("\n\n━━━━━━━━━━\n\n" + old if old else "")) if front else ((old + "\n\n━━━━━━━━━━\n\n" if old else "") + text))

        ld = lambda n, d=None: json.load(open(os.path.join(DIR, n), encoding="utf-8")) if os.path.exists(os.path.join(DIR, n)) else d
        try:  # 重點個股解析：業務、上下游、為何可能上漲、循環股與否、目標價（接在名單後面）
            import analysis
            data, plan, prof = ld("data.json"), ld("sop_plan.json", {}), ld("stock_profiles.json", {})
            atext = analysis.build(data, cfg, plan, prof)  # Discord：持股＋名單前幾檔
            if atext:
                add(["report_discord.txt"], atext)
            log("重點個股解析已加入報告")
        except Exception as e:
            log("重點個股解析失敗，略過：", e)
        try:  # 持股賣出提醒：已實際買進的股票該不該賣、為什麼（放在最前面）；sell_plan.json 給隔天開盤檢查用
            import exits
            xtext, xplan = exits.build(ld("data.json"), cfg, ld("stock_profiles.json", {}))
            with open(os.path.join(DIR, "sell_plan.json"), "w", encoding="utf-8") as f:
                json.dump(xplan or {"date": None, "holds": []}, f, ensure_ascii=False, indent=1)
            if xtext:
                add(["report_discord.txt", PRIV], xtext, front=True)
                log("持股賣出提醒已加入報告（只給自己）")
        except Exception as e:
            log("持股賣出提醒失敗，略過：", e)
        try:  # 持股相關新聞（公司＋原料，例如華新看銅、鎳、不銹鋼）整理，附利多／利空（只給自己）
            import alert
            ntext = alert.digest(cfg, ld("stock_profiles.json", {}), ld("sell_plan.json", {}))
            if ntext:
                add(["report_discord.txt", PRIV], ntext)
                log("持股相關新聞已加入報告（只給自己）")
        except Exception as e:
            log("持股相關新聞失敗，略過：", type(e).__name__)
        try:  # 模擬下單（daily_report.js 產生）：有沒有成交、今天賺多少（只給自己）
            op = os.path.join(DIR, "report_orders.txt")
            otext = open(op, encoding="utf-8").read().strip() if os.path.exists(op) else ""
            if otext:
                add(["report_discord.txt", PRIV], otext)
                log("模擬下單已加入報告（只給自己）")
        except Exception as e:
            log("模擬下單計算失敗，略過：", e)
        try:  # 自選觀察：走勢、法人、營收、近 3 天新聞（只給自己）
            import watch
            wids = [str(x) for x in ((cfg.get("state") or {}).get("watch") or [])]
            if wids:
                import fetch_finmind
                fetch_finmind.load_env()
                fetch_finmind.TOKEN = os.environ.get("FINMIND_TOKEN") or os.environ.get("TSL_FINMIND_TOKEN", "")
                wtx = watch.build(ld("data.json"), wids, ld("stock_profiles.json", {}), fetch_finmind.get,
                                  plan_rows={r["id"]: r for r in ld("sop_plan.json", {}).get("rows", [])})
                if wtx:
                    add(["report_discord.txt", PRIV], wtx)
                    log("自選觀察已加入報告（只給自己）")
        except Exception as e:
            log("自選觀察失敗，略過：", e)
        cycle = ""
        try:  # 循環股谷底轉強（復盤學到的規則）；每檔附建議
            import review
            cycle = review.cycle_alerts(ld("data.json"), ld("stock_profiles.json", {}))
            if cycle:
                add(["report_discord.txt"], cycle)
                log("循環股谷底轉強提醒已加入報告")
        except Exception as e:
            log("循環股谷底轉強掃描失敗，略過：", e)
        try:  # 飆股前兆（2026-10 研究：長紅 K＋營收創新高／投信連買）
            import rocket
            rk = rocket.scan(ld("data.json"), ld("stock_profiles.json", {}))
            if rk:
                add(["report_discord.txt"], rk)
                log("飆股前兆已加入報告")
        except Exception as e:
            log("飆股前兆掃描失敗，略過：", e)
        if (today - last).days >= 2:  # 每週復盤（週日或連假最後一天晚上）：檢討每筆買賣，賺的賠的都記到 lessons.json
            try:
                import review
                rtext, les = review.review_trades(ld("data.json"), cfg, ld("stock_profiles.json", {}))
                if rtext:
                    add(["report_discord.txt", PRIV], rtext)
                    new = review.save_lessons(les)
                    log("每週復盤已加入報告，新增 %d 條教訓" % len(new))
            except Exception as e:
                log("每週復盤失敗，略過：", e)
        if os.path.getsize(os.path.join(DIR, PRIV)):
            add([PRIV], "🔒 只給你：持股與買賣（%s 收盤）" % expect, front=True)
        if (today - last).days >= 2:  # 週日或連假最後一天晚上：整合休市期間的國際新聞與名單個股新聞
            try:
                import fetch_finmind
                import weekend
                fetch_finmind.load_env()
                fetch_finmind.TOKEN = os.environ.get("FINMIND_TOKEN") or os.environ.get("TSL_FINMIND_TOKEN", "")
                wtext = weekend.build(last, today, fetch_finmind.get)
                add(["report_discord.txt"], wtext)
                log("週末綜合已加入報告")
            except Exception as e:
                log("週末綜合失敗，略過：", e)
        try:  # 精簡版：LINE 群發與 Discord 本文都用這份（一檔一行、每檔有建議）；完整版當 Discord 附檔
            import brief
            btext = brief.build(ld("sop_plan.json", {}), ld("data.json"), ld("stock_profiles.json", {}), cycle)
            if (today - last).days >= 2 and "wtext" in locals():  # 週末只放國際新聞重點，個股新聞在附檔
                btext += "\n\n" + "\n".join(wtext.split("名單個股新聞")[0].strip().splitlines()[:12])
            with open(os.path.join(DIR, "report_line.txt"), "w", encoding="utf-8") as f:
                f.write(btext)
            log("精簡版報告 %d 字（完整版 %d 字當附檔）" % (len(btext), os.path.getsize(os.path.join(DIR, "report_discord.txt"))))
        except Exception as e:
            log("精簡版產生失敗，用完整版：", e)
        if dry:
            log("--dry-run：只產生報告，不發送。報告在 report_discord.txt、report_line.txt")
            return
        size = lambda n: os.path.getsize(os.path.join(DIR, n)) if os.path.exists(os.path.join(DIR, n)) else 0
        if not size("report_line.txt") and not size("report_line_private.txt"):
            log("今天所有策略都沒有選出股票、也沒有持股，不發送。")
            return
        att, imgs = ["report_discord.txt"], []
        try:  # 完整版做成 Word 檔：你的完整版（含持股）＋家人的分享版（不含持股）
            import fullreport
            att = [os.path.relpath(fullreport.main(True), DIR), os.path.relpath(fullreport.main(False), DIR)]
            log("Word 檔：", "、".join(att))
        except Exception as e:
            log("Word 檔產生失敗，改附文字檔：", e)
        try:  # 推薦總表＋前幾檔「為什麼可以買」詳細原因，畫成四張圖（LINE 直接看，不用開檔案）
            import detail_img
            P = ld("sop_plan.json", {})
            allh = [r for r in P.get("rows", []) if r.get("state") == "hold"]
            hold = [r for r in allh if not str(r.get("hold_why", "")).startswith("循環股")]
            cyc_h = [r for r in allh if str(r.get("hold_why", "")).startswith("循環股")]
            notes = ["風險偏高（%s）：只因量價突破／穩健動能入選的 %d 檔先觀望（%s）" % (hold[0].get("hold_why", ""), len(hold), "、".join(r["name"] for r in hold[:12]))] if hold else []
            if cyc_h:
                notes.append("循環股在高檔先觀望（已到近 5 年平均高點附近）：%s" % "、".join(r["name"] for r in cyc_h[:12]))
            notes += [x for x in (cycle or "").split("\n") if x.strip()]  # 循環股谷底轉強
            macro = [m.get("title", "") for m in (ld("data.json", {}).get("macro") or [])[:5] if m.get("title")]
            if macro:
                notes += ["國際新聞：" + "；".join(macro)]
            imgs = [os.path.relpath(x, DIR) for x in detail_img.build(P, ld("data.json"), ld("stock_profiles.json", {}), notes=notes)]
            log("推薦圖卡：", "、".join(imgs))
        except Exception as e:
            log("推薦圖卡產生失敗，改用總表圖片：", e)
            try:
                import table_img
                R = json.load(open(os.path.join(DIR, "report_full_share.json"), encoding="utf-8"))
                imgs = [os.path.relpath(x, DIR) for x in table_img.build(R["summary"], R["date"], R["risk"])]
            except Exception as e2:
                log("總表圖片也失敗，略過：", e2)
        lp = os.path.join(DIR, "discord_files.json")
        if os.path.exists(lp):
            os.remove(lp)
        cmd = [py, "send_report.py", "report_line.txt", "--discord-only"]
        for a in att + imgs:
            cmd += ["--attach", a]
        try:
            run(cmd, timeout=180)  # Discord：本文精簡版＋Word 與總表圖片附檔（同時取得檔案網址給 LINE 用）
        except Exception as e:  # Discord 失敗不影響 LINE
            log("Discord 發送失敗：", e)
        ex_pub = ex_priv = None
        try:  # LINE 不能傳檔案：推薦總表與原因放圖片、Word 放「打開完整報告」按鈕（檔案在 Discord，約 24 小時內有效）
            links = json.load(open(lp, encoding="utf-8")) if os.path.exists(lp) else {}
            def button(url, title, label="打開完整報告", note="全部股票的詳細說明與買賣建議（Word 檔，24 小時內有效，記得存到手機）"):
                if len(url) > 1000:
                    return None
                return {"type": "flex", "altText": title, "contents": {"type": "bubble",
                        "body": {"type": "box", "layout": "vertical", "contents": [
                            {"type": "text", "text": title, "weight": "bold", "size": "md", "wrap": True},
                            {"type": "text", "text": note, "size": "sm", "color": "#666666", "wrap": True}]},
                        "footer": {"type": "box", "layout": "vertical", "contents": [
                            {"type": "button", "style": "primary", "color": "#0D6C7B", "action": {"type": "uri", "label": label, "uri": url}}]}}}
            pics = [{"type": "image", "originalContentUrl": links[os.path.basename(x)], "previewImageUrl": links[os.path.basename(x)]}
                    for x in imgs if os.path.basename(x) in links][:4]
            pub = next((u for n, u in links.items() if "分享版" in n and n.endswith(".docx")), None)
            mine = next((u for n, u in links.items() if n.endswith(".docx") and "分享版" not in n), None)
            ex_pub = pics + [b for b in [pub and button(pub, "📄 完整報告（%s）" % expect)] if b]
            ex_priv = [b for b in [mine and button(mine, "📄 你的完整報告（含持股）")] if b]
            for name, ex in (("line_extra.json", ex_pub), ("line_extra_private.json", ex_priv)):
                with open(os.path.join(DIR, name), "w", encoding="utf-8") as f:
                    json.dump(ex, f, ensure_ascii=False)
            log("LINE 附加：圖卡 %d 張、按鈕 %d 個" % (len(pics), len(ex_pub) - len(pics)))
            if imgs and not pics:
                log("⚠️ 圖卡有產生但拿不到 Discord 檔案網址，LINE 只會發文字；Discord 回傳的檔名：", list(links))
        except Exception as e:
            log("LINE 圖片／按鈕準備失敗，只發文字：", e)
        if size("report_line.txt"):
            run([py, "send_report.py", "report_line.txt", "--line-only", "--images-only"] + (["--extra", "line_extra.json"] if ex_pub else []), timeout=120)  # 群發給所有好友
        if size("report_line_private.txt"):
            run([py, "send_report.py", "report_line_private.txt", "--discord-only"], timeout=120)  # 持股與買賣只給自己：發 Discord，不佔 LINE 額度（你的完整版 Word 已在 Discord 附檔）
        mark_sent("daily", rday)
        log("完成")
    except Exception as e:
        log("錯誤：", e)
        if not dry:  # 失敗時送一則簡短通知到 Discord，方便知道今天沒發成功
            try:
                with open(os.path.join(DIR, "report_error.txt"), "w", encoding="utf-8") as f:
                    f.write("⚠️ 條件選股室每日報告失敗：%s\n請查看 logs/%s" % (e, os.path.basename(LOG)))
                subprocess.run([py, "send_report.py", "report_error.txt", "--discord-only"], cwd=DIR, timeout=120, creationflags=NO_WINDOW)
            except Exception:
                pass
        sys.exit(1)


if __name__ == "__main__":
    main()
