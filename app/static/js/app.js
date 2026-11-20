// Общие помощники интерфейса
const CLASS_COLORS = { CHO: '#2f6fa8', CHON: '#d9822b', CHOS: '#2e9461', CHONS: '#a8418f' };
const SEQ_SCALE = [[0, '#f3f7fb'], [0.5, '#7fa8cf'], [1, '#1f4e79']];
const GROUP_COLORS = ['#2f6fa8', '#d9822b', '#2e9461', '#a8418f', '#c23b3b', '#6b5fb5', '#3f9aa8', '#8a6d3b'];
const PLOT_CFG = { displaylogo: false, responsive: true, toImageButtonOptions: { format: 'png', scale: 3 },
  modeBarButtonsToRemove: ['lasso2d', 'select2d', 'autoScale2d'] };
const PLOT_LAYOUT = { margin: { l: 58, r: 16, t: 10, b: 48 }, font: { family: 'Inter, Segoe UI, system-ui, sans-serif', size: 12, color: '#18212b' },
  paper_bgcolor: '#fff', plot_bgcolor: '#fff', hoverlabel: { font: { size: 12 } },
  xaxis: { gridcolor: '#eef1f4', zeroline: false, linecolor: '#c9d1da', ticks: 'outside', tickcolor: '#c9d1da' },
  yaxis: { gridcolor: '#eef1f4', zeroline: false, linecolor: '#c9d1da', ticks: 'outside', tickcolor: '#c9d1da' },
  legend: { orientation: 'h', y: 1.08, x: 0, font: { size: 12 } } };
function layout(extra) {
  const L = JSON.parse(JSON.stringify(PLOT_LAYOUT));
  for (const [k, v] of Object.entries(extra || {})) L[k] = (typeof v === 'object' && !Array.isArray(v) && L[k]) ? Object.assign(L[k], v) : v;
  return L;
}

function toast(msg, err) {
  const t = document.getElementById('toast');
  t.textContent = msg; t.className = 'toast show' + (err ? ' err' : '');
  clearTimeout(t._h); t._h = setTimeout(() => t.className = 'toast', err ? 6000 : 3000);
}

async function api(url, opts = {}) {
  const o = Object.assign({ headers: {} }, opts);
  if (o.json !== undefined) { o.body = JSON.stringify(o.json); o.headers['Content-Type'] = 'application/json'; delete o.json; }
  const r = await fetch(url, o);
  let data = null;
  try { data = await r.json(); } catch (e) { /* не JSON */ }
  if (!r.ok) {
    const msg = data && data.detail ? (typeof data.detail === 'string' ? data.detail : JSON.stringify(data.detail)) : `${r.status} ${r.statusText}`;
    throw new Error(msg);
  }
  return data;
}

const fmt = (x, n = 3) => (x === null || x === undefined || Number.isNaN(x)) ? '—' :
  (typeof x === 'number' ? (Math.abs(x) >= 1000 ? x.toLocaleString('ru-RU', { maximumFractionDigits: 0 }) : x.toFixed(n)) : x);
const fmtP = p => p === null || p === undefined ? '—' : (p < 0.001 ? p.toExponential(1) : p.toFixed(3));
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

// Сортировка таблицы по клику на заголовок (значение из data-sort или текста)
function makeSortable(table) {
  const ths = [...table.tHead.rows[0].cells];
  ths.forEach((th, i) => {
    if (!th.classList.contains('sortable')) return;
    th.addEventListener('click', () => {
      const asc = !th.classList.contains('sorted-asc');
      ths.forEach(h => h.classList.remove('sorted-asc', 'sorted-desc'));
      th.classList.add(asc ? 'sorted-asc' : 'sorted-desc');
      const rows = [...table.tBodies[0].rows];
      const val = r => { const c = r.cells[i]; const v = c.dataset.sort ?? c.textContent.trim(); const n = parseFloat(v); return (v !== '' && !isNaN(n) && /^-?[\d.eE+-]+$/.test(v)) ? n : v.toLowerCase(); };
      rows.sort((a, b) => { const x = val(a), y = val(b); return (x > y ? 1 : x < y ? -1 : 0) * (asc ? 1 : -1); });
      rows.forEach(r => table.tBodies[0].appendChild(r));
    });
  });
}

// Фильтр строк таблицы: поиск по data-search, проект по data-project, качество по data-quality
function makeFilter(table, sel) {
  const q = document.querySelector(sel.q), pr = sel.project && document.querySelector(sel.project),
    qu = sel.quality && document.querySelector(sel.quality), cnt = sel.count && document.querySelector(sel.count);
  const run = () => {
    const s = (q.value || '').toLowerCase().trim(); let n = 0; const rows = [...table.tBodies[0].rows];
    rows.forEach(r => {
      let ok = !s || (r.dataset.search || r.textContent.toLowerCase()).includes(s);
      if (ok && pr && pr.value) ok = pr.value === '__none' ? !r.dataset.project : r.dataset.project === pr.value;
      if (ok && qu && qu.value) ok = r.dataset.quality === qu.value;
      r.style.display = ok ? '' : 'none'; if (ok) n++;
    });
    if (cnt) cnt.textContent = `${n} из ${rows.length}`;
  };
  [q, pr, qu].forEach(e => e && e.addEventListener('input', run));
  run();
  return run;
}

// Диалог редактирования пробы (журнал и страница пробы)
function openSampleDialog(sample, onSaved) {
  const dlg = document.getElementById('sample-dlg');
  const f = dlg.querySelector('form');
  f.reset();
  const isNew = !sample;
  dlg.querySelector('.dlg-title').textContent = isNew ? 'Новая проба' : `Проба ${sample.code}`;
  const map = { code: 'code', project: 'project', group_label: 'group', sample_type: 'sample_type', location: 'location',
    sampling_date: 'sampling_date', extraction: 'extraction', measured_at: 'measured_at', operator: 'operator',
    description: 'description', notes: 'notes' };
  if (sample) for (const [field, key] of Object.entries(map)) { const el = f.elements[field]; if (el) el.value = sample[key] ?? ''; }
  dlg.querySelector('.btn-delete').style.display = isNew ? 'none' : '';
  f.onsubmit = async (e) => {
    e.preventDefault();
    const data = Object.fromEntries(new FormData(f).entries());
    try {
      const res = isNew ? await api('/api/samples', { method: 'POST', json: data })
        : await api(`/api/samples/${encodeURIComponent(sample.code)}`, { method: 'PATCH', json: data });
      dlg.close(); toast('Сохранено'); onSaved && onSaved(res);
    } catch (err) { toast(err.message, true); }
  };
  dlg.querySelector('.btn-delete').onclick = async () => {
    if (!confirm(`Удалить пробу ${sample.code} вместе со всеми загруженными спектрами?`)) return;
    try { await api(`/api/samples/${encodeURIComponent(sample.code)}`, { method: 'DELETE' }); dlg.close(); toast('Проба удалена'); onSaved && onSaved(null); }
    catch (err) { toast(err.message, true); }
  };
  dlg.showModal();
}
