// Графики страницы пробы
(async function () {
  const D = await api(`/api/samples/${encodeURIComponent(CODE)}/chart-data`);
  const F = D.formulas, n = F.formula.length;
  const idx = [...Array(n).keys()];
  const maxRel = Math.max(...F.rel_intensity);
  const size = i => 3 + 14 * Math.sqrt(F.rel_intensity[i] / maxRel);
  const hover = i => `<b>${F.formula[i]}</b><br>m/z ${F.theo_mz[i].toFixed(4)}<br>H/C ${F.hc[i].toFixed(3)}, O/C ${F.oc[i].toFixed(3)}<br>DBE ${F.dbe[i]}, NOSC ${F.nosc[i].toFixed(2)}<br>отн. инт. ${(F.rel_intensity[i] * 100).toFixed(3)} %`;
  const LASZ = { lignin: '#7a5c3e', tannin: '#b5651d', peptide: '#c23b3b', lipid: '#d4a017', carbohydrate: '#3f9aa8', aminosugar: '#6b5fb5', undefinded: '#a0a9b3' };
  const LASZ_RU = { lignin: 'лигнины', tannin: 'танины', peptide: 'пептиды', lipid: 'липиды', carbohydrate: 'углеводы', aminosugar: 'аминосахара', undefinded: 'не опред.' };
  const ORDER = ['CHO', 'CHON', 'CHOS', 'CHONS'];
  const byKey = (key) => { const m = {}; idx.forEach(i => (m[F[key][i]] ||= []).push(i));
    if (key !== 'elemental_class') return m; const o = {}; ORDER.forEach(k => { if (m[k]) o[k] = m[k]; }); return o; };
  const drawn = {};

  function vk(mode) {
    let traces;
    const sub = (ids, name, color) => ({ type: 'scattergl', mode: 'markers', name, x: ids.map(i => F.oc[i]), y: ids.map(i => F.hc[i]),
      text: ids.map(hover), hoverinfo: 'text', marker: { size: ids.map(size), color, opacity: .7, line: { width: 0 } } });
    if (mode === 'class') traces = Object.entries(byKey('elemental_class')).map(([k, ids]) => sub(ids, `${k} (${ids.length})`, CLASS_COLORS[k]));
    else if (mode === 'lasz') traces = Object.entries(byKey('lasz_class')).map(([k, ids]) => sub(ids, `${LASZ_RU[k] || k} (${ids.length})`, LASZ[k] || '#888'));
    else {
      const key = mode === 'nosc' ? 'nosc' : 'rel_intensity';
      const order = idx.slice().sort((a, b) => F[key][a] - F[key][b]);
      const t = sub(order, '', order.map(i => mode === 'int' ? Math.log10(F.rel_intensity[i]) : F.nosc[i]));
      Object.assign(t.marker, { colorscale: mode === 'nosc' ? 'RdBu' : 'Viridis', reversescale: mode === 'nosc', showscale: true,
        colorbar: { title: { text: mode === 'nosc' ? 'NOSC' : 'lg отн. инт.', side: 'right' }, thickness: 12 } });
      t.showlegend = false; traces = [t];
    }
    Plotly.react('ch-vk', traces, layout({ xaxis: { title: 'O/C', range: [0, 1.05] }, yaxis: { title: 'H/C', range: [0.2, 2.1] } }), PLOT_CFG);
  }

  function ms() {
    const traces = Object.entries(byKey('elemental_class')).map(([k, ids]) => {
      const x = [], y = [], t = [];
      ids.forEach(i => { x.push(F.theo_mz[i], F.theo_mz[i], null); y.push(0, F.intensity[i], null); t.push(hover(i), hover(i), ''); });
      return { type: 'scattergl', mode: 'lines', name: k, x, y, text: t, hoverinfo: 'text', line: { color: CLASS_COLORS[k], width: 1 } };
    });
    Plotly.react('ch-ms', traces, layout({ xaxis: { title: 'm/z' }, yaxis: { title: 'Интенсивность', exponentformat: 'power' } }), PLOT_CFG);
  }

  function classes() {
    const c = D.classes;
    Plotly.react('ch-cls', [
      { type: 'bar', name: 'по числу формул', x: c.labels, y: c.count.map(v => v * 100), marker: { color: c.labels.map(k => CLASS_COLORS[k]) }, hovertemplate: '%{x}: %{y:.1f} %<extra>по числу</extra>' },
      { type: 'bar', name: 'по интенсивности', x: c.labels, y: c.intensity.map(v => v * 100), marker: { color: c.labels.map(k => CLASS_COLORS[k]), opacity: .45 }, hovertemplate: '%{x}: %{y:.1f} %<extra>по интенсивности</extra>' },
    ], layout({ barmode: 'group', yaxis: { title: '%' } }), PLOT_CFG);
    const l = D.lasz, ord = l.labels.map((k, i) => i).sort((a, b) => l.count[b] - l.count[a]);
    Plotly.react('ch-lasz', [
      { type: 'bar', name: 'по числу формул', x: ord.map(i => LASZ_RU[l.labels[i]] || l.labels[i]), y: ord.map(i => l.count[i] * 100), marker: { color: ord.map(i => LASZ[l.labels[i]]) } },
      { type: 'bar', name: 'по интенсивности', x: ord.map(i => LASZ_RU[l.labels[i]] || l.labels[i]), y: ord.map(i => l.intensity[i] * 100), marker: { color: ord.map(i => LASZ[l.labels[i]]), opacity: .45 } },
    ], layout({ barmode: 'group', yaxis: { title: '%' } }), PLOT_CFG);
  }

  function squares(mode) {
    const S = D.squares, vals = S[mode];
    const hb = S.hc_bins, ob = S.oc_bins;  // hc_bins: сверху вниз (1.8–2.2 … 0–0.6)
    const z = [], txt = [];
    for (let r = hb.length - 1; r >= 0; r--) {
      const row = [], trow = [];
      for (let c = 0; c < ob.length; c++) { const name = 'D' + String(S.layout[`${r},${c}`]).padStart(2, '0'); row.push(vals[name] * 100); trow.push(`${name}<br>${(vals[name] * 100).toFixed(1)} %`); }
      z.push(row); txt.push(trow);
    }
    const y = hb.slice().reverse().map(b => `${b[0]}–${b[1]}`), x = ob.map(b => `${b[0]}–${b[1]}`);
    Plotly.react('ch-sq', [{ type: 'heatmap', z, x, y, text: txt, texttemplate: '%{text}', hoverinfo: 'text', colorscale: SEQ_SCALE, showscale: true,
      colorbar: { title: { text: '%', side: 'right' }, thickness: 12 }, xgap: 2, ygap: 2 }],
      layout({ xaxis: { title: 'O/C', type: 'category' }, yaxis: { title: 'H/C', type: 'category' } }), PLOT_CFG);
  }

  function dbe() {
    const t = Object.entries(byKey('elemental_class')).map(([k, ids]) => ({ type: 'scattergl', mode: 'markers', name: k, x: ids.map(i => F.C[i]), y: ids.map(i => F.dbe[i]),
      text: ids.map(hover), hoverinfo: 'text', marker: { size: ids.map(size), color: CLASS_COLORS[k], opacity: .65 } }));
    Plotly.react('ch-dbe', t, layout({ xaxis: { title: 'C' }, yaxis: { title: 'DBE' } }), PLOT_CFG);
    const k = Object.entries(byKey('elemental_class')).map(([c, ids]) => ({ type: 'scattergl', mode: 'markers', name: c, x: ids.map(i => F.theo_mz[i]), y: ids.map(i => F.kmd[i]),
      text: ids.map(hover), hoverinfo: 'text', marker: { size: 5, color: CLASS_COLORS[c], opacity: .7 } }));
    Plotly.react('ch-kmd', k, layout({ xaxis: { title: 'm/z' }, yaxis: { title: 'KMD (CH₂)' } }), PLOT_CFG);
  }

  function err() {
    const ok = idx.filter(i => F.err_ppm[i] !== null);
    if (!ok.length) { document.getElementById('ch-err').innerHTML = '<div class="empty">В CSV нет ошибки m/z</div>'; return; }
    Plotly.react('ch-err', Object.entries(byKey('elemental_class')).map(([c, ids]) => {
      ids = ids.filter(i => F.err_ppm[i] !== null);
      return { type: 'scattergl', mode: 'markers', name: c, x: ids.map(i => F.theo_mz[i]), y: ids.map(i => F.err_ppm[i]), text: ids.map(hover), hoverinfo: 'text',
        marker: { size: ids.map(size), color: CLASS_COLORS[c], opacity: .65 } };
    }), layout({ xaxis: { title: 'm/z' }, yaxis: { title: 'ошибка, ppm', zeroline: true, zerolinecolor: '#c9d1da' } }), PLOT_CFG);
  }

  const draw = { vk: () => vk(document.querySelector('#vk-color .on').dataset.v), ms, cls: classes,
    sq: () => squares(document.querySelector('#sq-mode .on').dataset.v), dbe, err };
  function show(tab) {
    document.querySelectorAll('#tabs button').forEach(b => b.classList.toggle('on', b.dataset.tab === tab));
    document.querySelectorAll('.tab-pane').forEach(p => p.classList.toggle('on', p.id === 'tab-' + tab));
    if (draw[tab] && !drawn[tab]) { draw[tab](); drawn[tab] = true; }
    else document.querySelectorAll(`#tab-${tab} .js-plotly-plot`).forEach(p => Plotly.Plots.resize(p));
  }
  document.querySelectorAll('#tabs button').forEach(b => b.onclick = () => show(b.dataset.tab));
  const seg = (id, fn) => document.querySelectorAll(`#${id} button`).forEach(b => b.onclick = () => {
    document.querySelectorAll(`#${id} button`).forEach(x => x.classList.toggle('on', x === b)); fn(b.dataset.v); });
  seg('vk-color', vk); seg('sq-mode', squares);
  show('vk');
})().catch(e => toast(e.message, true));
