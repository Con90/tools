// Style tab: body-shape guide, colouring tips, preferences and the Claude brief.
// Uses helpers from app.js ($, $$, api, esc, fillSelect, state).

const styleState = { guide: null, busy: false, error: '' };

// Opus 5 list prices, $ per million tokens: for showing what a brief cost.
const PRICE_IN = 5, PRICE_OUT = 25;

async function renderStyle() {
  const sel = $('#style-profile');
  fillSelect(sel, state.profiles.map(p => [p.id, p.name]), sel.value || state.profiles[0]?.id);
  if (!state.profiles.length) {
    $('#style-content').innerHTML = '<p class="hint">First <a href="#" data-goto="profile">create a profile</a>.</p>';
    return;
  }
  styleState.guide = await api(`/api/profiles/${sel.value}/style`);
  styleState.error = '';
  drawStyle();
}

function list(items) {
  return `<ul>${items.map(i => `<li>${esc(i)}</li>`).join('')}</ul>`;
}

function chips(name, options, selected) {
  return `<div class="chip-picks">${options.map(o => `
    <label class="pick"><input type="checkbox" name="${name}" value="${esc(o)}"${selected.includes(o) ? ' checked' : ''}>${esc(o)}</label>`).join('')}</div>`;
}

function shapeCard(g) {
  const s = g.shape;
  const picker = `<label class="inline-select">${s ? 'Not right? ' : ''}Choose your shape
    <select id="shape-override"><option value="">${g.auto_shape ? `Use my measurements (${esc(g.shape_options[g.auto_shape])})` : 'Work it out from my sizes'}</option>
    ${Object.entries(g.shape_options).map(([k, v]) => `<option value="${k}"${s?.overridden && s.key === k ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>`;
  if (!s) {
    return `<section class="card"><h2>Your shape</h2>
      <p class="hint">Add your chest, waist and hips (or your usual top and trouser sizes) on
        <a href="#" data-goto="profile">My profile</a> to get shape-based advice.</p>${picker}</section>`;
  }
  const badge = s.overridden ? 'set by you' : s.estimated ? 'estimated from your usual sizes' : 'from your measurements';
  return `<section class="card shape-card">
    <p class="eyebrow">Your shape · ${badge}</p>
    <h2>${esc(s.name)}${s.variant ? ` <span class="muted">${esc(s.variant)}</span>` : ''}</h2>
    <p>${esc(s.summary)}</p>
    <p class="goal"><b>The idea:</b> ${esc(s.goal)}</p>
    <div class="two-col">
      <div><h3>Look for</h3>${list(s.wear)}</div>
      <div><h3>Harder to wear</h3>${list(s.avoid)}</div>
    </div>
    ${g.proportion_tips.length ? `<h3>Proportions</h3>${list(g.proportion_tips)}` : ''}
    ${picker}
  </section>`;
}

function colourCard(g) {
  if (!g.colour_tips.length) {
    return `<section class="card"><h2>Your colouring</h2>
      <p class="hint">Add photos in <a href="#" data-goto="colour">Colours</a> for advice on contrast, fabrics and prints.</p></section>`;
  }
  return `<section class="card"><h2>Your colouring</h2>
    ${g.contrast ? `<p class="eyebrow">${esc(g.contrast)} contrast</p>` : ''}
    ${list(g.colour_tips)}</section>`;
}

function prefsCard(g) {
  const p = g.preferences || {};
  return `<section class="card">
    <h2>About you</h2>
    <p class="hint">This shapes the personal brief below.</p>
    <form id="prefs-form">
      <h3>Your week involves</h3>${chips('lifestyle', g.options.lifestyle, p.lifestyle || [])}
      <h3>Style words you like</h3>${chips('vibes', g.options.vibes, p.vibes || [])}
      <div class="row">
        <label>Budget <select name="budget"><option value="">—</option>
          ${g.options.budget.map(b => `<option${p.budget === b ? ' selected' : ''}>${esc(b)}</option>`).join('')}</select></label>
      </div>
      <div class="row">
        <label>Pieces you love wearing <input name="loves" maxlength="500" value="${esc(p.loves || '')}" placeholder="e.g. wide-leg trousers, denim jackets"></label>
        <label>Won't wear / dislikes <input name="dislikes" maxlength="500" value="${esc(p.dislikes || '')}" placeholder="e.g. anything cropped, heels"></label>
      </div>
      <label>Anything else <input name="notes" maxlength="1000" value="${esc(p.notes || '')}" placeholder="e.g. need outfits for a new job; I cycle to work"></label>
      <div class="actions"><button type="submit">Save</button><span id="prefs-status" class="status"></span></div>
    </form>
  </section>`;
}

function readPrefs() {
  const f = $('#prefs-form');
  return {
    lifestyle: $$('[name="lifestyle"]:checked', f).map(c => c.value),
    vibes: $$('[name="vibes"]:checked', f).map(c => c.value),
    budget: f.budget.value || null,
    loves: f.loves.value.trim(), dislikes: f.dislikes.value.trim(), notes: f.notes.value.trim(),
  };
}

function dot(hex) {
  return hex ? `<i class="dot" style="background:${hex}"></i>` : '<i class="dot missing"></i>';
}

function briefHtml(result) {
  const b = result.brief;
  const cost = (result.usage.input_tokens * PRICE_IN + result.usage.output_tokens * PRICE_OUT) / 1e6;
  const shopUrl = q => `https://www.google.com/search?tbm=shop&q=${encodeURIComponent(q)}`;
  return `<div class="brief">
    <h2>${esc(b.headline)}</h2>
    <p>${esc(b.summary)}</p>

    <h3>Style directions</h3>
    <div class="directions">${b.directions.map(d => `
      <article class="direction"><h4>${esc(d.name)}</h4><p>${esc(d.description)}</p>
        <p class="muted">${esc(d.why_it_suits_you)}</p>
        <p><b>Signature pieces</b></p>${list(d.signature_pieces)}
        ${d.avoid.length ? `<p><b>Skip</b></p>${list(d.avoid)}` : ''}</article>`).join('')}</div>

    <h3>Outfit formulas</h3>
    <div class="outfits">${b.outfits.map(o => `
      <article class="outfit"><p class="eyebrow">${esc(o.occasion)}</p><h4>${esc(o.name)}</h4>
        <ul class="pieces">${o.pieces.map(p => `<li>${dot(p.colour_hex)}${esc(p.item)} <span class="muted">${esc(p.colour_name)}</span></li>`).join('')}</ul>
        <p class="muted">${esc(o.styling_note)}</p></article>`).join('')}</div>

    <h3>Shopping list</h3>
    <ol class="shopping">${b.shopping_list.map(i => `
      <li>${dot(i.colour_hex)}<div><b>${esc(i.item)}</b> <span class="muted">${esc(i.colour_name)}</span>
        <p class="muted">${esc(i.why)}</p></div>
        <span class="search-links"><button type="button" class="small" data-find="${esc(i.search_query)}" data-garment="${esc(i.category)}">Find</button>
        <a class="search" href="${shopUrl(i.search_query)}" target="_blank" rel="noopener" title="Search Google Shopping: ${esc(i.search_query)}">Google</a></span></li>`).join('')}</ol>

    <h3>Fit notes</h3>${list(b.fit_notes)}
    <p class="muted small-print">Written by ${esc(result.model)} on ${esc(new Date(result.created_at).toLocaleString())}
      ${result.photo_included ? 'with your photo' : 'without a photo'} · about $${cost.toFixed(2)}</p>
  </div>`;
}

function briefCard(g) {
  const key = g.api;
  const keyForm = `<form id="key-form" class="key-form">
      <label>Anthropic API key <input name="key" type="password" autocomplete="off" placeholder="sk-ant-…"></label>
      <button type="submit" class="secondary">Save key</button>
      ${key.source === 'saved in the app' ? '<button type="button" class="link" id="key-remove">Remove saved key</button>' : ''}
    </form>
    <p class="muted small-print">Get a key at <a href="https://console.anthropic.com/settings/keys" target="_blank" rel="noopener">console.anthropic.com</a>.
      It's saved only on this computer (<code>data/settings.json</code>). You can also set <code>ANTHROPIC_API_KEY</code> before running the app.</p>`;
  return `<section class="card brief-card">
    <h2>Personal style brief <span class="muted">by Claude</span></h2>
    <p class="hint">Claude turns everything above into style directions, outfit formulas in your palette and a
      shopping list. It's sent your shape, proportions, colour season and what you told us (not your raw
      measurements), plus a photo only if you tick the box. Each brief costs roughly $0.10–0.20 on your API key.</p>
    ${key.configured ? `<p class="muted">API key: ${esc(key.source)}. <button type="button" class="link" id="key-change">Change</button></p>
      <div id="key-edit" hidden>${keyForm}</div>` : keyForm}
    <div class="actions">
      <label class="check"><input type="checkbox" id="brief-photo"${g.has_photo ? '' : ' disabled'}>
        Include a photo${g.has_photo ? '' : ' <span class="muted">(add one in Colours first)</span>'}</label>
      <button type="button" id="brief-go"${styleState.busy ? ' disabled' : ''}>${styleState.busy ? 'Writing your brief…' : g.brief ? 'Write a new brief' : 'Write my brief'}</button>
      <span class="status">${styleState.busy ? 'This can take up to a minute.' : ''}</span>
    </div>
    ${styleState.error ? `<p class="error">${esc(styleState.error)}</p>` : ''}
    ${g.brief ? briefHtml(g.brief) : ''}
  </section>`;
}

function drawStyle() {
  const g = styleState.guide;
  $('#style-content').innerHTML = `<div class="style-grid">${shapeCard(g)}${colourCard(g)}</div>${prefsCard(g)}${briefCard(g)}`;
}

async function saveStyle(changes = {}) {
  const g = styleState.guide;
  const body = {
    preferences: $('#prefs-form') ? readPrefs() : g.preferences,
    shape_override: $('#shape-override')?.value || null,
    ...changes,
  };
  styleState.guide = await api(`/api/profiles/${$('#style-profile').value}/style`, { method: 'PUT', body });
}

function wireStyle() {
  $('#style-profile').addEventListener('change', renderStyle);
  const root = $('#view-style');
  root.addEventListener('change', async e => {
    if (e.target.id === 'shape-override') { await saveStyle(); drawStyle(); }
  });
  root.addEventListener('submit', async e => {
    e.preventDefault();
    if (e.target.id === 'prefs-form') {
      await saveStyle();
      drawStyle();
      $('#prefs-status').textContent = 'Saved.';
    }
    if (e.target.id === 'key-form') {
      try {
        await api('/api/settings/anthropic-key', { method: 'PUT', body: { key: e.target.key.value } });
        styleState.error = '';
      } catch (err) { styleState.error = err.message; }
      await saveStyle();  // keep unsaved preference edits
      drawStyle();
    }
  });
  root.addEventListener('click', async e => {
    if (e.target.dataset.find) {
      shopSearchFor(e.target.dataset.find, e.target.dataset.garment, $('#style-profile').value);
      return;
    }
    if (e.target.id === 'key-change') $('#key-edit').hidden = false;
    if (e.target.id === 'key-remove') {
      await api('/api/settings/anthropic-key', { method: 'PUT', body: { key: null } });
      await saveStyle(); drawStyle();
    }
    if (e.target.id === 'brief-go') {
      const includePhoto = $('#brief-photo').checked;
      await saveStyle();  // the brief uses the latest preferences
      styleState.busy = true; styleState.error = '';
      drawStyle();
      try {
        styleState.guide = await api(`/api/profiles/${$('#style-profile').value}/style/brief`,
          { method: 'POST', body: { include_photo: includePhoto } });
      } catch (err) {
        styleState.error = err.message;
      }
      styleState.busy = false;
      drawStyle();
    }
  });
}

wireStyle();
