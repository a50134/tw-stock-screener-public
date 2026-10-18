"""
detail_img.py - 推薦股票的「為什麼可以買」詳細圖卡（手機直接看，不用開 Word）
每檔一張卡：標題列（代號 名稱 收盤＋建議）＋入選策略、業務、上下游、優勢、為何可能上漲、走勢、基本面、法人、循環股、目標、風險
內容沿用 analysis.block（和 Word 完整版同一份文字）；最多四張、每張 1MB 內（LINE 預覽圖上限）：全部名單總表、今晚重點、推薦股完整原因、其餘股票精簡原因，依序裝滿（LINE 一次最多 5 則：4 張圖＋按鈕，不發文字）

用法：python detail_img.py   （讀 data.json、sop_plan.json、stock_profiles.json，輸出 推薦_日期_N.png）
"""
import json
import os
import re

from PIL import Image, ImageDraw

import analysis
import brief
from table_img import font

DIR = os.path.dirname(os.path.abspath(__file__))
W, PAD, LBL = 1080, 28, 168  # 圖寬、左右留白、標籤欄寬
C = {"head": (13, 108, 123), "ok": (22, 128, 74), "wait": (176, 120, 20), "hold": (110, 120, 130),
     "ink": (19, 27, 35), "sub": (79, 94, 107), "line": (216, 222, 227), "card": (247, 250, 251), "why": (232, 245, 240)}
SHOW = {"為何可能上漲": "為何會漲", "是循環股嗎": "循環股？", "推估目標": "目標價"}  # 標籤太長的縮短
MINI = ["建議", "為何可能上漲", "主要業務"]  # 精簡卡（其餘股票；價格區間與目標已在總表）
ORDER = ["建議", "入選策略", "為何可能上漲", "循環位置", "主要業務", "上游", "下游", "優勢", "營收", "籌碼", "技術面", "最近走勢", "基本面", "是循環股嗎", "推估目標", "風險"]


def wrap(d, text, f, width):
    """中文逐字換行；數字（含小數點、%、正負號）不拆開"""
    toks = re.findall(r"[0-9A-Za-z.,%+\-～~]+|.", text)
    lines, cur = [], ""
    for tk in toks:
        if cur and d.textlength(cur + tk, font=f) > width:
            lines.append(cur)
            cur = tk.lstrip()
        else:
            cur += tk
    if cur:
        lines.append(cur)
    return lines or [""]


def fields(text):
    """analysis.block 的文字拆成 (標題, {標籤: 內容})"""
    L = text.split("\n")
    out = {}
    for x in L[1:]:
        x = x.lstrip("・")
        if x.startswith("入選策略："):
            a = x[5:].split("｜")
            out["入選策略"] = a[0] + ("（" + a[1] + "）" if len(a) > 1 else "")
        elif x.startswith("上游："):
            up, _, down = x[3:].partition("；下游：")
            out["上游"], out["下游"] = up, down
        elif "：" in x:
            k, _, v = x.partition("：")
            out[k] = v
    return L[0], out


def card(d, y, head, F, act, measure=False, order=None):
    """畫一張卡；measure=True 只算高度"""
    f, fb, fh = font(25), font(25, True), font(31, True)
    tw = W - 2 * PAD - LBL - 24
    h0 = y
    col = C["ok"] if act.startswith("🟢") else C["hold"] if act.startswith("⚪") else C["wait"]
    if not measure:
        d.rectangle([PAD, y, W - PAD, y + 62], fill=C["head"])
        d.text((PAD + 18, y + 13), head.replace("【", "").replace("】", "  "), font=fh, fill="white")
    y += 74
    for k in order or ORDER:
        v = F.get(k)
        if not v:
            continue
        v = v.replace("🟢 ", "").replace("🟡 ", "").replace("⚪ ", "")
        rows = wrap(d, v, fb if k in ("建議", "為何可能上漲") else f, tw)
        hh = len(rows) * 36 + 14
        if not measure:
            if k in ("建議", "為何可能上漲"):
                d.rectangle([PAD, y - 4, W - PAD, y + hh - 6], fill=C["why"] if k == "為何可能上漲" else (255, 255, 255))
            d.text((PAD + 14, y), SHOW.get(k, k), font=fb, fill=col if k == "建議" else C["sub"])
            for i, r in enumerate(rows):
                d.text((PAD + LBL, y + i * 36), r, font=fb if k in ("建議", "為何可能上漲") else f,
                       fill=col if k == "建議" else C["ink"])
            d.line([PAD, y + hh - 6, W - PAD, y + hh - 6], fill=C["line"], width=1)
        y += hh
    return y + 24 - h0


TCOLS = [("股票", 330), ("收盤", 120), ("建議", 120), ("買進區間", 220), ("停損", 110), ("目標", 124)]


def table(d, y, rows, measure=False):
    """推薦總表（可買＋等拉回，一檔一列）；回傳高度"""
    f, fb, R = font(23), font(23, True), 42
    h = (len(rows) + 1) * R + 70
    if measure:
        return h
    d.text((PAD, y), "今晚全部名單（%d 檔，依建議與健檢分數排序；下面有每檔原因）" % len(rows), font=font(27, True), fill=C["head"])
    y += 48
    d.rectangle([PAD, y, W - PAD, y + R], fill=C["head"])
    x = PAD
    for n, w in TCOLS:
        d.text((x + 8, y + 8), n, font=fb, fill="white")
        x += w
    y += R
    for r in rows:
        ok, hold = r.get("state") == "ok", r.get("state") == "hold"
        d.rectangle([PAD, y, W - PAD, y + R], fill=(232, 245, 240) if ok else (240, 242, 244) if hold else (253, 246, 227))
        vals = ["%s %s" % (r["id"], r["name"]), analysis.px(r["prev"]), "可買" if ok else "觀望" if hold else "等拉回",
                "%s～%s" % (analysis.px(r["lo"]), analysis.px(r["hi"])), analysis.px(r["stop"]), analysis.px(r["t1"]) if r.get("t1") else "—"]
        x = PAD
        for (n, w), v in zip(TCOLS, vals):
            v = str(v)
            while d.textlength(v, font=f) > w - 14 and len(v) > 2:
                v = v[:-2] + "…"
            d.text((x + 8, y + 8), v, font=fb if n == "建議" else f, fill=(C["ok"] if ok else C["hold"] if hold else C["wait"]) if n == "建議" else C["ink"])
            x += w
        d.line([PAD, y + R, W - PAD, y + R], fill=C["line"], width=1)
        y += R
    return h


def clean(x):
    """圖上字型沒有 emoji：去掉表情符號"""
    return re.sub(r"[\U0001F000-\U0001FFFF\u2600-\u27BF\uFE0F]", "", x).strip()


def notes_block(d, y, notes, measure=False):
    """今晚重點（先觀望、循環股谷底轉強等）；回傳高度"""
    if not notes:
        return 0
    f, fb = font(23), font(25, True)
    tw = W - 2 * PAD - 28
    rows = [r for n in notes for r in wrap(d, clean(n), f, tw)]
    h = 56 + len(rows) * 34 + 20
    if not measure:
        d.rectangle([PAD, y, W - PAD, y + h - 12], fill=(253, 246, 227))
        d.text((PAD + 14, y + 12), "今晚重點", font=fb, fill=C["wait"])
        for i, r in enumerate(rows):
            d.text((PAD + 14, y + 52 + i * 34), r, font=f, fill=C["ink"])
    return h


MAXH = 6000      # 每張圖最高（太長手機看會糊）
MAXB = 950_000   # LINE 預覽圖上限 1MB（原圖與預覽用同一張）


def save(im, out):
    """存成 1MB 以內：先試 PNG，太大改 JPEG 逐步降畫質"""
    im.save(out, "PNG", optimize=True)
    if os.path.getsize(out) <= MAXB:
        return out
    os.remove(out)
    out = out[:-4] + ".jpg"
    for q in (85, 75, 65, 55, 45):
        im.save(out, "JPEG", quality=q, optimize=True)
        if os.path.getsize(out) <= MAXB:
            break
    return out


def build(plan, data, profiles, n_img=4, top_ok=8, top_wait=5, notes=None):
    """最多 n_img 張圖、每張 1MB 內，盡量放進全部資訊：
    全部名單總表 → 今晚重點 → 推薦股完整原因卡 → 其餘股票精簡卡（放不下的才省略，並註明看 Word）"""
    by = {s["id"]: s for s in data["stocks"]}
    t = len(data["dates"]) - 1
    allrows = [r for r in plan.get("rows", []) if r.get("lo") and r.get("stop") and r["id"] in by]
    if not allrows:
        return []
    ok, wait, rest = brief.pick(plan, top_ok, top_wait)
    hold = [r for r in allrows if r.get("state") == "hold"]
    key = lambda r: -(r.get("score") or 0)
    table_rows = [r for r in ok + wait + sorted(rest, key=lambda r: (r.get("state") != "ok", key(r))) + sorted(hold, key=key) if r["id"] in by]
    full = [r for r in ok + wait if r["id"] in by and not str(r["id"]).startswith("00")]
    mini = [r for r in table_rows if r not in full]

    def item(r):
        s = by[r["id"]]
        head, F = fields(analysis.block(s, analysis.facts(s, t), profiles.get(r["id"]), r))
        F["建議"] = analysis.advise(s, t, r)
        return head, F

    tmp = ImageDraw.Draw(Image.new("RGB", (W, 10)))
    blocks = [(table(tmp, 0, table_rows, True), lambda d, y: table(d, y, table_rows))]
    if notes:
        blocks.append((notes_block(tmp, 0, notes, True), lambda d, y: notes_block(d, y, notes)))
    for kind, rows in (("full", full), ("mini", mini)):
        for r in rows:
            h, F = item(r)
            o = None if kind == "full" else MINI
            blocks.append((card(tmp, 0, h, F, F["建議"], True, o), lambda d, y, h=h, F=F, o=o: card(d, y, h, F, F["建議"], False, o)))
    # 依序裝進最多 n_img 張；每張扣掉標題 120＋頁尾 60
    pages, cur, used = [], [], 0
    for bh, fn in blocks:
        if cur and used + bh > MAXH - 180:
            pages.append(cur)
            cur, used = [], 0
            if len(pages) == n_img:
                break
        cur.append((bh, fn))
        used += bh
    else:
        pages.append(cur)
    shown = sum(len(p) for p in pages)
    left = len(blocks) - shown
    date = plan.get("date") or data.get("asOf", "")
    outs = []
    for n, part in enumerate(pages, 1):
        foot = "還有 %d 檔放不下，請按「打開完整報告」看 Word。" % left if left and n == len(pages) else ""
        H = 120 + sum(bh for bh, _ in part) + (100 if foot else 60)
        im = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(im)
        d.text((PAD, 24), "條件選股室｜推薦與原因（%d/%d）" % (n, len(pages)), font=font(34, True), fill=C["head"])
        d.text((PAD, 74), "%s 收盤｜國際風險：%s｜依建議與健檢分數排序" % (date, plan.get("risk", "—")), font=font(22), fill=C["sub"])
        y = 120
        for bh, fn in part:
            fn(d, y)
            y += bh
        if foot:
            d.text((PAD, H - 84), foot, font=font(22, True), fill=C["wait"])
        d.text((PAD, H - 44), "收盤跌破停損就出場；國際風險高時只買一半。依固定規則計算，不是投資建議。", font=font(20), fill=C["sub"])
        outs.append(save(im, os.path.join(DIR, "推薦_%s_%d.png" % (date, n))))
    return outs


if __name__ == "__main__":
    ld = lambda n, dft=None: json.load(open(os.path.join(DIR, n), encoding="utf-8")) if os.path.exists(os.path.join(DIR, n)) else dft
    for p in build(ld("sop_plan.json", {}), ld("data.json"), ld("stock_profiles.json", {})):
        print(p)
