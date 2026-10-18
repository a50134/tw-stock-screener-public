"""
cards.py - 把今晚的推薦圖卡存進「歷史圖卡」資料夾（網頁版可依日期翻看）

用法：python cards.py 資料夾   （把專案裡的 推薦_日期_N.png/jpg 複製成 資料夾/日期_N.副檔名，
      只留最近 KEEP 個日期，並重寫 資料夾/index.json）
"""
import glob
import json
import os
import re
import shutil
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
KEEP = 20  # 約一個月的交易日（每天 4 張、約 3.5MB）
PAT = re.compile(r"^(\d{4}-\d{2}-\d{2})_(\d+)\.(png|jpg)$")


def save(out):
    os.makedirs(out, exist_ok=True)
    new = sorted(glob.glob(os.path.join(DIR, "推薦_*_*.png")) + glob.glob(os.path.join(DIR, "推薦_*_*.jpg")))
    for d in {re.search(r"推薦_(\d{4}-\d{2}-\d{2})_", f).group(1) for f in new if re.search(r"推薦_(\d{4}-\d{2}-\d{2})_", f)}:
        for f in glob.glob(os.path.join(out, d + "_*")):  # 同一天重跑：先清掉舊的
            os.remove(f)
    for f in new:
        m = re.search(r"推薦_(\d{4}-\d{2}-\d{2})_(\d+)\.(png|jpg)$", f)
        if m:
            shutil.copy(f, os.path.join(out, "%s_%s.%s" % m.groups()))
    days = {}
    for f in os.listdir(out):
        m = PAT.match(f)
        if m:
            days.setdefault(m.group(1), []).append((int(m.group(2)), f))
    keep = sorted(days, reverse=True)[:KEEP]
    for d in set(days) - set(keep):
        for _, f in days[d]:
            os.remove(os.path.join(out, f))
    idx = {"days": [{"d": d, "f": [f for _, f in sorted(days[d])]} for d in keep]}
    json.dump(idx, open(os.path.join(out, "index.json"), "w", encoding="utf-8"), ensure_ascii=False)
    print("歷史圖卡：%d 天（最新 %s）" % (len(keep), keep[0] if keep else "—"))
    return idx


if __name__ == "__main__":
    save(sys.argv[1])
