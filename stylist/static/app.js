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
// Body measurements show to ½ cm / ¼ in; feet need millimetres (a shoe size is ~4 mm).
const FINE = new Set(['foot_length']);
const fmt = (cm, fine = false) => {
  const v = toDisplay(cm);
  const steps = fine ? (state.unit === 'in' ? 100 : 10) : (state.unit === 'in' ? 4 : 2);
  return String(Math.round(v * steps) / steps);
};
const fmtRange = (r, fine = false) => Array.isArray(r)
  ? (r[0] === r[1] ? fmt(r[0], fine) : `${fmt(r[0], fine)}–${fmt(r[1], fine)}`)
  : fmt(r, fine);

// "86-91", "86–91", "86 to 91" or "86" → [lo, hi] / number, in cm. Empty → null.
// Read a range cell, keeping the stored value if the displayed text is unchanged.
function readCell(input) {
  const stored = input.dataset.cm ? JSON.parse(input.dataset.cm) : null;
  if (stored != null && input.value === fmtRange(stored, FINE.has(input.dataset.m))) return stored;
  return parseRange(input.value);
}

const cellAttrs = (v, fine = false) => v != null ? `value="${fmtRange(v, fine)}" data-cm="${esc(JSON.stringify(v))}"` : '';

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
  if (view === 'colour') renderColour();
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
    const hasAny = Object.keys(profile?.usual_sizes || {}).length > 0
      || (profile?.mode === 'detailed' && Object.keys(profile?.measurements || {}).length > 0);
    empty.innerHTML = hasAny
      ? `No size charts cover ${esc(state.meta.garments[garmentSel.value].label.toLowerCase())} with the sizes you've given.
         <a href="#" data-goto="charts">Add a size chart</a> or <a href="#" data-goto="profile">add to your profile</a>.`
      : 'Your profile has no sizes yet. <a href="#" data-goto="profile">Add your usual sizes or measurements</a>.';
  }
  out.innerHTML = results.map(resultCard).join('');
}

const VERDICT = { great: 'Great fit', good: 'Good fit', poor: 'Poor fit' };

function detailList(details) {
  return `<ul class="details">${details.map(d => `
    <li class="st-${d.status}"><span>${esc(d.label)}</span>
      <span class="muted">you ${d.estimated_from ? '~' : ''}${fmt(d.body, FINE.has(d.measurement))}${d.estimated_from ? ' (est.)' : ''} · size ${fmtRange(d.range, FINE.has(d.measurement))}</span>
      <b>${esc(d.note)}</b></li>`).join('')}</ul>`;
}

// "UK" + "12" → prefix shown small before the size; letters and W sizes stand alone.
const SIZE_PREFIX = { UK: 'UK', EU: 'EU', US: 'US' };

function equivalentsText(eq) {
  return Object.entries(eq || {}).map(([sys, v]) => {
    if (sys === 'Letter') return v;
    if (sys === 'W') return `W${v}`;
    if (sys === 'cm') return `${fmt(Number(v), true)} ${state.unit} foot`;
    return `${sys} ${v}`;
  }).join(' · ');
}

function resultCard(r) {
  const prefix = SIZE_PREFIX[r.size_system] && !r.size.toUpperCase().startsWith(r.size_system)
    ? `<span class="sys">${SIZE_PREFIX[r.size_system]}</span>` : '';
  const length = r.length ? ` <span class="length">${esc(r.length.label)} leg</span>` : '';
  const eq = equivalentsText(r.equivalents);
  const alt = r.alternative
    ? `<p class="alt">Between sizes — <b>${esc(r.alternative.size)}</b>
        ${r.alternative.equivalents && Object.keys(r.alternative.equivalents).length ? `<span class="muted">(${esc(equivalentsText(r.alternative.equivalents))})</span>` : ''}
        also works:</p>${detailList(r.alternative.details)}`
    : '';
  const lengthNote = r.length && r.length.status !== 'good'
    ? `<p class="muted">Leg length: ${esc(r.length.note)}</p>` : '';
  const sources = [...new Set([...r.details.map(d => d.estimated_from), r.length?.estimated_from].filter(Boolean))];
  const estimate = sources.length
    ? `<p class="estimate">Estimated from ${esc(sources.join(', '))}. Add measurements for a closer match.</p>` : '';
  return `<article class="card result v-${r.verdict}">
    <header>
      <div><h3>${esc(r.brand)}</h3><span class="muted">${esc(state.meta.sections[r.section] || '')}</span></div>
      <div class="size"><span class="big">${prefix}${esc(r.size)}</span>${length}</div>
    </header>
    ${eq ? `<p class="equivalents">${esc(eq)}</p>` : ''}
    <span class="badge">${VERDICT[r.verdict]}</span>
    ${detailList(r.details)}${lengthNote}${alt}${estimate}
  </article>`;
}

// --- profile ------------------------------------------------------------------------

// Measurements that only make sense for one section's clothing.
const GENDER_ONLY = { underbust: 'female' };

function currentGender() {
  return $('#profile-form [name="gender"]:checked')?.value || 'female';
}

function renderMeasureGrid(values = {}) {
  const gender = currentGender();
  $('#measure-grid').innerHTML = Object.entries(state.meta.measurements).map(([key, m]) => `
    <label${GENDER_ONLY[key] && GENDER_ONLY[key] !== gender ? ' hidden' : ''}>${esc(m.label)}
      <input type="number" step="any" min="0" name="m-${key}"
        value="${values[key] != null ? fmt(values[key], FINE.has(key)) : ''}" data-cm="${values[key] ?? ''}">
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
    out[key] = cm && input.value === fmt(Number(cm), FINE.has(key))
      ? Number(cm)
      : Math.round(fromDisplay(Number(input.value)) * 10) / 10;
  }
  return out;
}

const SYSTEM_SHORT = { UK: 'UK', EU: 'EU', US: 'US', Letter: 'S/M/L', W: 'Waist (W)' };

function sizeSelectOptions(gender, cat, system, selected) {
  const labels = state.meta.size_options[gender][cat][system] || [];
  const show = v => system === 'W' ? `W${v}` : v;
  return ['<option value="">—</option>', ...labels.map(v =>
    `<option value="${esc(v)}"${v === selected ? ' selected' : ''}>${esc(show(v))}</option>`)].join('');
}

function renderUsualGrid(usual = {}) {
  const gender = currentGender();
  const options = state.meta.size_options[gender];
  $('#usual-grid').innerHTML = Object.keys(options).map(cat => {
    const entry = usual[cat] || {};
    const systems = Object.keys(options[cat]);
    const system = systems.includes(entry.system) ? entry.system : systems[0];
    const lengths = cat === 'bottoms' ? state.meta.lengths[gender] : null;
    return `<div class="usual-row" data-cat="${cat}">
      <span class="usual-label">${esc(state.meta.usual_categories[cat])}</span>
      <div class="segmented small">${systems.map(sys => `
        <label><input type="radio" name="sys-${cat}" value="${sys}"${sys === system ? ' checked' : ''}> ${esc(SYSTEM_SHORT[sys] || sys)}</label>`).join('')}
      </div>
      <select class="usual-size" aria-label="${esc(state.meta.usual_categories[cat])} size">
        ${sizeSelectOptions(gender, cat, system, entry.system === system ? entry.size : '')}</select>
      ${lengths ? `<select class="usual-length" aria-label="Leg length">
        <option value="">Leg length</option>
        ${lengths.map(l => `<option value="${esc(l)}"${l === entry.length ? ' selected' : ''}>${esc(/^\d/.test(l) ? `L${l}` : l)}</option>`).join('')}
      </select>` : ''}
    </div>`;
  }).join('');
}

function readUsual() {
  const out = {};
  $$('#usual-grid .usual-row').forEach(row => {
    const size = $('.usual-size', row).value;
    if (!size) return;
    const entry = { system: $('input[type=radio]:checked', row).value, size };
    const length = $('.usual-length', row)?.value;
    if (length) entry.length = length;
    out[row.dataset.cat] = entry;
  });
  return out;
}

function syncProfileForm() {
  const form = $('#profile-form');
  const gender = currentGender();
  $('#also-other-label').textContent = gender === 'female' ? "Also show men's clothing" : "Also show women's clothing";
  const detailed = form.querySelector('[name="mode"]:checked')?.value === 'detailed';
  $('#detailed-fields').hidden = !detailed;
  $('#quick-fields legend').textContent = detailed
    ? 'Usual sizes (optional, used for anything you haven\'t measured)' : 'Usual sizes';
}

function loadProfileForm(profile) {
  const form = $('#profile-form');
  form.dataset.id = profile?.id ?? '';
  form.name.value = profile?.name ?? '';
  form.fit.value = profile?.fit ?? 'regular';
  const gender = profile?.gender ?? 'female';
  $$('[name="gender"]', form).forEach(r => { r.checked = r.value === gender; });
  $$('[name="mode"]', form).forEach(r => { r.checked = r.value === (profile?.mode ?? 'quick'); });
  const other = gender === 'female' ? 'mens' : 'womens';
  form['also-other'].checked = (profile?.sections ?? []).includes(other);
  renderUsualGrid(profile?.usual_sizes);
  renderMeasureGrid(profile?.measurements);
  syncProfileForm();
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
  const gender = currentGender();
  const [own, other] = gender === 'female' ? ['womens', 'mens'] : ['mens', 'womens'];
  const body = {
    name: form.name.value.trim(),
    gender,
    sections: [own, 'unisex', ...(form['also-other'].checked ? [other] : [])],
    fit: form.fit.value,
    mode: $('[name="mode"]:checked', form).value,
    usual_sizes: readUsual(),
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
          ${c.size_system !== 'Other' ? `· ${esc(SYSTEM_SHORT[c.size_system] || c.size_system)}` : ''}
          <span class="muted">${c.sizes.length} sizes</span>
        </button>`).join('')}</div>
      ${charts[0].notes ? `<p class="muted">${esc(charts[0].notes)}</p>` : ''}
    </div>`).join('') || '<p class="hint">No size charts yet.</p>';
}

function chartColumns() {
  return $$('#chart-columns input:checked').map(cb => cb.value);
}

// Sensible starting columns for a new chart of this garment type.
function defaultColumns(garment) {
  return state.meta.garments[garment].measurements.filter(k => k !== 'sleeve' && k !== 'neck');
}

// Most brands label sizes this way for this section and garment.
function defaultSystem(section, garment) {
  if (garment === 'shoes' || section === 'womens') return 'UK';
  if (section === 'mens') return garment === 'bottoms' ? 'W' : 'Letter';
  return 'Letter';
}

function renderColumnPicker(selected, garment) {
  // Inside leg lives in the Lengths table and foot length only suits shoes,
  // so both are offered only where they belong (or if a chart already uses them).
  $('#chart-columns').innerHTML = Object.entries(state.meta.measurements)
    .filter(([k]) => k !== 'inseam' || selected.includes('inseam'))
    .filter(([k]) => (k === 'foot_length') === (garment === 'shoes') || selected.includes(k))
    .map(([k, m]) => `<label class="check"><input type="checkbox" value="${k}"${selected.includes(k) ? ' checked' : ''}> ${esc(m.label)}</label>`)
    .join('');
}

function sizeRow(size, cols) {
  return `<tr>
    <td><input class="size-label" value="${esc(size?.label ?? '')}" placeholder="M"></td>
    ${cols.map(k => `<td><input data-m="${k}" ${cellAttrs(size?.ranges?.[k], FINE.has(k))} placeholder="–"></td>`).join('')}
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
  fillSelect($('#chart-system'), Object.entries(state.meta.size_systems),
    chart?.size_system ?? defaultSystem(form.section.value, form.garment.value));
  form.notes.value = chart?.notes ?? '';
  form.source_url.value = chart?.source_url ?? '';

  const garment = form.garment.value;
  const used = chart ? [...new Set(chart.sizes.flatMap(s => Object.keys(s.ranges)))] : null;
  renderColumnPicker(used ?? defaultColumns(garment), garment);
  renderSizeTable(chart?.sizes ?? [{}, {}, {}]);
  $('#lengths-body').innerHTML = (chart?.lengths ?? []).map(lengthRow).join('');
  $('#lengths-block').hidden = garment === 'shoes';

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
      size_system: form.size_system.value, notes: form.notes.value.trim(), source_url: form.source_url.value.trim(), sizes, lengths,
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
  $('#profile-form').addEventListener('change', e => {
    if (e.target.name === 'gender') {
      // Size systems differ between sections, so rebuild the usual-size rows.
      const pendingMeasurements = readMeasurements();
      renderUsualGrid({});
      renderMeasureGrid(pendingMeasurements);
    }
    if (e.target.name?.startsWith('sys-')) {
      const row = e.target.closest('.usual-row');
      const size = $('.usual-size', row);
      size.innerHTML = sizeSelectOptions(currentGender(), row.dataset.cat, e.target.value, size.value);
    }
    syncProfileForm();
  });
  $('#chart-garment').addEventListener('change', e => {
    const garment = e.target.value;
    $('#lengths-block').hidden = garment === 'shoes';
    if (state.editingChart) return; // keep an existing chart's columns and labels
    renderColumnPicker(defaultColumns(garment), garment);
    renderSizeTable(readSizes({ strict: false }));
    $('#chart-system').value = defaultSystem($('#chart-form').section.value, garment);
  });
  $('#chart-form').section.addEventListener('change', e => {
    if (!state.editingChart) $('#chart-system').value = defaultSystem(e.target.value, $('#chart-garment').value);
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
