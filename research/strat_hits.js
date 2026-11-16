// strat_hits.js - 在背景執行網頁，算出「每個策略（含已刪除）每天選到哪些股票」，給搭配回測用
// 用法：node research/strat_hits.js data.json out.json
const fs = require('fs');
const path = require('path');
const { JSDOM } = require('jsdom');
// 網頁程式包在函式裡，外面拿不到變數；在 window.__recent 旁邊多插一個 window.__allHits（只在這支程式的記憶體裡改，不改網頁檔）
const HOOK = "window.__allHits=()=>{const o={};for(const st of S.strategies){const act=st.conds.filter(c=>c.on!==false);if(!act.length)continue;" +
  "const need=st.mode==='all'?act.length:Math.min(Math.max(1,st.k),act.length);const days={};" +
  "for(let t=65;t<=LAST;t++){const ids=evalAt(t,act,need).filter(x=>x.hit).map(x=>x.s.id);if(ids.length)days[D[t]]=ids}" +
  "o[st.id]={name:st.name,days}}return JSON.stringify(o)};\n";
const html = fs.readFileSync(path.join(__dirname, '..', 'stock-screener.html'), 'utf8').replace('window.__recent=', HOOK + 'window.__recent=');
const dom = new JSDOM('<!doctype html><html><head></head><body>' + html + '</body></html>', {
  url: 'https://localhost/', runScripts: 'dangerously', pretendToBeVisual: true,
  beforeParse(w) {
    const ctx = new Proxy({}, { get: (t, k) => (k === 'measureText' ? () => ({ width: 40 }) : k in t ? t[k] : () => {}), set: (t, k, v) => { t[k] = v; return true; } });
    w.HTMLCanvasElement.prototype.getContext = () => ctx;
    w.matchMedia = () => ({ matches: false, addEventListener() {} });
    w.HTMLElement.prototype.scrollIntoView = () => {};
  },
});
const w = dom.window, d = w.document;
const wait = (ms) => new Promise((r) => setTimeout(r, ms));
(async () => {
  await wait(800);
  const f = new w.File([fs.readFileSync(process.argv[2], 'utf8')], 'data.json', { type: 'application/json' });
  const inp = d.querySelector('#fileIn');
  Object.defineProperty(inp, 'files', { value: [f], configurable: true });
  inp.dispatchEvent(new w.Event('change'));
  await wait(1500);
  const out = w.__allHits();
  fs.writeFileSync(process.argv[3], out);
  const o = JSON.parse(out);
  for (const [k, v] of Object.entries(o)) console.log(k, v.name, Object.keys(v.days).length + ' 天有選到');
  process.exit(0);
})();
