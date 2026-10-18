"""
build_site.py - 把條件選股室打包成可以放上網、加到手機主畫面的網站（PWA）

用法：
  python build_site.py          # 產生 site/ 資料夾
  python build_site.py out_dir  # 指定輸出資料夾

site/ 內容：
  index.html            條件選股室（加上手機 App 需要的設定）
  data.json 等          有就一起放進去，打開網頁會自動載入最新真實資料
  manifest/sw/圖示      讓手機可以「加入主畫面」，像 App 一樣全螢幕開啟，沒網路也能看上次的資料
本機預覽：cd site && python -m http.server 8000，再用瀏覽器開 http://localhost:8000
"""
import os
import shutil
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
OUT = os.path.abspath(sys.argv[1]) if len(sys.argv) > 1 else os.path.join(DIR, "site")
DATA_FILES = ["data.json", "macro.json", "broker.json"]

HEAD = """<!doctype html>
<html lang="zh-Hant-TW">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1,viewport-fit=cover">
<meta name="theme-color" content="#0D6C7B">
<meta name="apple-mobile-web-app-capable" content="yes">
<meta name="mobile-web-app-capable" content="yes">
<meta name="apple-mobile-web-app-status-bar-style" content="default">
<meta name="apple-mobile-web-app-title" content="選股室">
<link rel="manifest" href="manifest.webmanifest">
<link rel="icon" type="image/png" sizes="192x192" href="icon-192.png">
<link rel="apple-touch-icon" href="apple-touch-icon.png">
"""

TAIL = """
<script>
/* 網站版：註冊離線快取；匯入的 macro.json / broker.json 也一起自動載入 */
if ('serviceWorker' in navigator) addEventListener('load', () => navigator.serviceWorker.register('sw.js').catch(() => {}));
['macro.json', 'broker.json'].forEach(f => fetch(f, {cache: 'no-cache'}).then(r => r.ok ? r.blob() : null).then(b => {
  if (!b) return;
  const inp = document.getElementById('fileIn'), dt = new DataTransfer();
  dt.items.add(new File([b], f, {type: 'application/json'}));
  inp.files = dt.files; inp.dispatchEvent(new Event('change'));
}).catch(() => {}));
</script>
</html>
"""


def main():
    src = open(os.path.join(DIR, "stock-screener.html"), encoding="utf-8").read()
    # 原檔從 <title> 開始（可直接用瀏覽器打開）；網站版補上完整的 head
    head_end = src.index("</style>") + len("</style>")
    html = HEAD + src[:head_end] + "\n</head>\n<body>\n" + src[head_end:] + "\n</body>" + TAIL
    if os.path.isdir(OUT):
        shutil.rmtree(OUT)
    os.makedirs(OUT)
    with open(os.path.join(OUT, "index.html"), "w", encoding="utf-8") as f:
        f.write(html)
    for name in os.listdir(os.path.join(DIR, "web")):
        shutil.copy(os.path.join(DIR, "web", name), OUT)
    found = []
    for name in DATA_FILES:
        p = os.path.join(DIR, name)
        if os.path.exists(p):
            shutil.copy(p, OUT)
            found.append(name)
    # 讓 GitHub Pages 不要用 Jekyll 處理
    open(os.path.join(OUT, ".nojekyll"), "w").close()
    print("網站已產生：%s（資料：%s）" % (OUT, "、".join(found) or "無，會顯示示範資料"))


if __name__ == "__main__":
    main()
