"""
fx.py - 台幣由貶轉升提醒（2026-11-13 使用者同意加入每晚報告）

訊號 A1：美元兌台幣（Yahoo TWD=X）近 60 個交易日內創新高（台幣最弱）後 20 天內，
         從高點回落 1.5% 以上，而且收盤由上往下跌破 20 日線（同一次訊號 20 天內只算一次）。
回測（research/twd_wd_bt.py，2006～2026，20 次）：之後加權指數 60 天平均 +5.0%、120 天平均 +11.4%、120 天後下跌只有 10%；
         任何一天買是 60 天 +3.3%、120 天 +6.8%、下跌 28%。只當大盤提醒，不單獨當買進理由。
"""
import sys


def signals(f):
    """回傳出現 A1 訊號的位置（索引）"""
    out, last = [], -99
    ma = lambda t: sum(f[t - 19:t + 1]) / 20
    for t in range(61, len(f)):
        hi_t = max(range(t - 59, t + 1), key=lambda k: f[k])
        if t - hi_t <= 20 and f[t] <= f[hi_t] * 0.985 and f[t] < ma(t) and f[t - 1] >= ma(t - 1) * 0.999 and t - last > 20:
            out.append(t)
            last = t
    return out


def clean(rows):
    f = [r["close"] for r in rows]
    for i in range(1, len(f)):  # Yahoo 匯率偶爾有錯價：單日跳 3% 以上當作前一天
        if abs(f[i] / f[i - 1] - 1) > 0.03:
            f[i] = f[i - 1]
    return [r["date"] for r in rows], f


def line(rows=None):
    """每晚報告一行（可發 LINE，大盤資訊）。抓不到資料回 None"""
    if rows is None:
        try:
            import us
            rows = us.yahoo("TWD=X", years=1)[0]
        except Exception as e:
            print("  ! 匯率抓不到：", e, file=sys.stderr)
            return None
    if len(rows) < 80:
        return None
    D, f = clean(rows)
    n = len(f)
    S = signals(f)
    ma20 = sum(f[-20:]) / 20
    hi_t = max(range(n - 60, n), key=lambda k: f[k])
    note = "（過去 20 次：之後 120 天大盤平均 +11%、9 成上漲；只是大盤提醒，個股照買點）"
    if S and n - 1 - S[-1] <= 20:  # 訊號出現後 20 個交易日內都提醒
        t = S[-1]
        return "💱 台幣由貶轉升訊號 %s 出現：美元兌台幣從 %.2f 回到 %.2f、跌破 20 日線，外資資金可能回流；現在 %.2f%s" % (
            D[t][5:].replace("-", "/"), max(f[t - 59:t + 1]), f[t], f[-1], note)
    need = min(f[hi_t] * 0.985, ma20)
    if n - 1 - hi_t <= 20 and f[-1] < ma20:
        return "💱 台幣：美元兌台幣 %.2f 已跌破 20 日線 %.2f，但跌破那天離近 60 天高點 %.2f 不到 1.5%%，這次不算台幣轉升訊號" % (f[-1], ma20, f[hi_t])
    if n - 1 - hi_t <= 20 and f[-1] > need:
        return "💱 台幣：美元兌台幣 %.2f（近 60 天最高 %.2f，%s），要回到 %.2f 以下（跌破 20 日線 %.2f）才算台幣轉升訊號%s" % (
            f[-1], f[hi_t], D[hi_t][5:].replace("-", "/"), need, ma20, note)
    return "💱 台幣：美元兌台幣 %.2f（20 日線 %.2f），目前沒有台幣轉升訊號" % (f[-1], ma20)


if __name__ == "__main__":
    print(line())
