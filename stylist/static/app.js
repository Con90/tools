// Stylist front end. Everything is stored in cm; the unit toggle only changes
// what's shown and how typed values are read.

const $ = (sel, root = document) => root.querySelector(sel);
const $$ = (sel, root = document) => [...root.querySelectorAll(sel)];

const state = { meta: null, profiles: [], charts: [], unit: 'cm', editingChart: null };

try { state.unit = localStorage.getItem('stylist.unit') || 'cm'; } catch { /* storage unavailable */ }

// --- helpers -----------------------------------------------------------------

async function api(path, options = {}) {
  const res = await fetch(path, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
    body: options.body ? JSON.stringify(options.body) : undefined,
  });
  if (res.status === 204) return null;
  const data = await res.json().catch(() => null);
  if (!res.ok) {
    const detail = data?.detail;
    const msg = Array.isArray(detail)
      ? detail.map(d => `${d.loc.slice(1).join('.')}: ${d.msg}`).join('; ')
      : detail || res.statusText;
    throw new Error(msg);
  }
  return data;
}

const toDisplay = cm => state.unit === 'in' ? cm / 2.54 : cm;
const fromDisplay = v => state.unit === 'in' ? v * 2.54 : v;
const fmt = cm => {
  const v = toDisplay(cm);
  return String(Math.round(v * (state.unit === 'in' ? 4 : 2)) / (state.unit === 'in' ? 4 : 2));
};
const fmtRange = r => Array.isArray(r) ? (r[0] === r[1] ? fmt(r[0]) : `${fmt(r[0])}–${fmt(r[1])}`) : fmt(r);

// "86-91", "86–91", "86 to 91" or "86" → [lo, hi] / number, in cm. Empty → null.
// Read a range cell, keeping the stored value if the displayed text is unchanged.
function readCell(input) {
  const stored = input.dataset.cm ? JSON.parse(input.dataset.cm) : null;
  if (stored != null && input.value === fmtRange(stored)) return stored;
  return parseRange(input.value);
}

const cellAttrs = v => v != null ? `value="${fmtRange(v)}" data-cm="${esc(JSON.stringify(v))}"` : '';

function parseRange(text) {
  const t = text.trim();
  if (!t) return null;
  const parts = t.split(/\s*(?:-|–|—|to)\s*/).map(Number);
  if (parts.some(n => !Number.isFinite(n) || n <= 0) || parts.length > 2) throw new Error(`Can't read "${t}"`);
  const cm = parts.map(n => Math.round(fromDisplay(n) * 10) / 10);
  return cm.length === 1 ? cm[0] : cm;
}

const label = key => state.meta.measurements[key]?.label ?? key;
const esc = s => String(s).replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' })[c]);

function fillSelect(select, entries, selected) {
  select.innerHTML = entries.map(([v, text]) =>
    `<option value="${esc(v)}"${String(v) === String(selected) ? ' selected' : ''}>${esc(text)}</option>`).join('');
}

// --- navigation & units ----------------------------------------------------------

function show(view) {
  $$('nav button').forEach(b => b.classList.toggle('active', b.dataset.view === view));
  $$('.view').forEach(v => { v.hidden = v.id !== `view-${view}`; });
  if (view === 'find') renderFind();
  if (view === 'profile') renderProfile();
  if (view === 'charts') renderCharts();
}

function setUnit(unit) {
  // Re-read the profile form in the old unit before switching, so unsaved
  // typing isn't lost or mis-converted.
  const pending = !$('#view-profile').hidden ? readMeasurements() : null;
  state.unit = unit;
  try { localStorage.setItem('stylist.unit', unit); } catch { /* ignore */ }
  $$('.units button').forEach(b => b.classList.toggle('active', b.dataset.unit === unit));
  $$('.unit-label').forEach(el => { el.textContent = `(${unit})`; });
  if (pending) renderMeasureGrid(pending);
  if (!$('#view-find').hidden) renderFind();
  if (!$('#view-charts').hidden) renderCharts();
}

// --- find my size -------------------------------------------------------------------

async function renderFind() {
  const profileSel = $('#find-profile');
  const garmentSel = $('#find-garment');
  const current = profileSel.value || state.profiles[0]?.id;
  fillSelect(profileSel, state.profiles.map(p => [p.id, p.name]), current);
  if (!garmentSel.options.length) {
    fillSelect(garmentSel, Object.entries(state.meta.garments).map(([k, g]) => [k, g.label]), 'tops');
  }

  const empty = $('#find-empty');
  const out = $('#find-results');
  if (!state.profiles.length) {
    empty.hidden = false;
    empty.innerHTML = 'Start by <a href="#" data-goto="profile">adding your measurements</a>.';
    out.innerHTML = '';
    return;
  }

  const fit = $('#find-fit').value;
  const q = new URLSearchParams({ profile_id: profileSel.value, garment: garmentSel.value });
  if (fit) q.set('fit', fit);
  const results = await api(`/api/match?${q}`);

  empty.hidden = results.length > 0;
  if (!results.length) {
    const profile = state.profiles.find(p => String(p.id) === profileSel.value);
    const hasAny = Object.keys(profile?.measurements || {}).length > 0;
    empty.innerHTML = hasAny
      ? `No size charts cover ${esc(state.meta.garments[garmentSel.value].label.toLowerCase())} with the measurements you've entered.
         <a href="#" data-goto="charts">Add a size chart</a> or <a href="#" data-goto="profile">add more measurements</a>.`
      : 'Your profile has no measurements yet. <a href="#" data-goto="profile">Add them</a>.';
  }
  out.innerHTML = results.map(resultCard).join('');
}

const VERDICT = { great: 'Great fit', good: 'Good fit', poor: 'Poor fit' };

function detailList(details) {
  return `<ul class="details">${details.map(d => `
    <li class="st-${d.status}"><span>${esc(d.label)}</span>
      <span class="muted">you ${fmt(d.body)} · size ${fmtRange(d.range)}</span>
      <b>${esc(d.note)}</b></li>`).join('')}</ul>`;
}

function resultCard(r) {
  const length = r.length ? ` <span class="length">${esc(r.length.label)} leg</span>` : '';
  const alt = r.alternative
    ? `<p class="alt">Between sizes — <b>${esc(r.alternative.size)}</b> also works:</p>${detailList(r.alternative.details)}`
    : '';
  const lengthNote = r.length && r.length.status !== 'good'
    ? `<p class="muted">Leg length: ${esc(r.length.note)}</p>` : '';
  return `<article class="card result v-${r.verdict}">
    <header>
      <div><h3>${esc(r.brand)}</h3><span class="muted">${esc(state.meta.sections[r.section] || '')}</span></div>
      <div class="size"><span class="big">${esc(r.size)}</span>${length}</div>
    </header>
    <span class="badge">${VERDICT[r.verdict]}</span>
    ${detailList(r.details)}${lengthNote}${alt}
  </article>`;
}

// --- profile ------------------------------------------------------------------------

function renderMeasureGrid(values = {}) {
  $('#measure-grid').innerHTML = Object.entries(state.meta.measurements).map(([key, m]) => `
    <label>${esc(m.label)}
      <input type="number" step="any" min="0" name="m-${key}"
        value="${values[key] != null ? fmt(values[key]) : ''}" data-cm="${values[key] ?? ''}">
    </label>`).join('');
}

function readMeasurements() {
  const out = {};
  for (const key of Object.keys(state.meta.measurements)) {
    const input = $(`[name="m-${key}"]`);
    if (!input?.value) continue;
    // Untouched fields keep their exact stored value, so flipping cm/in and
    // saving doesn't drift 90 cm to 90.2 cm through rounding.
    const cm = input.dataset.cm;
    out[key] = cm && input.value === fmt(Number(cm))
      ? Number(cm)
      : Math.round(fromDisplay(Number(input.value)) * 10) / 10;
  }
  return out;
}

function loadProfileForm(profile) {
  const form = $('#profile-form');
  form.dataset.id = profile?.id ?? '';
  form.name.value = profile?.name ?? '';
  form.fit.value = profile?.fit ?? 'regular';
  const sections = profile?.sections ?? ['womens', 'mens', 'unisex'];
  $$('[name="sections"]', form).forEach(cb => { cb.checked = sections.includes(cb.value); });
  renderMeasureGrid(profile?.measurements);
  $('#profile-delete').hidden = !profile;
  $('#profile-status').textContent = '';
}

function renderProfile() {
  const sel = $('#profile-select');
  const form = $('#profile-form');
  const id = form.dataset.id || state.profiles[0]?.id || '';
  fillSelect(sel, [...state.profiles.map(p => [p.id, p.name]), ...(id ? [] : [['', 'New profile']])], id);
  loadProfileForm(state.profiles.find(p => String(p.id) === String(id)));
}

async function saveProfile(e) {
  e.preventDefault();
  const form = e.target;
  const body = {
    name: form.name.value.trim(),
    fit: form.fit.value,
    sections: $$('[name="sections"]:checked', form).map(cb => cb.value),
    measurements: readMeasurements(),
  };
  const status = $('#profile-status');
  try {
    const id = form.dataset.id;
    const saved = id
      ? await api(`/api/profiles/${id}`, { method: 'PUT', body })
      : await api('/api/profiles', { method: 'POST', body });
    state.profiles = await api('/api/profiles');
    form.dataset.id = saved.id;
    renderProfile();
    status.textContent = 'Saved.';
  } catch (err) {
    status.textContent = err.message;
  }
}

async function deleteProfile() {
  const id = $('#profile-form').dataset.id;
  if (!id || !confirm('Delete this profile?')) return;
  await api(`/api/profiles/${id}`, { method: 'DELETE' });
  state.profiles = await api('/api/profiles');
  $('#profile-form').dataset.id = '';
  renderProfile();
}

// --- size charts ------------------------------------------------------------------

function renderCharts() {
  const byBrand = {};
  for (const c of state.charts) (byBrand[c.brand] ??= []).push(c);
  $('#chart-list').innerHTML = Object.entries(byBrand).map(([brand, charts]) => `
    <div class="card brand">
      <h3>${esc(brand)}</h3>
      <div class="chips">${charts.map(c => `
        <button class="chip" data-chart="${c.id}">
          ${esc(state.meta.sections[c.section])} · ${esc(state.meta.garments[c.garment]?.label ?? c.garment)}
          <span class="muted">${c.sizes.length} sizes</span>
        </button>`).join('')}</div>
      ${charts[0].notes ? `<p class="muted">${esc(charts[0].notes)}</p>` : ''}
    </div>`).join('') || '<p class="hint">No size charts yet.</p>';
}

function chartColumns() {
  return $$('#chart-columns input:checked').map(cb => cb.value);
}

function renderColumnPicker(selected) {
  $('#chart-columns').innerHTML = Object.entries(state.meta.measurements)
    .filter(([k]) => k !== 'inseam' || selected.includes('inseam'))
    .map(([k, m]) => `<label class="check"><input type="checkbox" value="${k}"${selected.includes(k) ? ' checked' : ''}> ${esc(m.label)}</label>`)
    .join('');
}

function sizeRow(size, cols) {
  return `<tr>
    <td><input class="size-label" value="${esc(size?.label ?? '')}" placeholder="M"></td>
    ${cols.map(k => `<td><input data-m="${k}" ${cellAttrs(size?.ranges?.[k])} placeholder="–"></td>`).join('')}
    <td><button type="button" class="remove" title="Remove">×</button></td>
  </tr>`;
}

function lengthRow(len) {
  return `<tr>
    <td><input class="len-label" value="${esc(len?.label ?? '')}" placeholder="Regular"></td>
    <td><input class="len-inseam" ${cellAttrs(len?.inseam)} placeholder="76-81"></td>
    <td><button type="button" class="remove" title="Remove">×</button></td>
  </tr>`;
}

// Read the size table as it stands, so changing columns keeps typed values.
function readSizes({ strict }) {
  return $$('#sizes-body tr').map(tr => {
    const ranges = {};
    $$('[data-m]', tr).forEach(input => {
      try {
        const v = readCell(input);
        if (v != null) ranges[input.dataset.m] = v;
      } catch (err) { if (strict) throw err; }
    });
    return { label: $('.size-label', tr).value.trim(), ranges };
  }).filter(s => !strict || s.label || Object.keys(s.ranges).length);
}

function renderSizeTable(sizes) {
  const cols = chartColumns();
  $('#sizes-head').innerHTML = `<tr><th>Size</th>${cols.map(k => `<th>${esc(label(k))}</th>`).join('')}<th></th></tr>`;
  $('#sizes-body').innerHTML = sizes.map(s => sizeRow(s, cols)).join('');
}

function openChart(chart) {
  state.editingChart = chart;
  const form = $('#chart-form');
  fillSelect($('#chart-garment'), Object.entries(state.meta.garments).map(([k, g]) => [k, g.label]), chart?.garment ?? 'tops');
  form.brand.value = chart?.brand ?? '';
  form.section.value = chart?.section ?? (state.profiles[0]?.sections?.[0] || 'womens');
  form.notes.value = chart?.notes ?? '';
  form.source_url.value = chart?.source_url ?? '';

  const garment = form.garment.value;
  const used = chart ? [...new Set(chart.sizes.flatMap(s => Object.keys(s.ranges)))] : null;
  renderColumnPicker(used ?? state.meta.garments[garment].measurements.filter(k => k !== 'sleeve' && k !== 'neck'));
  renderSizeTable(chart?.sizes ?? [{}, {}, {}]);
  $('#lengths-body').innerHTML = (chart?.lengths ?? []).map(lengthRow).join('');

  $('#chart-title').textContent = chart ? `Edit ${chart.brand}` : 'New size chart';
  $('#chart-delete').hidden = !chart;
  $('#chart-error').hidden = true;
  $('#chart-dialog').showModal();
}

async function saveChart(e) {
  e.preventDefault();
  const form = e.target;
  const error = $('#chart-error');
  try {
    const sizes = readSizes({ strict: true });
    if (sizes.some(s => !s.label)) throw new Error('Every size needs a label.');
    const lengths = $$('#lengths-body tr').map(tr => ({
      label: $('.len-label', tr).value.trim(),
      inseam: readCell($('.len-inseam', tr)),
    })).filter(l => l.label || l.inseam != null);
    if (lengths.some(l => !l.label || l.inseam == null)) throw new Error('Each length needs a label and an inside-leg value.');

    const body = {
      brand: form.brand.value.trim(), section: form.section.value, garment: form.garment.value,
      notes: form.notes.value.trim(), source_url: form.source_url.value.trim(), sizes, lengths,
    };
    const id = state.editingChart?.id;
    await (id ? api(`/api/charts/${id}`, { method: 'PUT', body }) : api('/api/charts', { method: 'POST', body }));
    state.charts = await api('/api/charts');
    $('#chart-dialog').close();
    renderCharts();
  } catch (err) {
    error.textContent = err.message;
    error.hidden = false;
  }
}

async function deleteChart() {
  const chart = state.editingChart;
  if (!chart || !confirm(`Delete the ${chart.brand} chart?`)) return;
  await api(`/api/charts/${chart.id}`, { method: 'DELETE' });
  state.charts = await api('/api/charts');
  $('#chart-dialog').close();
  renderCharts();
}

// --- wiring -------------------------------------------------------------------------

function wire() {
  $$('nav button').forEach(b => b.addEventListener('click', () => show(b.dataset.view)));
  $$('.units button').forEach(b => b.addEventListener('click', () => setUnit(b.dataset.unit)));
  document.addEventListener('click', e => {
    const link = e.target.closest('[data-goto]');
    if (link) { e.preventDefault(); show(link.dataset.goto); }
  });

  ['#find-profile', '#find-garment', '#find-fit'].forEach(s => $(s).addEventListener('change', renderFind));

  $('#profile-select').addEventListener('change', e => {
    loadProfileForm(state.profiles.find(p => String(p.id) === e.target.value));
  });
  $('#profile-new').addEventListener('click', () => {
    loadProfileForm(null);
    const sel = $('#profile-select');
    sel.add(new Option('New profile', '', true, true));
    $('#profile-form').name.focus();
  });
  $('#profile-form').addEventListener('submit', saveProfile);
  $('#profile-delete').addEventListener('click', deleteProfile);

  $('#chart-new').addEventListener('click', () => openChart(null));
  $('#chart-list').addEventListener('click', e => {
    const chip = e.target.closest('[data-chart]');
    if (chip) openChart(state.charts.find(c => String(c.id) === chip.dataset.chart));
  });
  $('#chart-columns').addEventListener('change', () => renderSizeTable(readSizes({ strict: false })));
  $('#chart-garment').addEventListener('change', e => {
    if (state.editingChart) return; // keep an existing chart's columns
    renderColumnPicker(state.meta.garments[e.target.value].measurements.filter(k => k !== 'sleeve' && k !== 'neck'));
    renderSizeTable(readSizes({ strict: false }));
  });
  $('#size-add').addEventListener('click', () => {
    $('#sizes-body').insertAdjacentHTML('beforeend', sizeRow(null, chartColumns()));
  });
  $('#length-add').addEventListener('click', () => {
    $('#lengths-body').insertAdjacentHTML('beforeend', lengthRow(null));
  });
  $('#chart-dialog').addEventListener('click', e => {
    if (e.target.classList.contains('remove')) e.target.closest('tr').remove();
  });
  $('#chart-form').addEventListener('submit', saveChart);
  $('#chart-cancel').addEventListener('click', () => $('#chart-dialog').close());
  $('#chart-delete').addEventListener('click', deleteChart);
}

async function init() {
  [state.meta, state.profiles, state.charts] = await Promise.all([
    api('/api/meta'), api('/api/profiles'), api('/api/charts'),
  ]);
  wire();
  setUnit(state.unit);
  show(state.profiles.length ? 'find' : 'profile');
}

init();
