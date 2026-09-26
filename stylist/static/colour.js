// Colours tab: photo upload, sample adjustment, season result and palette.
// Uses the helpers defined in app.js ($, $$, api, esc, fillSelect, state).

const colourState = { photos: [], summary: null, seasons: null, preview: null, editing: null };

const FEATURE_LABELS = { skin: 'Skin', hair: 'Hair', eyes: 'Eyes', white: 'White' };

async function renderColour() {
  if (!colourState.seasons) colourState.seasons = await api('/api/seasons');
  const sel = $('#colour-profile');
  fillSelect(sel, state.profiles.map(p => [p.id, p.name]), sel.value || state.profiles[0]?.id);
  const hasProfile = state.profiles.length > 0;
  $('#drop').hidden = !hasProfile;
  if (!hasProfile) {
    $('#colour-empty').hidden = false;
    $('#colour-empty').innerHTML = '<h2>Find your colours</h2><p>First <a href="#" data-goto="profile">create a profile</a>, then add photos here.</p>';
    $('#colour-result').innerHTML = $('#photo-grid').innerHTML = '';
    return;
  }
  await loadColour();
}

async function loadColour() {
  const pid = $('#colour-profile').value;
  [colourState.photos, colourState.summary] = await Promise.all([
    api(`/api/profiles/${pid}/photos`), api(`/api/profiles/${pid}/colour`),
  ]);
  colourState.preview = null;
  drawColour();
}

function drawColour() {
  const { photos, summary } = colourState;
  $('#colour-empty').hidden = photos.length > 0;
  $('#photos-heading').hidden = !photos.length;
  $('#colour-result').innerHTML = summary?.season ? resultHtml(summary) : '';
  $('#photo-grid').innerHTML = photos.map(photoCard).join('');
}

// --- result ------------------------------------------------------------------------------

function swatch(hex, { avoid = false, big = false } = {}) {
  return `<button type="button" class="swatch${avoid ? ' avoid' : ''}${big ? ' big' : ''}" style="--c:${hex}"
    title="${hex}: click to copy" data-copy="${hex}"><span>${hex}</span></button>`;
}

function axisBar(value, left, right) {
  const pct = Math.round((value + 1) * 50);
  return `<div class="axis"><span>${left}</span>
    <div class="axis-track"><i style="left:${pct}%"></i></div><span>${right}</span></div>`;
}

function resultHtml(s) {
  const seasons = colourState.seasons.seasons;
  const shown = colourState.preview || s.season;
  const p = { key: shown, ...seasons[shown] };
  const isOverride = s.settings?.season_override;
  const previewing = colourState.preview && colourState.preview !== s.season;

  const features = ['skin', 'hair', 'eyes'].map(f => {
    const c = s.features[f];
    return `<div class="feature">${c ? `<i style="background:${c.hex}"></i>` : '<i class="missing"></i>'}
      <span>${FEATURE_LABELS[f]}</span><span class="muted">${c ? (c.source.startsWith('natural') ? 'set by you' : c.hex) : 'not found'}</span></div>`;
  }).join('');

  const matches = (s.ranked || []).map(r => `
    <button type="button" class="match${r.season === shown ? ' active' : ''}" data-preview="${r.season}">
      ${esc(r.name)} <b>${r.match}%</b></button>`).join('');

  const hairOptions = Object.entries(colourState.seasons.natural_hair);
  const seasonOptions = Object.entries(seasons).map(([k, v]) => [k, v.name]);

  return `
  <section class="card season-card">
    <div class="season-head">
      <div>
        <p class="eyebrow">${previewing ? 'Previewing' : isOverride ? 'Your season (set by you)' : 'Your season'}</p>
        <h2>${esc(p.name)}</h2>
        <p>${esc(p.summary)}</p>
        ${previewing ? `<button type="button" class="small" data-set-season="${shown}">Make this my season</button>
          <button type="button" class="small secondary" data-preview="${s.season}">Back to ${esc(seasons[s.season].name)}</button>` : ''}
      </div>
      <div class="features">${features}</div>
    </div>

    ${s.scores ? `<div class="axes">
      ${axisBar(s.scores.warmth, 'Cool', 'Warm')}
      ${axisBar(s.scores.depth, 'Light', 'Deep')}
      ${axisBar(s.scores.clarity, 'Soft', 'Bright')}
      <p class="muted">Measured: ${esc(s.words.join(', '))}, from ${s.photos} photo${s.photos === 1 ? '' : 's'}.</p>
    </div>
    <div class="matches"><span class="muted">Closest seasons:</span>${matches}</div>` : ''}

    <details class="settings">
      <summary>Adjust</summary>
      <div class="row">
        <label>My natural hair colour (if dyed or hidden)
          <select id="natural-hair"><option value="">Use my photos</option>
          ${hairOptions.map(([k, v]) => `<option value="${k}"${s.settings?.natural_hair === k ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select>
        </label>
        <label>I already know my season
          <select id="season-override"><option value="">Use the analysis${s.auto_season ? ` (${esc(seasons[s.auto_season].name)})` : ''}</option>
          ${seasonOptions.map(([k, v]) => `<option value="${k}"${isOverride === k ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select>
        </label>
      </div>
    </details>
  </section>

  <section class="card palette">
    <h3>Best neutrals <span class="muted">(wardrobe basics)</span></h3>
    <div class="swatches">${p.neutrals.map(h => swatch(h)).join('')}</div>
    <h3>Your colours</h3>
    <div class="swatches">${p.colours.map(h => swatch(h)).join('')}</div>
    <h3>Statement accents</h3>
    <div class="swatches">${p.accents.map(h => swatch(h, { big: true })).join('')}</div>
    <h3>Harder to wear</h3>
    <div class="swatches">${p.avoid.map(h => swatch(h, { avoid: true })).join('')}</div>
    <div class="palette-notes">
      <p><b>Metals:</b> ${esc(p.metals)}</p>
      <p><b>Tip:</b> ${esc(p.tips)}</p>
    </div>
  </section>

  ${compareHtml(s)}`;
}

// Face crops over each candidate season's colours: the human way to decide
// between two close seasons is to see which colours make the face look clearer.
function compareHtml(s) {
  const photo = colourState.photos.find(ph => ph.included && ph.face_box);
  if (!photo || !s.ranked || s.ranked.length < 2) return '';
  const seasons = colourState.seasons.seasons;
  const candidates = [...new Set([s.season, ...s.ranked.slice(0, 2).map(r => r.season)])].slice(0, 2);
  const face = `/api/photos/${photo.id}/face?size=240`;
  return `<section class="card compare">
    <h3>Compare side by side</h3>
    <p class="hint">Which row makes your skin look more even and your eyes brighter, without shadows or
      a grey or yellow cast? That's usually the better season.</p>
    ${candidates.map(key => {
      const p = seasons[key];
      const picks = [p.colours[1], p.colours[5], p.colours[8], p.accents[0], p.neutrals[3]];
      return `<div class="compare-row"><span class="compare-name">${esc(p.name)}</span>
        <div class="compare-tiles">${picks.map(h =>
          `<div class="drape" style="--c:${h}"><img src="${face}" alt="" loading="lazy"></div>`).join('')}</div></div>`;
    }).join('')}
  </section>`;
}

// --- photos ---------------------------------------------------------------------------------

function markers(photo) {
  return Object.entries(photo.points || {}).flatMap(([f, pts]) => pts.map(([x, y]) =>
    `<i class="marker m-${f}" style="left:${x * 100}%;top:${y * 100}%" title="${FEATURE_LABELS[f]}"></i>`)).join('');
}

function featureSwatches(photo) {
  return ['skin', 'hair', 'eyes'].map(f => {
    const c = photo.colours[f];
    return `<span class="fs">${c ? `<i style="background:${c.hex}"></i>` : '<i class="missing"></i>'}
      ${FEATURE_LABELS[f]}${c?.source === 'picked' ? ' <span class="muted">(picked)</span>' : ''}</span>`;
  }).join('') + (photo.white_balanced ? '<span class="fs muted">white-balanced</span>' : '');
}

function photoCard(photo) {
  const notes = [photo.error, ...photo.warnings].filter(Boolean);
  return `<article class="card photo-card${photo.included ? '' : ' excluded'}" data-photo="${photo.id}">
    <div class="photo-stage" data-open="${photo.id}"><img src="/api/photos/${photo.id}/image" alt="Photo ${photo.id}" loading="lazy">${markers(photo)}</div>
    <div class="feature-swatches">${featureSwatches(photo)}</div>
    ${notes.map(n => `<p class="note">${esc(n)}</p>`).join('')}
    <div class="actions">
      <label class="check"><input type="checkbox" data-include="${photo.id}"${photo.included ? ' checked' : ''}> Use</label>
      <button type="button" class="secondary small" data-open="${photo.id}">Adjust</button>
      <button type="button" class="danger small" data-delete-photo="${photo.id}">Delete</button>
    </div>
  </article>`;
}

async function uploadFiles(files) {
  const pid = $('#colour-profile').value;
  const status = $('#upload-status');
  const list = [...files];
  for (const [i, file] of list.entries()) {
    status.textContent = `Analysing ${i + 1} of ${list.length}…`;
    const res = await fetch(`/api/profiles/${pid}/photos`, {
      method: 'POST', body: file, headers: { 'Content-Type': file.type || 'application/octet-stream' },
    });
    if (!res.ok) {
      const err = await res.json().catch(() => ({}));
      status.textContent = `${file.name}: ${err.detail || res.statusText}`;
      await loadColour();
      return;
    }
  }
  status.textContent = '';
  await loadColour();
}

// --- editor ----------------------------------------------------------------------------------

function drawEditor() {
  const photo = colourState.photos.find(p => p.id === colourState.editing);
  if (!photo) return;
  $('#editor-stage').innerHTML = `<img src="/api/photos/${photo.id}/image" alt="">${markers(photo)}`;
  const manual = new Set(Object.entries(photo.colours).filter(([, c]) => c.source === 'picked').map(([f]) => f));
  if (photo.white_balanced) manual.add('white');
  $('#editor-swatches').innerHTML = ['skin', 'hair', 'eyes'].map(f => {
    const c = photo.colours[f];
    return `<span class="fs">${c ? `<i style="background:${c.hex}"></i>` : '<i class="missing"></i>'} ${FEATURE_LABELS[f]}
      ${manual.has(f) ? `<button type="button" class="link" data-unpick="${f}">reset to automatic</button>` : ''}</span>`;
  }).join('') + (manual.has('white')
    ? '<span class="fs">White reference set <button type="button" class="link" data-unpick="white">remove</button></span>' : '');
}

async function pickAt(e) {
  const img = $('#editor-stage img');
  if (!img || e.target.closest('.marker')) return;
  const rect = img.getBoundingClientRect();
  const x = (e.clientX - rect.left) / rect.width;
  const y = (e.clientY - rect.top) / rect.height;
  if (x < 0 || x > 1 || y < 0 || y > 1) return;
  const feature = $('#pick-mode input:checked').value;
  const updated = await api(`/api/photos/${colourState.editing}/pick`, { method: 'POST', body: { feature, x, y } });
  replacePhoto(updated);
}

function replacePhoto(updated) {
  colourState.photos = colourState.photos.map(p => p.id === updated.id ? updated : p);
  drawEditor();
}

// --- wiring ----------------------------------------------------------------------------------

function wireColour() {
  $('#colour-profile').addEventListener('change', loadColour);
  $('#photo-input').addEventListener('change', e => { uploadFiles(e.target.files); e.target.value = ''; });
  const drop = $('#drop');
  ['dragenter', 'dragover'].forEach(t => drop.addEventListener(t, e => { e.preventDefault(); drop.classList.add('over'); }));
  ['dragleave', 'drop'].forEach(t => drop.addEventListener(t, () => drop.classList.remove('over')));
  drop.addEventListener('drop', e => { e.preventDefault(); uploadFiles(e.dataTransfer.files); });

  $('#view-colour').addEventListener('click', async e => {
    const t = e.target.closest('[data-preview],[data-set-season],[data-copy],[data-open],[data-delete-photo]');
    if (!t) return;
    if (t.dataset.preview) { colourState.preview = t.dataset.preview; drawColour(); }
    if (t.dataset.setSeason) await saveColourSettings({ season_override: t.dataset.setSeason });
    if (t.dataset.copy) {
      try { await navigator.clipboard.writeText(t.dataset.copy); t.classList.add('copied'); setTimeout(() => t.classList.remove('copied'), 900); } catch { /* clipboard blocked */ }
    }
    if (t.dataset.open && !t.closest('dialog')) {
      colourState.editing = Number(t.dataset.open);
      drawEditor();
      $('#photo-dialog').showModal();
    }
    if (t.dataset.deletePhoto && confirm('Delete this photo?')) {
      await api(`/api/photos/${t.dataset.deletePhoto}`, { method: 'DELETE' });
      await loadColour();
    }
  });
  $('#view-colour').addEventListener('change', async e => {
    if (e.target.dataset.include) {
      await api(`/api/photos/${e.target.dataset.include}`, { method: 'PATCH', body: { included: e.target.checked } });
      await loadColour();
    }
    if (e.target.id === 'natural-hair' || e.target.id === 'season-override') {
      await saveColourSettings({});
    }
  });

  $('#editor-stage').addEventListener('click', pickAt);
  $('#editor-swatches').addEventListener('click', async e => {
    const f = e.target.dataset.unpick;
    if (f) replacePhoto(await api(`/api/photos/${colourState.editing}/pick/${f}`, { method: 'DELETE' }));
  });
  $('#photo-close').addEventListener('click', () => $('#photo-dialog').close());
  $('#photo-dialog').addEventListener('close', () => { colourState.editing = null; loadColour(); });
}

async function saveColourSettings(changes) {
  const body = {
    natural_hair: $('#natural-hair')?.value || null,
    season_override: $('#season-override')?.value || null,
    ...changes,
  };
  colourState.summary = await api(`/api/profiles/${$('#colour-profile').value}/colour`, { method: 'PUT', body });
  colourState.preview = null;
  drawColour();
}

wireColour();
