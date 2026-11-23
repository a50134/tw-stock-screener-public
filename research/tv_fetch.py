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
# YouTube 登入資料（cookies.txt，存在 GitHub Secrets 的 YT_COOKIES）：有的話用備用帳號身分看影片，才抓得到字幕
CK = os.environ.get("YT_COOKIES_FILE") or ""
YT = ["yt-dlp", "--sleep-requests", "1"] + (["--cookies", CK] if CK and os.path.getsize(CK) > 100 else [])
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
    r = subprocess.run(YT + ["--flat-playlist", "--playlist-end", "25", "-J", QUERY], capture_output=True, text=True)
    if r.returncode:
        print("搜尋失敗：", r.stderr[-500:])
        sys.exit(1)
    items = [e for e in json.loads(r.stdout).get("entries") or [] if "錢線百分百" in (e.get("title") or "")]
    print("搜尋到 %d 支" % len(items))
    done = {os.path.basename(p).split("_", 1)[1][:-5] for p in glob.glob(os.path.join(OUT, "*_*.json"))
            if json.load(open(p, encoding="utf-8")).get("subs")}  # 沒字幕的下次再試
    print("登入資料：", "有" if len(YT) > 3 else "沒有（只能抓標題）")
    blocked = 0
    tmp = "/tmp/tvsub"
    os.makedirs(tmp, exist_ok=True)
    n = 0
    for e in items:
        vid = e["id"]
        if vid in done:
            continue
        url = "https://www.youtube.com/watch?v=" + vid
        m = re.search(r"(20\d{6})", e.get("title") or "")
        d = m.group(1) if m else ""
        rec = {"title": e.get("title"), "date": "%s-%s-%s" % (d[:4], d[4:6], d[6:]) if d else "", "url": url,
               "duration": e.get("duration"), "desc": e.get("description") or "", "chapters": [], "subs": ""}
        # 單支影片頁：YouTube 常擋 GitHub 的機器（要登入確認不是機器人），擋掉就只存搜尋頁的標題
        info = subprocess.run(YT + ["-J", "--skip-download", url], capture_output=True, text=True)
        if info.returncode:
            blocked += 1
        else:
            j = json.loads(info.stdout)
            u = j.get("upload_date") or d
            rec.update(date="%s-%s-%s" % (u[:4], u[4:6], u[6:]), desc=j.get("description") or rec["desc"],
                       chapters=[c.get("title") for c in j.get("chapters") or []])
            for f in glob.glob(tmp + "/*"):
                os.remove(f)
            subprocess.run(YT + ["--skip-download", "--write-subs", "--write-auto-subs", "--sub-langs", "zh-Hant,zh-TW,zh-Hans,zh.*",
                            "--sub-format", "vtt", "-o", tmp + "/%(id)s.%(ext)s", url], capture_output=True, text=True)
            subs = sorted(glob.glob(tmp + "/*.vtt"), key=lambda p: ("Hant" not in p and "TW" not in p, p))
            rec["subs"] = vtt_text(subs[0]) if subs else ""
        if not rec["date"] or rec["date"].replace("-", "") < since:
            continue
        json.dump(rec, open(os.path.join(OUT, "%s_%s.json" % (rec["date"], vid)), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("存好：", rec["date"], rec["title"][:50], "字幕 %d 字" % len(rec["subs"]))
        n += 1
    print("新增 %d 集；被 YouTube 擋 %d 次" % (n, blocked))
    if blocked and len(YT) > 3:
        print("⚠️ 有登入資料還是被擋：登入資料可能過期了，請重新匯出 cookies 存到 YT_COOKIES")


if __name__ == "__main__":
    main()
