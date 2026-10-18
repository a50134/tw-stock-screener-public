"""
send_report.py - 把「條件選股室」複製的報告送到 Discord 和 LINE

用法：
  1. 在網頁的「每日 SOP」按「複製 Discord 格式」或「複製 LINE 格式」
  2. 執行  python send_report.py              # 讀剪貼簿
     或    python send_report.py report.txt   # 讀文字檔

設定（只設你要用的那個；token 不要貼到網頁或傳給別人）：
  DISCORD_WEBHOOK_URL  Discord 頻道 → 編輯頻道 → 整合 → Webhook → 新 Webhook → 複製 Webhook 網址
  LINE_CHANNEL_TOKEN   LINE Developers 後台 → 你的 Messaging API channel → Channel access token
                       （也可以叫 LINE_CHANNEL_ACCESS_TOKEN）
  LINE_TO              要推播的對象 userId（U 開頭）或群組 groupId（C 開頭）（也可以叫 LINE_USER_ID）
  LINE_BROADCAST=1     改成發給官方帳號的「所有好友」（家人加好友就收得到）；失敗時改推給 LINE_TO
  加 --push            這一則不群發，只推給 LINE_TO（持股等私人內容用）
  加 --extra 檔案      LINE 額外訊息（JSON：圖片、按鈕），和文字同一次發送
  加 --attach 檔案     Discord 附上檔案（可重複，例如 Word 完整版與分享版）；網址存到 discord_files.json

  可以設成環境變數，或寫在 .env 檔（一行一個 KEY=VALUE）。
  會自動讀：目前資料夾的 .env，或桌面 Claude-project/stock-analysis-lab/.env；
  也可以用 --env 指定：python send_report.py --env D:/路徑/.env
  python send_report.py --check  只檢查設定，不發送
  加 --discord-only 或 --line-only 只發其中一邊；--images-only：LINE 有圖片時不發文字（只發圖＋按鈕）

LINE Notify 已在 2025/3/31 停止服務，所以 LINE 要用官方帳號的 Messaging API，
免費方案每月推播則數有上限。
"""
import os
import sys

import requests

try:  # 讓 requests 使用 Windows／系統憑證庫（有些防毒或公司網路會造成 certifi 憑證驗證失敗）
    import truststore
    truststore.inject_into_ssl()
except ImportError:
    pass


def load_env():
    """讀 .env 檔（KEY=VALUE），不覆蓋已經設定的環境變數。
    會依序讀：--env 指定的檔案、目前資料夾的 .env、桌面 Claude-project/stock-analysis-lab/.env、
    桌面 hex-skill-lab-main/skills/12-stock-analyst/automation/.env（前面讀到的優先）"""
    paths = []
    if "--env" in sys.argv:
        i = sys.argv.index("--env")
        if i + 1 < len(sys.argv):
            paths.append(sys.argv[i + 1])
            del sys.argv[i:i + 2]
    desk = os.path.join(os.path.expanduser("~"), "Desktop")
    paths += [".env", os.path.join(desk, "Claude-project", "stock-analysis-lab", ".env"),
              os.path.join(desk, "hex-skill-lab-main", "skills", "12-stock-analyst", "automation", ".env")]
    found = []
    for p in paths:
        if os.path.isfile(p):
            with open(p, encoding="utf-8-sig") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#") or "=" not in line:
                        continue
                    k, v = line.split("=", 1)
                    k, v = k.strip().removeprefix("export ").strip(), v.strip().strip("\"'")
                    os.environ.setdefault(k, v)
                    os.environ.setdefault(k.upper(), v)
            found.append(os.path.abspath(p))
    return "、".join(dict.fromkeys(found)) or None


def read_text():
    skip = {i + 1 for i, a in enumerate(sys.argv) if a in ("--attach", "--extra")}
    args = [a for i, a in enumerate(sys.argv[1:], 1) if not a.startswith("-") and i not in skip]
    if args:
        with open(args[0], encoding="utf-8") as f:
            return f.read()
    import tkinter
    root = tkinter.Tk()
    root.withdraw()
    try:
        text = root.clipboard_get()
    finally:
        root.destroy()
    return text


def chunks(text, size):
    """依行切段，每段不超過 size 個字（Discord 單則 2000 字、LINE 單則 5000 字）。"""
    out, cur = [], ""
    for line in text.splitlines(keepends=True):
        while len(line) > size:
            if cur:
                out.append(cur)
                cur = ""
            out.append(line[:size])
            line = line[size:]
        if len(cur) + len(line) > size:
            out.append(cur)
            cur = ""
        cur += line
    if cur.strip():
        out.append(cur)
    return out


def send_discord(url, text, attach=None):
    """attach：附檔路徑清單（Word 完整版等），附在最後一則訊息。
    回傳 {檔名: 下載網址}（Discord 的檔案網址，約 24 小時內有效，給 LINE 放連結用）"""
    attach = [a for a in (attach or []) if os.path.exists(a)]
    parts = chunks(text, 1900)
    links = {}
    for i, part in enumerate(parts):
        if attach and i == len(parts) - 1:
            files, fs = {}, []
            for k, a in enumerate(attach):
                name = os.path.basename(a)
                mime = {".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document", ".png": "image/png",
                        ".jpg": "image/jpeg", ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"}.get(os.path.splitext(name)[1].lower())
                f = open(a, "rb")
                fs.append(f)
                files["files[%d]" % k] = (name, f, mime) if mime else ("完整報告.txt", f, "text/plain")
            try:
                r = requests.post(url + ("&" if "?" in url else "?") + "wait=true", data={"content": part}, files=files, timeout=90)
            finally:
                for f in fs:
                    f.close()
            if r.status_code < 300:
                try:  # Discord 會改檔名（中文字可能被拿掉），所以依上傳順序對回原本的檔名
                    att = r.json().get("attachments", [])
                    links = {x["filename"]: x["url"] for x in att}
                    if len(att) == len(attach):
                        links.update({os.path.basename(a): x["url"] for a, x in zip(attach, att)})
                except Exception:
                    links = {}
        else:
            r = requests.post(url, json={"content": part}, timeout=20)
        if r.status_code >= 300:
            raise RuntimeError("Discord 回應 %s：%s" % (r.status_code, r.text[:200]))
    return links


def send_line(token, to, text, broadcast=False, extra=None):
    """broadcast=True：發給官方帳號所有好友（家人加好友就收得到）；否則只推給 to 這一個人／群組。
    一次請求最多 5 個訊息泡泡，LINE 算 1 則 × 收到的人數（免費方案每月有則數上限）"""
    parts = chunks(text, 4900) if text.strip() else []
    msgs = [{"type": "text", "text": p} for p in parts] + list(extra or [])  # extra：圖片、按鈕等（同一次發送最多 5 則）
    url = "https://api.line.me/v2/bot/message/" + ("broadcast" if broadcast else "push")
    for i in range(0, len(msgs), 5):  # 一次最多 5 則（一次請求只算 1 則額度）
        body = {"messages": msgs[i:i + 5]}
        if not broadcast:
            body["to"] = to
        r = requests.post(url, headers={"Authorization": "Bearer " + token}, json=body, timeout=20)
        if r.status_code >= 300:
            raise RuntimeError("LINE 回應 %s：%s" % (r.status_code, r.text[:200]))


def main():
    src = load_env()
    # 去掉前後空白與換行（貼上金鑰時常會多帶一個換行，LINE 會拒絕）
    hook = os.environ.get("DISCORD_WEBHOOK_URL", "").strip()
    token = (os.environ.get("LINE_CHANNEL_TOKEN") or os.environ.get("LINE_CHANNEL_ACCESS_TOKEN", "")).strip()
    to = (os.environ.get("LINE_TO") or os.environ.get("LINE_USER_ID", "")).strip()
    bc = os.environ.get("LINE_BROADCAST", "").strip().lower() in ("1", "true", "yes", "all")  # 發給所有好友
    if "--push" in sys.argv:  # 私人內容（持股）：不群發，只推給 LINE_TO
        bc = False
    if "--check" in sys.argv:
        print("設定來源：", src or "只有環境變數")
        print("Discord：", "已設定" if hook.startswith("https://") else "未設定")
        print("LINE：", "未設定（需要 LINE_CHANNEL_TOKEN）" if not token else "發給所有好友（broadcast）" if bc else "已設定（只發給 LINE_TO）" if to else "未設定（需要 LINE_TO，或設 LINE_BROADCAST=1 發給所有好友）")
        if token:  # 只查詢、不發送：本月額度、已用則數、好友人數
            import datetime as dt
            H = {"Authorization": "Bearer " + token}
            def q(path):
                try:
                    r = requests.get("https://api.line.me/v2/bot/" + path, headers=H, timeout=20)
                    return r.json() if r.status_code < 300 else {"錯誤": "%s %s" % (r.status_code, r.text[:120])}
                except Exception as e:
                    return {"錯誤": str(e)}
            print("LINE 本月額度：", q("message/quota"))
            print("LINE 本月已用：", q("message/quota/consumption"))
            day = (dt.date.today() - dt.timedelta(days=1)).strftime("%Y%m%d")
            print("LINE 好友人數（%s）：" % day, q("insight/followers?date=" + day))
        return
    text = read_text().strip()
    if not text:
        sys.exit("剪貼簿是空的：請先在網頁按「複製 Discord 格式」或「複製 LINE 格式」。")
    if not hook and not (token and (to or bc)):
        sys.exit("還沒設定 DISCORD_WEBHOOK_URL，或 LINE_CHANNEL_TOKEN 加 LINE_TO，請看檔案開頭的說明。")
    if "--line-only" in sys.argv:
        hook = ""
    if "--discord-only" in sys.argv:
        token = to = ""
        bc = False
    sent = False
    if hook:
        try:
            att = [sys.argv[i + 1] for i, a in enumerate(sys.argv) if a == "--attach" and i + 1 < len(sys.argv)]
            links = send_discord(hook, text, att)
            if links:  # 存下附檔網址，daily_run 會放進 LINE 訊息
                import json
                with open("discord_files.json", "w", encoding="utf-8") as f:
                    json.dump(links, f, ensure_ascii=False)
            print("已送到 Discord")
            sent = True
        except Exception as e:
            print("Discord 失敗：", e, file=sys.stderr)
    if token and (to or bc):
        try:
            extra = []
            if "--extra" in sys.argv:  # LINE 額外訊息（總表圖片、打開 Word 的按鈕），JSON 檔
                import json
                try:
                    extra = json.load(open(sys.argv[sys.argv.index("--extra") + 1], encoding="utf-8"))
                except Exception as e:
                    print("額外訊息讀取失敗，只發文字：", e, file=sys.stderr)
            if "--images-only" in sys.argv and any(m.get("type") == "image" for m in extra):
                text = ""  # 只發圖片＋按鈕（圖片產生失敗時才照常發文字）
            send_line(token, to, text, bc, extra)
            print("已送到 LINE" + ("（所有好友）" if bc else ""))
            sent = True
        except Exception as e:
            print("LINE 失敗：", e, file=sys.stderr)
            if bc and to:  # 群發失敗（例如本月則數用完）至少推給自己
                try:
                    send_line(token, to, text, False, extra)
                    print("已改送到 LINE_TO")
                    sent = True
                except Exception as e2:
                    print("LINE 推播也失敗：", e2, file=sys.stderr)
    if not sent:
        sys.exit(1)


if __name__ == "__main__":
    main()
