const D = window.TW, S = D.summary, C = D.crash, META = D.meta;
const GAMMAS = ['0', '1', '2', '4'];
const GLAB = { '0': 'Q（γ=0）', '1': '真實 γ=1', '2': '真實 γ=2', '4': '真實 γ=4' };
const DASH = { '0': [], '1': [8, 4], '2': [4, 3], '4': [1, 3] };
const css = n => getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const pct = (x, d = 1) => x == null || isNaN(x) ? '—' : (x * 100).toFixed(d) + '%';
const num = (x, d = 2) => x == null || isNaN(x) ? '—' : Number(x).toFixed(d);
const pOf = (date, th, g) => { const r = C[date]; return r && r[th] ? r[th][g] : null; };
const $ = (s, r = document) => r.querySelector(s);

function flagText(f) {
  if (!f) return [];
  return f.split(';').filter(Boolean).map(x => {
    let m;
    if ((m = x.match(/^threshold_(\d\.\d+)_extrapolated_(near|next)$/))) return `${m[2] === 'near' ? '近月' : '次月'}履約價未涵蓋 K/F=${m[1]}，該門檻機率靠外插`;
    if (x === 'official_missing') return '官方 VIX 尚未公布';
    if (x === 'vix_diff_warn') return '自算與公布 VIX 差距偏大';
    if (x === 'svix_gt_vix') return null;
    return '曲線外插違反無套利（已修正）：' + x;
  }).filter(Boolean);
}

function initChrome() {
  const u = $('#updated'); if (u) u.textContent = META.last_updated || '—';
  const v = $('#m-ver'); if (v) v.textContent = META.method_version || '—';
  const r = $('#m-rate'); if (r) r.textContent = ((META.params && META.params.risk_free_rate) * 100).toFixed(2) + '%';
  const a = $('#m-acc');
  if (a) {
    const d = S.map(x => x.vix_diff).filter(x => x != null);
    a.textContent = d.length
      ? `共 ${d.length} 個交易日對照，平均差 ${num(d.reduce((p, q) => p + q, 0) / d.length, 3)}，平均絕對誤差 ${num(d.reduce((p, q) => p + Math.abs(q), 0) / d.length, 3)}，最大絕對差 ${num(Math.max(...d.map(Math.abs)), 2)}（VIX 點）。`
      : '尚無可對照的公布值。';
  }
}

/* ---- 日期範圍篩選：所有圖與表格共用同一個範圍 ---- */
const state = { range: 0 };
const visible = () => state.range ? S.slice(-state.range) : S;
function bindRange(cb) {
  document.querySelectorAll('[data-range]').forEach(b => b.addEventListener('click', () => {
    state.range = +b.dataset.range;
    document.querySelectorAll('[data-range]').forEach(x => x.setAttribute('aria-pressed', String(x === b)));
    cb();
  }));
}

/* ---- 圖表 ---- */
const crosshair = {
  id: 'crosshair',
  afterDatasetsDraw(chart) {
    const a = chart.tooltip && chart.tooltip.getActiveElements();
    if (!a || !a.length) return;
    const x = a[0].element.x, { top, bottom } = chart.chartArea, c = chart.ctx;
    c.save(); c.strokeStyle = css('--ink-3'); c.lineWidth = 1; c.setLineDash([3, 3]);
    c.beginPath(); c.moveTo(x, top); c.lineTo(x, bottom); c.stroke(); c.restore();
  }
};
const charts = {};
function base(opts) {
  const txt = css('--ink-2');
  return {
    responsive: true, maintainAspectRatio: false, animation: false,
    interaction: { mode: 'index', intersect: false },
    scales: {
      x: { ticks: { color: txt, maxTicksLimit: 8, autoSkip: true }, grid: { display: false }, border: { color: css('--line') } },
      y: Object.assign({ ticks: { color: txt }, grid: { color: css('--grid') }, border: { display: false } }, opts.y || {}),
    },
    plugins: {
      legend: { display: opts.legend !== false, position: 'bottom', labels: { color: txt, boxWidth: 28, boxHeight: 2 } },
      tooltip: Object.assign({ backgroundColor: css('--card'), titleColor: css('--ink'), bodyColor: css('--ink'), borderColor: css('--line'), borderWidth: 1, padding: 10, boxPadding: 4 }, opts.tooltip || {}),
    },
  };
}
const line = (label, data, color, extra = {}) => Object.assign({ label, data, borderColor: color, backgroundColor: color, borderWidth: 2, pointRadius: 0, pointHoverRadius: 4, tension: 0, spanGaps: false }, extra);
function draw(id, labels, datasets, opts) {
  if (charts[id]) charts[id].destroy();
  charts[id] = new Chart(document.getElementById(id), { type: 'line', data: { labels, datasets }, options: base(opts), plugins: [crosshair] });
}
function chartFallback() {
  document.querySelectorAll('.chart').forEach(e => { e.textContent = '圖表函式庫載入失敗；請參考下方表格。'; });
}
function fillTable(sel, rowFn) {
  const tb = $(sel + ' tbody'); tb.textContent = '';
  visible().slice().reverse().forEach(r => {
    const tr = document.createElement('tr');
    rowFn(r).forEach(t => { const td = document.createElement('td'); td.textContent = t; tr.appendChild(td); });
    tb.appendChild(tr);
  });
}
initChrome();
