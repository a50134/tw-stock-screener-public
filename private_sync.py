"""
private_sync.py - 私人資料（持股、買賣紀錄、自選觀察、持股賣出計畫、復盤教訓）放在私人專案，不放公開專案

公開專案的 sop_config.json 不含 orders 與 state.watch；排程執行時：
  python private_sync.py pull priv   # 從私人專案（checkout 在 priv/）把私人資料併進來（只在執行環境，不會存回公開專案）
  python private_sync.py push priv   # 把當晚更新的 sell_plan.json、lessons.json 存回私人專案資料夾（之後由排程 commit）
"""
import json
import os
import shutil
import sys

DIR = os.path.dirname(os.path.abspath(__file__))
FILES = ["sell_plan.json", "lessons.json"]  # 每晚會更新、要存回私人專案的檔案


def pull(priv):
    p = os.path.join(priv, "sop_config.json")
    cfg_path = os.path.join(DIR, "sop_config.json")
    cfg = json.load(open(cfg_path, encoding="utf-8"))
    if os.path.exists(p):
        pc = json.load(open(p, encoding="utf-8"))
        if pc.get("orders") is not None:
            cfg["orders"] = pc["orders"]
        if (pc.get("state") or {}).get("watch") is not None:
            cfg.setdefault("state", {})["watch"] = pc["state"]["watch"]
        json.dump(cfg, open(cfg_path, "w", encoding="utf-8"), ensure_ascii=False, indent=1)
    for f in FILES:
        if os.path.exists(os.path.join(priv, f)):
            shutil.copy(os.path.join(priv, f), os.path.join(DIR, f))
    o = cfg.get("orders") or {}
    n = len((o.get("list") if isinstance(o, dict) else o) or [])
    print("私人資料已載入：買賣紀錄 %d 筆、自選觀察 %d 檔" % (n, len((cfg.get("state") or {}).get("watch") or [])))


def push(priv):
    for f in FILES:
        if os.path.exists(os.path.join(DIR, f)):
            shutil.copy(os.path.join(DIR, f), os.path.join(priv, f))
    print("私人資料已存回私人專案資料夾")


if __name__ == "__main__":
    {"pull": pull, "push": push}[sys.argv[1]](sys.argv[2] if len(sys.argv) > 2 else os.path.join(DIR, "priv"))
