"""
tv_fetch.py - 抓財經節目（錢線百分百、理財達人秀、財經皓角）最近幾集的 YouTube 標題、簡介、自動字幕（給 Claude 讀，整理節目提到的選股策略再回測）

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
import time

OUT = sys.argv[1] if len(sys.argv) > 1 else "tv"
DAYS = int(sys.argv[2]) if len(sys.argv) > 2 else 3
# YouTube 登入資料（cookies.txt，存在 GitHub Secrets 的 YT_COOKIES）：有的話用備用帳號身分看影片，才抓得到字幕
CK = os.environ.get("YT_COOKIES_FILE") or ""
YT = ["yt-dlp", "--sleep-requests", "3", "--sleep-subtitles", "5"] + (["--cookies", CK] if CK and os.path.getsize(CK) > 100 else [])
# 追蹤的節目：（名稱、YouTube 搜尋字、標題一定要有的字）；搜尋結果依上傳日期排序，只留 20 分鐘以上的完整集數
SHOWS = [
    ("錢線百分百", "錢線百分百 完整版", "錢線百分百"),
    ("理財達人秀", "理財達人秀 李兆華", "理財達人秀"),   # 2026-11-24 使用者同意加
    ("財經皓角", "游庭皓的財經皓角", "財經皓角"),       # 2026-11-24 使用者同意加
    ("財經週末趴", "民視財經週末趴", "週末趴"),         # 2026-11-24 使用者要求加（週六 22:00，民視）
    ("財經週日趴", "財經週日趴", "週日趴"),
]


def search_url(q):
    import urllib.parse
    return "https://www.youtube.com/results?search_query=%s&sp=CAI%%253D" % urllib.parse.quote_plus(q)


def title_date(t):
    """標題裡的日期：20261123、2026/11/23、2026.11.23、2026-11-23"""
    m = re.search(r"(20\d{2})[./-]?(\d{1,2})[./-]?(\d{1,2})", t or "")
    if not m:
        return ""
    y, mo, d = m.groups()
    if not (1 <= int(mo) <= 12 and 1 <= int(d) <= 31):
        return ""
    return "%s%02d%02d" % (y, int(mo), int(d))


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


KEEP_DAYS = 3  # 字幕全文保留天數（例行分析每天讀一次，3 天後刪掉）
MAX_ASR = 5  # 每次最多語音辨識幾集（一集約 1 小時，辨識要 10～20 分鐘）
_MODEL = []


def transcribe(url, tmp):
    """下載聲音 → faster-whisper 轉文字 → 轉成繁體；失敗回傳空字串"""
    for f in glob.glob(tmp + "/a.*"):
        os.remove(f)
    r = subprocess.run(YT + ["-f", "bestaudio", "-x", "--audio-format", "mp3", "--audio-quality", "64K",
                             "-o", tmp + "/a.%(ext)s", url], capture_output=True, text=True)
    aud = glob.glob(tmp + "/a.mp3")
    if r.returncode or not aud:
        err = [x for x in r.stderr.splitlines() if "ERROR" in x]
        print("聲音下載失敗：", (err[-1] if err else r.stderr[-200:])[:200], flush=True)
        return ""
    try:
        from faster_whisper import WhisperModel
        if not _MODEL:
            _MODEL.append(WhisperModel("small", device="cpu", compute_type="int8"))
        t0 = time.time()
        segs, _ = _MODEL[0].transcribe(aud[0], language="zh", vad_filter=True, beam_size=1,
                                       initial_prompt="以下是台灣的股市財經節目，使用繁體中文。")
        text = "，".join(x.text.strip() for x in segs if x.text.strip())
        try:
            import opencc
            text = opencc.OpenCC("s2twp").convert(text)
        except Exception:
            pass
        print("語音辨識完成：%d 字、%.0f 秒" % (len(text), time.time() - t0), flush=True)
        os.remove(aud[0])  # 使用者要求：資料收集好就刪掉下載的檔案
        return text
    except Exception as ex:
        print("語音辨識失敗：", type(ex).__name__, str(ex)[:150], flush=True)
        return ""


def main():
    os.makedirs(OUT, exist_ok=True)
    keep = (dt.date.today() - dt.timedelta(days=KEEP_DAYS)).isoformat()
    done = set()
    for p in glob.glob(os.path.join(OUT, "*_*.json")):
        rec = json.load(open(p, encoding="utf-8"))
        if rec.get("subs") and (rec.get("date") or "9") < keep:
            # 使用者要求：資訊收集好（每天的例行分析已讀過）就刪掉下載的內容，只留標題、日期
            rec["subs"], rec["purged"] = "", True
            json.dump(rec, open(p, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        if rec.get("subs") or rec.get("purged"):
            done.add(os.path.basename(p).split("_", 1)[1][:-5])  # 沒字幕的下次再試
    since = (dt.date.today() - dt.timedelta(days=DAYS)).strftime("%Y%m%d")
    items = []
    for show, q, key in SHOWS:
        r = subprocess.run(YT + ["--flat-playlist", "--playlist-end", "25", "-J", search_url(q)], capture_output=True, text=True)
        if r.returncode:
            print("搜尋失敗：", show, r.stderr[-300:])
            continue
        got = [dict(e, show=show) for e in json.loads(r.stdout).get("entries") or []
               if len(e.get("id") or "") == 11 and key in (e.get("title") or "") and (e.get("duration") or 9999) >= 1200]  # 只要影片（頻道、播放清單也會出現在搜尋結果）
        print("%s：搜尋到 %d 支" % (show, len(got)))
        items += got
    if not items:
        print("沒有搜尋到任何節目（YouTube 搜尋頁可能暫時失敗），只做清除")
        return
    print("登入資料：", "有" if len(YT) > 3 else "沒有（只能抓標題）")
    blocked, asr_n = 0, 0
    tmp = "/tmp/tvsub"
    os.makedirs(tmp, exist_ok=True)
    n = 0
    for e in items:
        vid = e["id"]
        if vid in done:
            continue
        url = "https://www.youtube.com/watch?v=" + vid
        d = title_date(e.get("title"))
        if d and d < since:  # 標題就看得出太舊：不去問 YouTube（問太多次會被當機器人擋）
            continue
        time.sleep(4)
        rec = {"show": e["show"], "title": e.get("title"), "date": "%s-%s-%s" % (d[:4], d[4:6], d[6:]) if d else "", "url": url,
               "duration": e.get("duration"), "desc": e.get("description") or "", "chapters": [], "subs": ""}
        # 單支影片頁：YouTube 常擋 GitHub 的機器（要登入確認不是機器人），擋掉就只存搜尋頁的標題
        info = subprocess.run(YT + ["-J", "--skip-download", url], capture_output=True, text=True)
        if info.returncode:
            blocked += 1
            err = [x for x in info.stderr.splitlines() if "ERROR" in x]
            print("讀不到：", e["show"], vid, (err[-1] if err else info.stderr[-200:])[:200], flush=True)
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
            if not rec["subs"] and asr_n < MAX_ASR and rec["date"].replace("-", "") >= since:
                # 有些頻道（理財達人秀、週日趴）沒有字幕：下載聲音，用語音辨識（Whisper）轉成文字
                asr_n += 1
                rec["subs"] = transcribe(url, tmp)
                rec["asr"] = bool(rec["subs"])
        if not rec["date"] or rec["date"].replace("-", "") < since:
            continue
        json.dump(rec, open(os.path.join(OUT, "%s_%s.json" % (rec["date"], vid)), "w", encoding="utf-8"), ensure_ascii=False, indent=1)
        print("存好：", rec["date"], rec["title"][:50], "字幕 %d 字" % len(rec["subs"]))
        n += 1
    print("新增 %d 集；被 YouTube 擋 %d 次；語音辨識 %d 集" % (n, blocked, asr_n))
    if blocked and len(YT) > 3:
        print("⚠️ 有登入資料還是被擋：登入資料可能過期了，請重新匯出 cookies 存到 YT_COOKIES")


if __name__ == "__main__":
    main()
