"""第 3 項：大盤跌破季線時，追強勢股（多頭排列、在月線上 8% 內）到底好不好？大跌後 30 天內（暫時性大跌）vs 其他時候；權值股 vs 其他"""
import json,sys,statistics as st
sys.path.insert(0,'/home/user/tw-stock-screener-public')
import crash
exec(open(__file__.replace('weak_bt','stop_bt')).read().split("print('進場筆數'")[0].split("entries=[]")[0])
d=json.load(open(sys.argv[1]));D=d['dates'];S=d['stocks'];n=len(D)
m=next(x['c'] for x in S if x['id']=='0050')
ev=crash.events(D,m)
def post(t): return any(0<=t-e<=30 for e in ev)
rank={}
def isbig(s,t):
    if t not in rank:
        L=sorted(((float(x['shares'])*x['c'][t],x['id']) for x in S if not x['id'].startswith('00') and x.get('shares') and x['c'][t]),reverse=True)
        rank[t]={i for _,i in L[:50]}
    return s['id'] in rank[t]
R={}
for s in S:
    if s['id'].startswith('00'): continue
    c,o,h,l,v=s['c'],s['o'],s['h'],s['l'],s['v'];last=-99
    for t in range(70,n-2):
        if t-last<10 or not all(c[t-65:t+1]) or not all(h[t-15:t+2]) or not all(l[t-15:t+2]) or not o[t+1]: continue
        if sum(v[t-20:t])/20<500: continue
        m5,m20,m20p,m60=ma(c,5,t),ma(c,20,t),ma(c,20,t-1),ma(c,60,t)
        if not(m5>m20>m60 and m20>m20p): continue
        C=c[t];bias=(C/m20-1)*100
        if C<m20 or bias>8: continue
        A=atr(s,t);hi=C+0.3*A
        if l[t+1]>hi: continue
        px=min(o[t+1],hi);last=t
        weak=m[t]<ma(m,60,t)
        key=('大盤強（0050 在季線上）' if not weak else ('大盤弱＋大跌後 30 天內' if post(t) else '大盤弱（其他時候）'))+('｜權值股' if isbig(s,t) else '｜一般股')
        for H in (20,60):
            e=t+1+H
            if e>=n or not c[e]: continue
            cc=c[t:e+1]
            if any(cc[i] and cc[i-1] and abs(cc[i]/cc[i-1]-1)>0.11 for i in range(1,len(cc))): continue
            stop=px*0.92;out=None
            for u in range(t+2,e+1):
                if l[u] and l[u]<=stop: out=min(o[u] or stop,stop);break
            R.setdefault((key,H),[]).append((out or c[e])/px-1-0.006)
for (k,H),v in sorted(R.items(),key=lambda x:(x[0][1],x[0][0])):
    print('抱 %d 天｜%-24s %4d 筆｜勝率 %3.0f%%｜平均 %+5.1f%%｜最差 %+4.0f%%'%(H,k,len(v),100*sum(x>0 for x in v)/len(v),100*st.mean(v),100*min(v)))
print('大跌事件：',[D[e] for e in ev])
