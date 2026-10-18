"""
table_img.py - 把全部股票總表畫成圖片（給 LINE 群發直接看，不用開檔案）
每張最多 25 檔，最多 3 張（LINE 一次最多 5 則：文字＋3 張圖＋按鈕）
"""
import glob
import os

from PIL import Image, ImageDraw, ImageFont

DIR = os.path.dirname(os.path.abspath(__file__))
FONTS = ["/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc", "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc",
         "/usr/share/fonts/truetype/wqy/wqy-zenhei.ttc", "/usr/share/fonts/truetype/wqy/wqy-microhei.ttc"]


def font(size, bold=False):
    cands = [f for f in FONTS if os.path.exists(f)] + glob.glob("/usr/share/fonts/**/*CJK*", recursive=True)
    if bold:
        cands = [f for f in cands if "Bold" in f] + cands
    for f in cands:
        try:
            return ImageFont.truetype(f, size)
        except Exception:
            continue
    raise RuntimeError("找不到中文字型（GitHub Actions 要先 apt-get install fonts-noto-cjk）")


COLS = [("股票", 360), ("收盤", 120), ("建議", 140), ("買進區間", 220), ("停損", 120), ("目標", 130)]
W = sum(w for _, w in COLS) + 40
ROW = 46
COLOR = {"head": (13, 108, 123), "ok": (232, 245, 240), "wait": (253, 246, 227), "line": (216, 222, 227), "ink": (19, 27, 35), "sub": (79, 94, 107)}


def draw(rows, title, sub, out):
    f, fb, ft = font(24), font(24, True), font(32, True)
    H = 40 + 46 + 34 + ROW * (len(rows) + 1) + 40
    im = Image.new("RGB", (W, H), "white")
    d = ImageDraw.Draw(im)
    d.text((20, 20), title, font=ft, fill=COLOR["head"])
    d.text((20, 66), sub, font=font(20), fill=COLOR["sub"])
    y = 110
    d.rectangle([20, y, W - 20, y + ROW], fill=COLOR["head"])
    x = 20
    for name, w in COLS:
        d.text((x + 10, y + 9), name, font=fb, fill="white")
        x += w
    y += ROW
    for r in rows:
        d.rectangle([20, y, W - 20, y + ROW], fill=COLOR["ok"] if "可買" in r["act"] else COLOR["wait"])
        vals = ["%s %s" % (r["id"], r["name"]), r["close"], r["act"].replace("🟢 ", "").replace("🟡 ", "").replace("⚪ ", ""), r["zone"], r["stop"], r["t1"]]
        x = 20
        for (name, w), v in zip(COLS, vals):
            v = str(v)
            while d.textlength(v, font=f) > w - 16 and len(v) > 2:  # 太長就截短
                v = v[:-2] + "…"
            d.text((x + 10, y + 9), v, font=fb if name == "建議" else f, fill=COLOR["ink"])
            x += w
        d.line([20, y + ROW, W - 20, y + ROW], fill=COLOR["line"], width=1)
        y += ROW
    d.text((20, y + 8), "收盤跌破停損就出場；國際風險高時只買一半。依固定規則計算，不是投資建議。", font=font(18), fill=COLOR["sub"])
    im.save(out, "PNG", optimize=True)
    return out


def build(summary, date, risk, per=25, max_img=3):
    """summary：fullreport 的總表列；回傳圖片路徑清單"""
    rows = summary[:per * max_img]
    outs = []
    for i in range(0, len(rows), per):
        part = rows[i:i + per]
        n = i // per + 1
        title = "條件選股室｜%s 收盤總表%s" % (date, "（%d/%d）" % (n, (len(rows) + per - 1) // per) if len(rows) > per else "")
        sub = "國際風險：%s｜第 %d～%d 檔（依建議與健檢分數排序）" % (risk, i + 1, i + len(part))
        outs.append(draw(part, title, sub, os.path.join(DIR, "總表_%s_%d.png" % (date, n))))
    return outs
