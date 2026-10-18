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
const html = fs.readFileSync(path.join(dir, 'stock-screener.html'), 'utf8');
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
        Object.assign(plan, { date: sop.date, risk: sop.risk, gapMax: sop.gapMax, gapNo: sop.gapNo, gapDown: sop.gapDown });
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
  fs.writeFileSync(path.join(dir, 'sop_plan.json'), JSON.stringify(plan, null, 1), 'utf8');
  console.log('已產生報告：' + JSON.stringify(out) + '，開盤檢查名單 ' + plan.rows.length + ' 檔，資料日 ' + d.querySelector('#sopDate').textContent);
  process.exit(0);
})();
