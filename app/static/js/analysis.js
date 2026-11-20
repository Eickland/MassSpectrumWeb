// Страница анализа: выбор проб, группировка, статистика, PCA, перекрытие формул
(function () {
  const list = document.getElementById('pick-list');
  const labels = [...list.querySelectorAll('label')];
  const boxes = labels.map(l => l.querySelector('input'));
  const by = document.getElementById('by');
  const params = new URLSearchParams(location.search);
  const L = k => LABELS[k] || k;
  let last = null, csvRows = null;

  // --- выбор проб
  const pickQ = document.getElementById('pick-q'), pickP = document.getElementById('pick-project');
  const visible = l => l.style.display !== 'none';
  function filterPick() {
    const q = pickQ.value.toLowerCase(), p = pickP.value;
    labels.forEach(l => l.style.display = ((!q || l.dataset.code.toLowerCase().includes(q)) && (!p || l.dataset.project === p)) ? '' : 'none');
  }
  const count = () => document.getElementById('sel-count').textContent = `выбрано: ${boxes.filter(b => b.checked).length}`;
  pickQ.oninput = filterPick; pickP.onchange = filterPick; list.onchange = count;
  document.getElementById('sel-all').onclick = () => { labels.forEach(l => { if (visible(l)) l.querySelector('input').checked = true; }); count(); };
  document.getElementById('sel-none').onclick = () => { boxes.forEach(b => b.checked = false); count(); };
  const pre = (params.get('samples') || '').split(',').filter(Boolean), pid = params.get('project_id');
  boxes.forEach(b => { b.checked = pre.length ? pre.includes(b.value) : (pid ? b.dataset.pid === pid : true); });
  if (pid) { const opt = [...pickP.options].find(o => labels.some(l => l.dataset.project === o.value && l.querySelector('input').dataset.pid === pid)); if (opt) { pickP.value = opt.value; filterPick(); } }
  count();

  // --- способ группировки
  const syncBy = () => {
    document.getElementById('regex-box').style.display = by.value === 'regex' ? '' : 'none';
    document.getElementById('manual-hint').style.display = by.value === 'manual' ? '' : 'none';
    list.querySelectorAll('.man-g').forEach(s => s.style.display = by.value === 'manual' ? '' : 'none');
  };
  by.onchange = syncBy;
  // если у выбранных проб нет поля «Группа», а проектов несколько — группируем по проекту
  const selGroups = new Set(boxes.filter(b => b.checked).map(b => b.dataset.group).filter(Boolean));
  if (selGroups.size < 2) by.value = new Set(boxes.filter(b => b.checked).map(b => b.dataset.pid)).size > 1 ? 'project' : 'regex';
  syncBy();
  document.getElementById('rx-add').onclick = () => {
    const r = document.getElementById('regex-rows');
    r.insertAdjacentHTML('beforeend', '<div class="field"><input type="text" class="rx-name" placeholder="имя группы"></div><div class="field"><input type="text" class="rx-val" placeholder="regex"></div>');
  };

  function body() {
    const samples = boxes.filter(b => b.checked).map(b => b.value);
    const b = { samples, by: by.value, exclude_poor: document.getElementById('excl-poor').checked,
      min_presence: parseFloat(document.getElementById('presence').value) || 0.5 };
    if (by.value === 'regex') {
      const names = [...document.querySelectorAll('.rx-name')].map(e => e.value.trim()), vals = [...document.querySelectorAll('.rx-val')].map(e => e.value.trim());
      b.patterns = {}; names.forEach((n, i) => { if (n && vals[i]) b.patterns[n] = vals[i]; });
    }
    if (by.value === 'manual') {
      b.manual = {}; labels.forEach(l => { const c = l.querySelector('input'); if (c.checked) (b.manual[l.querySelector('.man-g').value] ||= []).push(c.value); });
    }
    return b;
  }

  // --- вкладки
  const drawn = {};
  function show(tab) {
    document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.toggle('on', p.id === 'tab-' + tab));
    if (!drawn[tab] && renderers[tab]) { renderers[tab](); drawn[tab] = true; }
    document.querySelectorAll(`#tab-${tab} .js-plotly-plot`).forEach(p => Plotly.Plots.resize(p));
  }
  document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => show(b.dataset.tab));

  // --- расчёт
  document.getElementById('run').onclick = async () => {
    const b = body();
    if (b.samples.length < 2) return toast('Выберите хотя бы две пробы', true);
    const btn = document.getElementById('run'); btn.disabled = true; btn.textContent = 'Считаю…';
    try {
      const [cmp, pca, ovl] = await Promise.allSettled([
        api('/api/analysis/compare', { method: 'POST', json: b }), api('/api/analysis/pca', { method: 'POST', json: b }),
        api('/api/analysis/overlap', { method: 'POST', json: b })]);
      if (cmp.status === 'rejected') throw cmp.reason;
      last = { cmp: cmp.value, pca: pca.status === 'fulfilled' ? pca.value : { error: pca.reason.message },
        ovl: ovl.status === 'fulfilled' ? ovl.value : { error: ovl.reason.message } };
      document.getElementById('result-empty').style.display = 'none'; document.getElementById('results').style.display = '';
      Object.keys(drawn).forEach(k => delete drawn[k]);
      fillBoxSelect(); show(document.querySelector('#tabs button.on').dataset.tab);
    } catch (e) { toast(e.message, true); }
    finally { btn.disabled = false; btn.textContent = 'Рассчитать'; }
  };

  const color = i => GROUP_COLORS[i % GROUP_COLORS.length];
  const groupOf = code => { for (const [g, l] of Object.entries(last.cmp.membership)) if (l.includes(code)) return g; return ''; };

  function renderStat() {
    const c = last.cmp, G = c.groups, sig = document.getElementById('only-sig').checked;
    document.getElementById('stat-head').innerHTML = `${esc(c.test)} · ` + G.map((g, i) => `<span class="legend-dot" style="background:${color(i)}"></span>${esc(g)} (n = ${c.sizes[i]})`).join(' · ');
    const two = G.length === 2;
    let h = '<thead><tr><th>Дескриптор</th>' + G.map(g => `<th class="num">медиана ${esc(g)}</th>`).join('') + G.map(g => `<th class="num">IQR ${esc(g)}</th>`).join('') +
      `<th class="num">${two ? 'U' : 'H'}</th><th class="num">p</th><th class="num">q</th>${two ? '<th class="num">δ Клиффа</th>' : ''}</tr></thead><tbody>`;
    for (const r of c.rows) {
      if (sig && !(r.q < 0.05)) continue;
      h += `<tr class="${r.q < 0.05 ? 'sig' : ''}" data-d="${esc(r.descriptor)}" style="cursor:pointer"><td>${esc(r.label)}</td>` + r.median.map(v => `<td class="num">${fmt(v, 4)}</td>`).join('') +
        r.iqr.map(v => `<td class="num">${fmt(v, 4)}</td>`).join('') + `<td class="num">${fmt(r.stat, 1)}</td><td class="num">${fmtP(r.p)}</td><td class="num"><strong>${fmtP(r.q)}</strong></td>` +
        (two ? `<td class="num">${fmt(r.effect, 2)}</td>` : '') + '</tr>';
    }
    const t = document.getElementById('stat-tbl'); t.innerHTML = h + '</tbody>';
    t.querySelectorAll('tbody tr').forEach(tr => tr.onclick = () => { document.getElementById('box-sel').value = tr.dataset.d; drawn.box = false; show('box'); renderBox(); });
  }
  document.getElementById('only-sig').onchange = () => last && renderStat();
  document.getElementById('stat-csv').onclick = () => {
    const c = last.cmp, G = c.groups;
    const head = ['descriptor', 'label', ...G.map(g => `n_${g}`), ...G.map(g => `median_${g}`), ...G.map(g => `iqr_${g}`), 'stat', 'p', 'q', 'cliffs_delta'];
    downloadCsv('statistics.csv', [head, ...c.rows.map(r => [r.descriptor, r.label, ...r.n, ...r.median, ...r.iqr, r.stat, r.p, r.q, r.effect])]);
  };

  function fillBoxSelect() {
    const s = document.getElementById('box-sel'), cur = s.value;
    s.innerHTML = last.cmp.rows.map(r => `<option value="${esc(r.descriptor)}">${esc(r.label)} (q = ${fmtP(r.q)})</option>`).join('');
    if (cur && [...s.options].some(o => o.value === cur)) s.value = cur;
  }
  function renderBox() {
    const k = document.getElementById('box-sel').value, T = last.cmp.table;
    const tr = last.cmp.groups.map((g, i) => { const rows = T.filter(r => groupOf(r.sample) === g);
      return { type: 'box', name: g, y: rows.map(r => r[k]), text: rows.map(r => r.sample), boxpoints: 'all', jitter: .4, pointpos: 0,
        marker: { color: color(i), size: 7 }, line: { color: color(i) }, fillcolor: color(i) + '22', hovertemplate: '%{text}: %{y:.4f}<extra></extra>' }; });
    Plotly.react('ch-box', tr, layout({ yaxis: { title: L(k) }, showlegend: false }), PLOT_CFG);
  }
  document.getElementById('box-sel').onchange = renderBox;

  function renderPca() {
    const P = last.pca;
    if (P.error) { document.getElementById('ch-pca').innerHTML = `<div class="empty">${esc(P.error)}</div>`; document.getElementById('ch-load').innerHTML = ''; return; }
    const gs = [...last.cmp.groups.filter(g => P.group.includes(g)), ...new Set(P.group.filter(g => !last.cmp.groups.includes(g)))];
    const pad = (k) => { const v = P.scores.map(r => r[k] ?? 0), lo = Math.min(...v), hi = Math.max(...v), d = (hi - lo) * 0.18 || 1; return [lo - d, hi + d]; };
    Plotly.react('ch-pca', gs.map((g, i) => { const ids = P.samples.map((s, j) => j).filter(j => P.group[j] === g);
      return { type: 'scatter', mode: 'markers+text', name: g || '—', x: ids.map(j => P.scores[j][0]), y: ids.map(j => P.scores[j][1]),
        text: ids.map(j => P.samples[j]), textposition: 'top center', textfont: { size: 10, color: '#5d6b7a' }, marker: { size: 11, color: color(i) },
        hovertemplate: '%{text}<extra></extra>' }; }),
      layout({ xaxis: { title: `PC1 (${(P.explained[0] * 100).toFixed(1)} %)`, zeroline: true, zerolinecolor: '#dde3e9', range: pad(0) },
        yaxis: { title: `PC2 (${((P.explained[1] || 0) * 100).toFixed(1)} %)`, zeroline: true, zerolinecolor: '#dde3e9', range: pad(1) } }), PLOT_CFG);
    const lo = P.loadings;
    Plotly.react('ch-load', [{ type: 'bar', orientation: 'h', name: 'PC1', y: lo.labels, x: lo.values.map(v => v[0]), marker: { color: '#2f6fa8' } },
      { type: 'bar', orientation: 'h', name: 'PC2', y: lo.labels, x: lo.values.map(v => v[1] ?? 0), marker: { color: '#d9822b' } }],
      layout({ barmode: 'group', margin: { l: 20 }, yaxis: { autorange: 'reversed', automargin: true }, xaxis: { title: 'нагрузка' } }), PLOT_CFG);
  }

  function renderOvl() {
    const O = last.ovl;
    if (O.error) { document.getElementById('ovl-kpis').innerHTML = `<div class="empty">${esc(O.error)}</div>`; return; }
    document.getElementById('ovl-kpis').innerHTML = `<div class="kpi"><div class="v">${O.common}</div><div class="l">общих для всех групп</div></div>` +
      O.groups.map((g, i) => `<div class="kpi"><div class="v" style="color:${color(i)}">${O.sets[g].n_specific}</div><div class="l">специфичных «${esc(g)}» (из ${O.sets[g].n_member} формул группы, n = ${O.sizes[i]})</div></div>`).join('');
    const tr = [{ type: 'scattergl', mode: 'markers', name: `общие (${O.common})`, x: O.common_set.oc, y: O.common_set.hc, text: O.common_set.formula,
      hoverinfo: 'text', marker: { size: 4, color: '#c3cad2' } }];
    O.groups.forEach((g, i) => { const s = O.sets[g];
      tr.push({ type: 'scattergl', mode: 'markers', name: `${g} (${s.n_specific})`, x: s.oc, y: s.hc, text: s.formula, hoverinfo: 'text', marker: { size: 6, color: color(i), opacity: .8 } }); });
    Plotly.react('ch-ovl', tr, layout({ xaxis: { title: 'O/C', range: [0, 1.05] }, yaxis: { title: 'H/C', range: [0.2, 2.1] } }), PLOT_CFG);
    const J = O.jaccard;
    Plotly.react('ch-jac', [{ type: 'heatmap', z: J.matrix, x: J.samples, y: J.samples, colorscale: SEQ_SCALE, zmin: 0, zmax: 1, colorbar: { thickness: 12 },
      hovertemplate: '%{x}<br>%{y}<br>Жаккар %{z:.2f}<extra></extra>' }], layout({ margin: { l: 20, b: 20 }, xaxis: { tickangle: -45, automargin: true }, yaxis: { autorange: 'reversed', automargin: true } }), PLOT_CFG);
  }
  document.getElementById('ovl-csv').onclick = () => {
    const O = last.ovl; const rows = [['group', 'formula', 'mz', 'H/C', 'O/C', 'class', 'mean_rel_intensity']];
    O.groups.forEach(g => { const s = O.sets[g]; s.formula.forEach((f, i) => rows.push([g, f, s.mz[i], s.hc[i], s.oc[i], s.cls[i], s.rel[i]])); });
    downloadCsv('specific_formulas.csv', rows);
  };

  function renderTbl() {
    const T = last.cmp.table; if (!T.length) return;
    const cols = Object.keys(T[0]);
    document.getElementById('desc-tbl').innerHTML = '<thead><tr>' + cols.map(c => `<th title="${esc(c)}">${esc(L(c))}</th>`).join('') + '</tr></thead><tbody>' +
      T.map(r => '<tr>' + cols.map(c => typeof r[c] === 'number' ? `<td class="num">${fmt(r[c], 4)}</td>` : `<td>${esc(r[c])}</td>`).join('') + '</tr>').join('') + '</tbody>';
    csvRows = [cols, ...T.map(r => cols.map(c => r[c]))];
  }
  document.getElementById('tbl-csv').onclick = () => { if (!csvRows) renderTbl(); downloadCsv('descriptors.csv', csvRows); };

  const renderers = { stat: renderStat, box: renderBox, pca: renderPca, ovl: renderOvl, tbl: renderTbl };

  function downloadCsv(name, rows) {
    const s = rows.map(r => r.map(v => v === null || v === undefined ? '' : (/[",;\n]/.test(String(v)) ? `"${String(v).replace(/"/g, '""')}"` : v)).join(',')).join('\n');
    const a = document.createElement('a'); a.href = URL.createObjectURL(new Blob(['﻿' + s], { type: 'text/csv' })); a.download = name; a.click();
  }

  if (boxes.filter(b => b.checked).length >= 2 && (pre.length || pid)) document.getElementById('run').click();
})();
