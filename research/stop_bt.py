"""停損幅度回測：用網頁版同樣的買進區（state=ok：收盤在月線上、離月線不到 8%），多頭排列的股票，下一天在區間內買到"""
import json,sys,statistics as st
sys.path.insert(0,'/home/user/tw-stock-screener-public')
import crash
d=json.load(open(sys.argv[1]));D=d['dates'];S=d['stocks'];n=len(D)
def atr(s,t,k=14):
    tr=[max(s['h'][i]-s['l'][i],abs(s['h'][i]-s['c'][i-1]),abs(s['l'][i]-s['c'][i-1])) for i in range(t-k+1,t+1)]
    return sum(tr)/k
def ma(c,k,t): return sum(c[t-k+1:t+1])/k
m0050=next(x['c'] for x in S if x['id']=='0050')
entries=[]
for s in S:
    if s['id'].startswith('00'): continue
    c,o,h,l,v=s['c'],s['o'],s['h'],s['l'],s['v']
    last=-99
    for t in range(70,n-2):
        if t-last<10 or not all(c[t-65:t+1]) or not all(h[t-15:t+2]) or not all(l[t-15:t+2]) or not o[t+1]: continue
        if sum(v[t-20:t])/20<500: continue
        m5,m20,m20p,m60=ma(c,5,t),ma(c,20,t),ma(c,20,t-1),ma(c,60,t)
        if not(m5>m20>m60 and m20>m20p): continue
        C=c[t];bias=(C/m20-1)*100
        if C<m20 or bias>8: continue
        A=atr(s,t);lo=max(m20,C-1.5*A);hi=C+0.3*A
        if l[t+1]>hi: continue
        px=min(o[t+1],hi)
        entries.append((s,t,px,lo,A,m0050[t]<ma(m0050,60,t)))
        last=t
print('進場筆數',len(entries))
def run(rule,H):
    R=[];stopped=0
    for s,t,px,lo,A,weak in entries:
        e=t+1+H
        if e>=n or not s['c'][e]: continue
        cc=s['c'][t:e+1]
        if any(cc[i] and cc[i-1] and abs(cc[i]/cc[i-1]-1)>0.11 for i in range(1,len(cc))): continue  # 分割、減資造成的假漲跌（台股一天最多 ±10%）
        stop=rule(px,lo,A)
        out=None
        for u in range(t+2,e+1):
            if stop and s['l'][u] and s['l'][u]<=stop:
                out=min(s['o'][u] or stop,stop);stopped+=1;break
        if out is None: out=s['c'][e]
        R.append((out/px-1-0.006,weak))
    return R,stopped
rules=[("現在：區間下緣 − 1 倍 ATR",lambda p,lo,A:lo-A),("下緣 − 1.5 倍 ATR",lambda p,lo,A:lo-1.5*A),("下緣 − 2 倍 ATR",lambda p,lo,A:lo-2*A),
       ("買價 −5%",lambda p,lo,A:p*0.95),("買價 −8%",lambda p,lo,A:p*0.92),("買價 −10%",lambda p,lo,A:p*0.90),("買價 −12%",lambda p,lo,A:p*0.88),("不停損",lambda p,lo,A:None)]
dist=[(p-(lo-A))/p*100 for s,t,p,lo,A,w in entries]
print('現在的停損離買價平均 %.1f%%（中位數 %.1f%%，10%%～90%%：%.1f%%～%.1f%%）'%(st.mean(dist),st.median(dist),sorted(dist)[len(dist)//10],sorted(dist)[len(dist)*9//10]))
for H in (20,60):
    print('\n抱 %d 天（停損觸發就出場）'%H)
    for nm,f in rules:
        R,k=run(f,H);v=[x for x,_ in R]
        if not v: continue
        wk=[x for x,w in R if w];sg=[x for x,w in R if not w]
        v2=sorted(v);los=[x for x in v if x<0]
        print('・%-14s %4d 筆｜勝率 %3.0f%%｜平均 %+5.1f%%｜賠錢的平均 %+5.1f%%｜最差 5%% %+4.0f%%｜最差 %+4.0f%%｜被停損 %3.0f%%｜大盤弱時 %+5.1f%%（%d 筆）｜大盤強時 %+5.1f%%'%(
            nm,len(v),100*sum(x>0 for x in v)/len(v),100*st.mean(v),100*st.mean(los),100*v2[len(v2)//20],100*min(v),100*k/len(v),100*st.mean(wk) if wk else 0,len(wk),100*st.mean(sg) if sg else 0))
