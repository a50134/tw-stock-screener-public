"""
quote.py - 查即時／收盤價（證交所基本市況報導，上市上櫃都可）
用法：python quote.py 2330 2603
"""
import datetime as dt
import sys

from morning_check import quotes  # 共用證交所報價（上市、上櫃都查）


def main():
    ids = [x for x in sys.argv[1:] if not x.startswith("-")] or ["2330"]
    q = quotes(ids)
    print("報價時間：", dt.datetime.now().strftime("%Y-%m-%d %H:%M"))
    for sid in ids:
        o, z, y = q.get(sid, (None, None, None))
        if z is None and o is None:
            print("%s：沒有報價" % sid)
            continue
        if z is None:  # 13:25～13:30 收盤集合競價期間沒有最新成交價
            print("%s　開 %s　最新：還沒有（收盤集合競價中，13:31 後再查）　昨收 %s" % (sid, o, y))
            continue
        print("%s　開 %s　最新 %s　昨收 %s　漲跌 %+.2f（%+.2f%%）" % (sid, o, z, y, z - y, (z / y - 1) * 100) if y else "%s　開 %s　最新 %s" % (sid, o, z))


if __name__ == "__main__":
    main()
