"""
morning_img.py - 早上開盤檢查畫成圖卡（LINE 群發只發圖，跟晚上一樣）
內容：開盤前觀察（台指期夜盤、美股）＋昨晚推薦每一檔的開盤價與建議（可買／等待／不要買＋原因、停損）
最多 4 張、每張 6000 像素與 1MB 內（LINE 預覽圖上限），放不下的才註明看 Discord
"""
import os

from PIL import Image, ImageDraw

from detail_img import C, PAD, W, MAXH, clean, save, wrap
from table_img import font

DIR = os.path.dirname(os.path.abspath(__file__))
COL = {"buy": C["ok"], "wait": C["wait"], "no": (190, 50, 50), "none": C["hold"]}
BG = {"buy": (232, 245, 240), "wait": (253, 246, 227), "no": (250, 235, 235), "none": (240, 242, 244)}


def pre_block(d, y, pre, measure=False):
    """開盤前觀察；回傳高度"""
    f, fb = font(23), font(25, True)
    rows = [r for x in pre.splitlines() if clean(x) for r in wrap(d, clean(x), f, W - 2 * PAD - 28)]
    h = 56 + len(rows) * 34 + 20
    if not measure:
        d.rectangle([PAD, y, W - PAD, y + h - 12], fill=C["card"])
        d.text((PAD + 14, y + 12), "開盤前觀察", font=fb, fill=C["head"])
        for i, r in enumerate(rows):
            d.text((PAD + 14, y + 52 + i * 34), r, font=f, fill=C["ink"])
    return h


def head_block(d, y, k, title, measure=False):
    if not measure:
        d.rectangle([PAD, y, W - PAD, y + 50], fill=COL[k])
        d.text((PAD + 16, y + 9), clean(title), font=font(27, True), fill="white")
    return 62


def line_block(d, y, k, line, measure=False):
    """一檔：第一段（代號 名稱 開盤價）粗體，後面（建議：原因｜停損）換行"""
    parts = clean(line).lstrip("・").split("｜")
    f, fb = font(24), font(25, True)
    tw = W - 2 * PAD - 32
    top = wrap(d, parts[0], fb, tw)
    rest = wrap(d, "　".join(parts[1:]), f, tw) if len(parts) > 1 else []
    h = len(top) * 36 + len(rest) * 34 + 20
    if not measure:
        d.rectangle([PAD, y, W - PAD, y + h - 6], fill=BG[k])
        d.rectangle([PAD, y, PAD + 6, y + h - 6], fill=COL[k])
        yy = y + 8
        for r in top:
            d.text((PAD + 20, yy), r, font=fb, fill=C["ink"])
            yy += 36
        for r in rest:
            d.text((PAD + 20, yy), r, font=f, fill=COL[k] if k != "none" else C["sub"])
            yy += 34
    return h + 4


def build(title, sub, pre, sections, n_img=4):
    """sections：[(群組代號, 標題, [每檔一行文字])]；回傳圖檔路徑"""
    tmp = ImageDraw.Draw(Image.new("RGB", (W, 10)))
    blocks = []
    if pre:
        blocks.append((pre_block(tmp, 0, pre, True), lambda d, y: pre_block(d, y, pre)))
    for k, t, lines in sections:
        if not lines:
            continue
        blocks.append((head_block(tmp, 0, k, t, True), lambda d, y, k=k, t=t: head_block(d, y, k, t)))
        for x in lines:
            blocks.append((line_block(tmp, 0, k, x, True), lambda d, y, k=k, x=x: line_block(d, y, k, x)))
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
        if cur:
            pages.append(cur)
    left = len(blocks) - sum(len(p) for p in pages)
    outs = []
    for n, part in enumerate(pages, 1):
        foot = "還有 %d 項放不下，請看 Discord 文字版。" % left if left and n == len(pages) else ""
        H = 120 + sum(bh for bh, _ in part) + (100 if foot else 60)
        im = Image.new("RGB", (W, H), "white")
        d = ImageDraw.Draw(im)
        d.text((PAD, 24), "%s%s" % (clean(title), "（%d/%d）" % (n, len(pages)) if len(pages) > 1 else ""), font=font(34, True), fill=C["head"])
        d.text((PAD, 74), clean(sub), font=font(22), fill=C["sub"])
        y = 120
        for bh, fn in part:
            fn(d, y)
            y += bh
        if foot:
            d.text((PAD, H - 84), foot, font=font(22, True), fill=C["wait"])
        d.text((PAD, H - 44), "依開盤價與固定規則判斷，不是投資建議。收盤跌破停損就出場。", font=font(20), fill=C["sub"])
        outs.append(save(im, os.path.join(DIR, "開盤_%d.png" % n)))
    return outs
