// daily_report.js - 在背景執行「條件選股室」網頁，產生每日 SOP 報告（Discord 與 LINE 兩種格式）
// 用法：node daily_report.js data.json [sop_config.json]
// 產出：report_discord.txt、report_line.txt（與網頁上按「複製 Discord／LINE 格式」的內容相同）
// 需要：npm install（安裝 jsdom）
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');

const dir = __dirname;
const dataPath = process.argv[2] || path.join(dir, 'data.json');
const cfgPath = process.argv[3] || path.join(dir, 'sop_config.json');
// 網頁程式包在函式裡，外面拿不到變數；在 window.__recent 旁邊多插一個 window.__allHits（只在記憶體裡改，不改網頁檔）
// 用途：每個策略（含已刪除）過去每天選到哪些股票，算每檔推薦股的「真實紀錄」
const HOOK = "window.__allHits=()=>{const o={};for(const st of S.strategies){const act=st.conds.filter(c=>c.on!==false);if(!act.length)continue;" +
  "const need=st.mode==='all'?act.length:Math.min(Math.max(1,st.k),act.length);const days={};" +
  "for(let t=65;t<=LAST;t++){const ids=evalAt(t,act,need).filter(x=>x.hit).map(x=>x.s.id);if(ids.length)days[t]=ids}" +
  "o[st.id]={name:st.name,days}}return o};\n";
const html = fs.readFileSync(path.join(dir, 'stock-screener.html'), 'utf8').replace('window.__recent=', HOOK + 'window.__recent=');
const cfg = fs.existsSync(cfgPath) ? JSON.parse(fs.readFileSync(cfgPath, 'utf8')) : {};
let clip = '';

const dom = new JSDOM('<!doctype html><html><head></head><body>' + html + '</body></html>', {
  url: 'https://localhost/', runScripts: 'dangerously', pretendToBeVisual: true,
  beforeParse(w) {
    const ctx = new Proxy({}, { get: (t, k) => (k === 'measureText' ? () => ({ width: 40 }) : k in t ? t[k] : () => {}), set: (t, k, v) => { t[k] = v; return true; } });
    w.HTMLCanvasElement.prototype.getContext = () => ctx;
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.HTMLElement.prototype.scrollIntoView = () => {};
    Object.defineProperty(w.navigator, 'clipboard', { value: { writeText: async (t) => { clip = t; } } });
    if (cfg.state) w.localStorage.setItem('xgs.state.v1', JSON.stringify(cfg.state));
    w.onerror = (m) => console.error('頁面錯誤：', m);
  },
});
const w = dom.window, d = w.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));

(async () => {
  await wait(800);
  const f = new w.File([fs.readFileSync(dataPath, 'utf8')], 'data.json', { type: 'application/json' });
  const inp = d.querySelector('#fileIn');
  Object.defineProperty(inp, 'files', { value: [f], configurable: true });
  inp.dispatchEvent(new w.Event('change'));
  await wait(1500);
  const msg = d.querySelector('#dataMsg');
  if (!msg.className.includes('ok')) { console.error('匯入資料失敗：' + msg.textContent); process.exit(2); }
  for (const extra of ['macro.json']) {  // 國際新聞另外匯入
    const pth = path.join(dir, extra);
    if (!fs.existsSync(pth)) continue;
    const fx = new w.File([fs.readFileSync(pth, 'utf8')], extra, { type: 'application/json' });
    Object.defineProperty(inp, 'files', { value: [fx], configurable: true });
    inp.dispatchEvent(new w.Event('change'));
    await wait(400);
  }
  const bkPath = path.join(dir, 'broker.json');  // 有手動跑 broker_flow.py 就一起帶入（日期不同的會自動忽略）
  if (fs.existsSync(bkPath)) {
    const fb = new w.File([fs.readFileSync(bkPath, 'utf8')], 'broker.json', { type: 'application/json' });
    Object.defineProperty(inp, 'files', { value: [fb], configurable: true });
    inp.dispatchEvent(new w.Event('change'));
    await wait(500);
  }
  d.querySelector('#exOnly').checked = !!cfg.onlyBuy;
  // cfg.reports："all"＝跑全部策略、只留有結果的；或 [{strat:'s1'}, {strat:'s9', onlyIfHits:true}]；沒設定就用 SOP 目前選的策略
  // cfg.skip：已刪除、不要再跑的策略（代號或名稱）；網頁內建策略每次載入都會補回來，所以要在這裡排除
  const skip = new Set(cfg.skip || []);
  const reports = (cfg.reports === 'all'
    ? [...d.querySelector('#sopStrat').options].map((o) => ({ strat: o.value, name: o.textContent, onlyIfHits: true }))
    : cfg.reports || [{ strat: null }]).filter((r) => !skip.has(r.strat) && !skip.has(r.name));
  if (skip.size) console.log('不跑的策略：' + [...skip].join('、'));
  const out = {};
  const plan = { rows: {} };  // 隔天早上開盤檢查用：每檔的買進區間、不追價、停損（同一檔出現在多個策略就合併）
  for (const [id, name] of [['#exDc', 'report_discord.txt'], ['#exLine', 'report_line.txt']]) {
    const parts = [];
    let head = [], news = [];
    for (const r of reports) {
      if (r.strat) {
        const sel = d.querySelector('#sopStrat');
        if (![...sel.options].some((o) => o.value === r.strat)) { console.error('找不到策略：' + r.strat); continue; }
        sel.value = r.strat;
        sel.dispatchEvent(new w.Event('change'));
        await wait(300);
      }
      clip = '';
      d.querySelector(id).click();
      await wait(200);
      if (!clip) { console.error('產生報告失敗：' + name); process.exit(3); }
      const n = +((clip.match(/最後 (\d+) 檔/) || [])[1] || 0);
      if (r.onlyIfHits && !n) continue;  // 例如作帳期以外或沒有符合，就不放這一段
      const sop = w.__SOP;
      if (id === '#exDc' && sop) {
        Object.assign(plan, { date: sop.date, risk: sop.risk, rescue: sop.rescue || '', gapMax: sop.gapMax, gapNo: sop.gapNo, gapDown: sop.gapDown });
        for (const x of sop.rows) (plan.rows[x.id] = plan.rows[x.id] || { ...x, strategies: [] }).strategies.push(sop.strategy);
      }
      // 拆成：標題（策略行之前）、國際新聞、策略本體（去掉重複的新聞與免責聲明）
      const L = clip.split('\n'), si = L.findIndex((x) => x.startsWith('策略：'));
      if (!head.length) head = L.slice(0, si).filter((x) => x.trim());
      const body = [];
      for (let i = si, inNews = false; i < L.length; i++) {
        if (L[i].includes('國際風險新聞')) inNews = true;
        else if (inNews && !L[i].trim()) { inNews = false; continue; }
        if (inNews) { if (!news.length || news[news.length - 1] !== L[i]) news.push(L[i]); continue; }
        if (!L[i].includes('不是投資建議')) body.push(L[i]);
      }
      parts.push((r.title ? r.title + '\n' : '') + body.join('\n').trim());
    }
    news = [...new Set(news)];
    const text = parts.length
      ? [head.join('\n'), news.length ? news.join('\n') : '', parts.join('\n\n━━━━━━━━━━\n\n'), '依固定規則計算的參考價位，不是投資建議。'].filter(Boolean).join('\n\n')
      : '';  // 全部策略都沒結果：空檔，daily_run.py 會略過發送
    fs.writeFileSync(path.join(dir, name), text, 'utf8');
    out[name] = text.length;
  }
  // 模擬下單：sop_config.json 的 orders.list 加上網頁存的 state.orders（同一筆只算一次）
  const seen = new Set(), olist = [];
  for (const o of [...((cfg.orders && cfg.orders.list) || (Array.isArray(cfg.orders) ? cfg.orders : [])), ...((cfg.state && cfg.state.orders) || [])]) {
    const key = [o.id, o.side || 'b', o.px ?? o.price, o.q ?? o.qty, o.d ?? o.date].join('|').replace(/\|buy\|/, '|b|').replace(/\|sell\|/, '|s|');
    if (!seen.has(key)) { seen.add(key); olist.push(o); }
  }
  const disc = cfg.orders && cfg.orders.disc != null ? +cfg.orders.disc : undefined;
  fs.writeFileSync(path.join(dir, 'report_orders.txt'), olist.length ? w.__ordersText(olist, disc) : '', 'utf8');
  plan.rows = Object.values(plan.rows);
  // 多策略共振：近 5 個交易日內有 2 個以上策略選到同一檔（回測：任 2 個同時選到勝率約 60%～76%，比單一策略高）
  // 特別強的組合（回測勝率 76% 以上）標 ⭐⭐
  try {
    // 背景策略：已刪除、不單獨推薦，但和特定策略同時選到時特別準（回測），只拿來標 ⭐⭐
    const HIDDEN = { s3: 's20', s7: 's19', s5: 's21' };  // 量價突破＋CAN SLIM 85%、NEURAL NETWORK＋穩健動能 69%、三率三升土洋合作＋強勢回檔 67%
    const ids = [...d.querySelector('#sopStrat').options].map((o) => o.value).filter((x) => !skip.has(x) || HIDDEN[x]);
    const rec = w.__recent(ids, 5), nm2id = {};
    for (const [k, v] of Object.entries(rec)) nm2id[v.name] = k;
    const STRONG = [['s19', 's21'], ['s19', 's9'], ['s21', 's9'], ...Object.entries(HIDDEN)];
    // 回測同時選到反而變差的組合，不算共振（CAN SLIM＋追強勢 47%～50%、強勢回檔＋ETF 33%、林區＋三率三升 25%）
    const BAD = [['s20', 's19'], ['s20', 's21'], ['s21', 's15'], ['s13', 's11'], ['s15', 's9']];
    for (const r of plan.rows) {
      const got = new Set((r.strategies || []).map((n) => nm2id[n]).filter(Boolean));
      for (const [k, v] of Object.entries(rec)) if (v.ids.includes(r.id)) got.add(k);
      for (const [h, p] of Object.entries(HIDDEN)) if (got.has(h) && !got.has(p)) got.delete(h);  // 背景策略只在和它的搭檔一起選到時才算
      const ks = [...got].sort();
      r.res = ks.map((k) => rec[k].name + (HIDDEN[k] ? '（背景）' : ''));
      const good = ks.some((a, i) => ks.slice(i + 1).some((b) => !BAD.some(([x, y]) => (x === a && y === b) || (x === b && y === a))));
      r.star = !good ? 0 : STRONG.some(([a, b]) => got.has(a) && got.has(b)) || ks.length >= 3 ? 2 : 1;
    }
    // 背景搭配（2026-11-16 使用者同意，加勝率 60% 以上的；research/combo_bt.py，同一天兩邊都選到）：
    // 投信一直買＋股價在投信成本附近 ＋ 彼得林區 62%、＋ 穩健動能 64%；上升三角形突破 ＋ 穩健動能 64%（穩健動能單獨 36%）
    const DJ = JSON.parse(fs.readFileSync(dataPath, 'utf8')), byId = {};
    for (const s of DJ.stocks) byId[s.id] = s;
    const itCost = (s) => {  // 投信近 20 天買超 ≥12 天、近 60 天累計買超，股價在投信估計成本 −5%～+3%
      const it = s.it || [], c = s.c, T = c.length - 1;
      if (it.length <= T || T < 60) return false;
      if (it.slice(T - 19, T + 1).filter((x) => (x || 0) > 0).length < 12) return false;
      if (it.slice(T - 59, T + 1).reduce((a, x) => a + (x || 0), 0) <= 0) return false;
      let w = 0, v = 0;
      for (let k = T - 59; k <= T; k++) if ((it[k] || 0) > 0 && c[k]) { w += it[k]; v += it[k] * c[k]; }
      const g = w ? c[T] / (v / w) - 1 : NaN;
      return g >= -0.05 && g <= 0.03;
    };
    const ascTri = (s) => {  // 上升三角形：近 60 天兩個高點差 2% 內（水平壓力）、兩個低點墊高 2% 以上，今天收盤突破壓力
      const { h, l, c } = s, T = c.length - 1, K = 3;
      if (T < 70 || [h, l, c].some((a) => a.slice(T - 63).some((x) => !x))) return false;
      const H = [], L = [];
      for (let i = T - 60; i <= T - K; i++) {
        const wh = h.slice(i - K, i + K + 1), wl = l.slice(i - K, i + K + 1);
        if (h[i] === Math.max(...wh)) H.push(h[i]);
        if (l[i] === Math.min(...wl)) L.push(l[i]);
      }
      if (H.length < 2 || L.length < 2) return false;
      const [ha, hb] = H.slice(-2), [la, lb] = L.slice(-2), R = Math.max(ha, hb);
      return Math.abs(ha / hb - 1) <= 0.02 && lb >= la * 1.02 && c[T] > R * 1.005 && c[T - 1] <= R * 1.005;
    };
    const COMBO = [['s13', '投信成本附近', itCost, 62], ['s19', '投信成本附近', itCost, 64], ['s19', '上升三角形突破', ascTri, 64]];
    for (const r of plan.rows) {
      const s = byId[r.id], got = new Set((r.strategies || []).map((n) => nm2id[n]).filter(Boolean));
      if (!s) continue;
      for (const [k, nm, f, wr] of COMBO) {
        let ok = false;
        try { ok = got.has(k) && f(s); } catch (e) { ok = false; }
        if (!ok) continue;
        const tag = nm + '（背景，搭' + rec[k].name + '回測勝率 ' + wr + '%）';
        if (!r.res.includes(tag)) r.res.push(tag);
        r.star = 2;
      }
    }
    // 📜 真實紀錄（2026-11-21 使用者要的，取代「隨機模擬」）：這檔入選的策略過去每次選到股票時，
    // 用這檔一樣的停損／目標百分比（隔天開盤買、20 個交易日內），先到目標、先停損、都沒到各幾次；另列這檔自己的紀錄
    try {
      const ALL = w.__allHits ? w.__allHits() : {};
      const name2k = {};
      for (const [k, v] of Object.entries(ALL)) name2k[v.name] = k;
      const H = 20, n = DJ.dates.length;
      const outcome = (s, t, sp, tp) => {
        if (t + 1 + H >= n || !s.o[t + 1]) return null;
        const e = s.o[t + 1];
        for (let u = t + 1; u <= t + H; u++) {
          if (!s.l[u] || !s.h[u]) return null;
          if (s.l[u] <= e * sp) return 's';  // 同一天兩邊都碰到算停損（保守）
          if (s.h[u] >= e * tp) return 't';
        }
        return 'n';
      };
      for (const r of plan.rows) {
        if (!r.lo || !r.hi || !r.stop || !r.t1) continue;
        const e0 = (r.lo + r.hi) / 2, sp = r.stop / e0, tp = r.t1 / e0;
        const ks = [...new Set((r.strategies || []).map((nm) => name2k[nm]).filter(Boolean))];
        if (!ks.length) continue;
        const seen = new Set(), cnt = { t: 0, s: 0, n: 0 }, own = { t: 0, s: 0, n: 0 };
        for (const k of ks) {
          const last = {};
          for (const [tt, ids] of Object.entries(ALL[k].days)) {
            const t = +tt;
            for (const id of ids) {
              if (t - (last[id] ?? -99) <= 20) continue;
              last[id] = t;
              const key = id + '|' + t;
              if (seen.has(key)) continue;
              seen.add(key);
              const st = byId[id], o = st && outcome(st, t, sp, tp);
              if (!o) continue;
              cnt[o]++;
              if (id === r.id) own[o]++;
            }
          }
        }
        const N = cnt.t + cnt.s + cnt.n, M = own.t + own.s + own.n;
        if (N < 10) continue;
        const pc = (x, tot) => Math.round(100 * x / tot) + '%';
        r.record = { n: N, t: cnt.t, s: cnt.s, nn: cnt.n, own: own, sp: Math.round((sp - 1) * 1000) / 10, tp: Math.round((tp - 1) * 1000) / 10,
          text: '📜 真實紀錄：' + (r.strategies || []).join('、') + '過去 ' + N + ' 次（' + DJ.dates[65].slice(0, 7) + ' 起），照這檔停損 ' +
            (Math.round((sp - 1) * 1000) / 10) + '%／目標 +' + (Math.round((tp - 1) * 1000) / 10) + '%，20 天內先到目標 ' + pc(cnt.t, N) +
            '、先停損 ' + pc(cnt.s, N) + '、都沒到 ' + pc(cnt.n, N) + (M ? '；這檔自己 ' + M + ' 次：目標 ' + own.t + '、停損 ' + own.s + '、都沒到 ' + own.n : '；這檔自己還沒有紀錄') };
      }
      console.log('真實紀錄：' + plan.rows.filter((r) => r.record).length + ' 檔');
    } catch (e) { console.error('真實紀錄計算失敗，略過：', e.message); }
    console.log('背景搭配：' + plan.rows.filter((r) => (r.res || []).some((x) => x.includes('回測勝率'))).length + ' 檔');
    console.log('多策略共振：' + plan.rows.filter((r) => r.star).length + ' 檔（強共振 ' + plan.rows.filter((r) => r.star === 2).length + ' 檔）');
  } catch (e) { console.error('共振標記失敗，略過：', e.message); }
  fs.writeFileSync(path.join(dir, 'sop_plan.json'), JSON.stringify(plan, null, 1), 'utf8');
  console.log('已產生報告：' + JSON.stringify(out) + '，開盤檢查名單 ' + plan.rows.length + ' 檔，資料日 ' + d.querySelector('#sopDate').textContent);
  process.exit(0);
})();
