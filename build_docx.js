// build_docx.js - 把 report_full.json 轉成 Word 檔（完整版報告：全部股票、每檔詳細說明與買賣建議）
// 用法：node build_docx.js report_full.json 輸出.docx
const fs = require('fs');
const {
  Document, Packer, Paragraph, TextRun, HeadingLevel, Table, TableRow, TableCell, WidthType, ShadingType,
  AlignmentType, LevelFormat, BorderStyle, PageBreak, Footer, PageNumber, TableOfContents,
} = require('docx');

const R = JSON.parse(fs.readFileSync(process.argv[2], 'utf8'));
const out = process.argv[3] || '條件選股室.docx';
const FONT = 'Microsoft JhengHei';
const ACCENT = '0D6C7B';

const p = (text, o = {}) => new Paragraph({ spacing: { after: 80 }, ...o, children: [new TextRun({ text, font: FONT, size: o.size || 21, bold: o.bold, color: o.color })] });
const bullet = (text) => new Paragraph({ numbering: { reference: 'dots', level: 0 }, spacing: { after: 40 }, children: [new TextRun({ text, font: FONT, size: 20 })] });
const h = (text, level) => new Paragraph({ heading: level, spacing: { before: 240, after: 120 }, children: [new TextRun({ text, font: FONT })] });

// 一行「標籤：內容」→ 標籤加粗；「建議」整行用主色
function detail(line) {
  const i = line.indexOf('：');
  const label = i > 0 && i < 8 ? line.slice(0, i) : '';
  const runs = label
    ? [new TextRun({ text: label + '：', font: FONT, size: 20, bold: true, color: label === '建議' ? ACCENT : undefined }),
       new TextRun({ text: line.slice(i + 1), font: FONT, size: 20, bold: label === '建議', color: label === '建議' ? ACCENT : undefined })]
    : [new TextRun({ text: line, font: FONT, size: 20 })];
  return new Paragraph({ numbering: { reference: 'dots', level: 0 }, spacing: { after: 40 }, children: runs });
}

// 總表：全部股票一列一檔
const W = [1500, 800, 900, 1500, 900, 900, 2526];  // 合計 9026（A4 扣邊界）
const cell = (text, i, head) => new TableCell({
  width: { size: W[i], type: WidthType.DXA },
  shading: head ? { type: ShadingType.CLEAR, fill: 'DAECEE', color: 'auto' } : undefined,
  margins: { top: 40, bottom: 40, left: 60, right: 60 },
  children: [new Paragraph({ children: [new TextRun({ text: String(text), font: FONT, size: 17, bold: head })] })],
});
const summary = new Table({
  width: { size: W.reduce((a, b) => a + b, 0), type: WidthType.DXA },
  columnWidths: W,
  rows: [
    new TableRow({ tableHeader: true, children: ['股票', '收盤', '建議', '買進區間', '停損', '目標', '入選策略'].map((t, i) => cell(t, i, true)) }),
    ...R.summary.map((x) => new TableRow({ children: [`${x.id} ${x.name}`, x.close, x.act, x.zone, x.stop, x.t1, x.strat].map((t, i) => cell(t, i)) })),
  ],
});

const body = [
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 120 }, children: [new TextRun({ text: '條件選股室｜完整報告', font: FONT, size: 40, bold: true, color: ACCENT })] }),
  new Paragraph({ alignment: AlignmentType.CENTER, spacing: { after: 240 }, children: [new TextRun({ text: `${R.date} 收盤｜國際風險：${R.risk}｜共 ${R.count} 檔入選`, font: FONT, size: 22 })] }),
  p('怎麼看：先看總表找到想看的股票，再翻到後面的詳細說明。每一檔都有「建議」：可買區間、停損價、目標價，或要等拉回／觀望的原因。價格依固定規則計算，不是投資建議。', { size: 20, color: '4F5E6B' }),
  new TableOfContents('目錄', { hyperlink: true, headingStyleRange: '1-2' }),
  new Paragraph({ children: [new PageBreak()] }),
  h('全部股票總表', HeadingLevel.HEADING_1),
  summary,
];
for (const sec of R.sections) {
  body.push(new Paragraph({ children: [new PageBreak()] }), h(sec.title, HeadingLevel.HEADING_1));
  if (sec.intro) body.push(p(sec.intro, { color: '4F5E6B' }));
  for (const b of sec.bullets || []) if (b.trim()) body.push(bullet(b.trim()));
  for (const it of sec.items || []) {
    body.push(h(it.head, HeadingLevel.HEADING_2));
    for (const l of it.lines) if (l.trim()) body.push(detail(l.trim()));
  }
}

const doc = new Document({
  styles: {
    default: { document: { run: { font: FONT, size: 21 } } },
    paragraphStyles: [
      { id: 'Heading1', name: 'Heading 1', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 30, bold: true, color: ACCENT, font: FONT }, paragraph: { spacing: { before: 240, after: 120 }, outlineLevel: 0 } },
      { id: 'Heading2', name: 'Heading 2', basedOn: 'Normal', next: 'Normal', quickFormat: true, run: { size: 24, bold: true, font: FONT },
        paragraph: { spacing: { before: 200, after: 80 }, outlineLevel: 1, border: { bottom: { style: BorderStyle.SINGLE, size: 4, color: 'D8DEE3', space: 2 } } } },
    ],
  },
  numbering: { config: [{ reference: 'dots', levels: [{ level: 0, format: LevelFormat.BULLET, text: '•', alignment: AlignmentType.LEFT, style: { paragraph: { indent: { left: 360, hanging: 240 } } } }] }] },
  sections: [{
    properties: { page: { size: { width: 11906, height: 16838 }, margin: { top: 1134, bottom: 1134, left: 1440, right: 1440 } } },
    footers: { default: new Footer({ children: [new Paragraph({ alignment: AlignmentType.CENTER, children: [new TextRun({ children: ['條件選股室 ', R.date, '｜第 ', PageNumber.CURRENT, ' 頁'], font: FONT, size: 16, color: '8492A0' })] })] }) },
    children: body,
  }],
});
Packer.toBuffer(doc).then((b) => { fs.writeFileSync(out, b); console.log('已產生', out, Math.round(b.length / 1024) + 'KB'); });
