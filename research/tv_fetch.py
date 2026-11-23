"""
tv_fetch.py - 抓「錢線百分百」最近幾集的 YouTube 標題、簡介、自動字幕（給 Claude 讀，整理節目提到的選股策略再回測）

用法：python research/tv_fetch.py 輸出資料夾 [天數=3]
結果：輸出資料夾/日期_影片代號.json（title、date、url、desc、subs 純文字），已經抓過的會跳過
需要：pip install yt-dlp
"""
import datetime as dt
import glob
import json
import os
import re
import subprocess
import sys

OUT = sys.argv[1] if len(sys.argv) > 1 else "tv"
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
QUERY = "https://www.youtube.com/results?search_query=%E9%8C%A2%E7%B7%9A%E7%99%BE%E5%88%86%E7%99%BE+%E5%AE%8C%E6%95%B4%E7%89%88&sp=CAI%253D"  # 錢線百分百 完整版，依上傳日期排序


def vtt_text(path):
    """字幕檔 → 去掉時間碼與重複行的純文字"""
    out, last = [], ""
    for line in open(path, encoding="utf-8", errors="ignore"):
        line = re.sub(r"<[^>]+>", "", line).strip()
        if not line or "-->" in line or line.startswith(("WEBVTT", "Kind:", "Language:")) or line.isdigit():
            continue
        if line != last:
            out.append(line)
            last = line
    return "".join(x if re.search(r"[，。！？]$", x) else x + "，" for x in out)


def main():
    os.makedirs(OUT, exist_ok=True)
    since = (dt.date.today() - dt.timedelta(days=DAYS)).strftime("%Y%m%d")
    r = subprocess.run(["yt-dlp", "--flat-playlist", "--playlist-end", "25", "-J", QUERY], capture_output=True, text=True)
    if r.returncode:
        print("搜尋失敗：", r.stderr[-500:])
        sys.exit(1)
    items = [e for e in json.loads(r.stdout).get("entries") or [] if "錢線百分百" in (e.get("title") or "")]
    print("搜尋到 %d 支" % len(items))
    done = {os.path.basename(p).split("_", 1)[1][:-5] for p in glob.glob(os.path.join(OUT, "*_*.json"))}
    tmp = "/tmp/tvsub"
    os.makedirs(tmp, exist_ok=True)
    n = 0
    for e in items:
        vid = e["id"]
        if vid in done:
            continue
        url = "https://www.youtube.com/watch?v=" + vid
        info = subprocess.run(["yt-dlp", "-J", "--skip-download", url], capture_output=True, text=True)
        if info.returncode:
            print("讀不到：", vid, info.stderr[-200:])
            continue
        j = json.loads(info.stdout)
        if (j.get("upload_date") or "0") < since:
            continue
        for f in glob.glob(tmp + "/*"):
            os.remove(f)
        subprocess.run(["yt-dlp", "--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "zh-Hant,zh-TW,zh-Hans,zh.*",
                        "--sub-format", "vtt", "-o", tmp + "/%(id)s.%(ext)s", url], capture_output=True, text=True)
        subs = sorted(glob.glob(tmp + "/*.vtt"), key=lambda p: ("Hant" not in p and "TW" not in p, p))
        text = vtt_text(subs[0]) if subs else ""
        d = j.get("upload_date") or ""
        rec = {"title": j.get("title"), "date": "%s-%s-%s" % (d[:4], d[4:6], d[6:]), "url": url, "duration": j.get("duration"),
               "desc": j.get("description") or "", "chapters": [c.get("title") for c in j.get("chapters") or []], "subs": text}
        json.dump(rec, open(os.path.join(OUT, "%s_%s.json" % (rec["date"], vid)), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("存好：", rec["date"], rec["title"][:50], "字幕 %d 字" % len(text))
        n += 1
    print("新增 %d 集" % n)


if __name__ == "__main__":
    main()
