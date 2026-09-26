// Try on tab: body photos, pick a saved item (or upload a garment), run FASHN try-on, gallery.
// Uses helpers from app.js ($, $$, api, esc, fillSelect, state, show).

const tryonState = { key: null, photos: [], saved: [], results: [], photoId: null, savedId: null,
                     garmentUpload: null, busy: false, error: '' };

const TRYON_TYPES = { tops: 'Top', knitwear: 'Knitwear', outerwear: 'Coat / jacket', bottoms: 'Trousers',
                      skirts: 'Skirt', dresses: 'Dress / jumpsuit' };

async function renderTryon() {
  const sel = $('#tryon-profile');
  fillSelect(sel, state.profiles.map(p => [p.id, p.name]), sel.value || state.profiles[0]?.id);
  if (!state.profiles.length) {
    $('#tryon-setup').innerHTML = '';
    $('#tryon-content').innerHTML = '<p class="hint">First <a href="#" data-goto="profile">create a profile</a>.</p>';
    return;
  }
  const pid = sel.value;
  [tryonState.key, tryonState.photos, tryonState.saved, tryonState.results] = await Promise.all([
    api('/api/settings/fashn'), api(`/api/profiles/${pid}/body-photos`),
    api(`/api/profiles/${pid}/saved`), api(`/api/profiles/${pid}/tryons`),
  ]);
  if (!tryonState.photos.some(p => p.id === tryonState.photoId)) tryonState.photoId = tryonState.photos.at(-1)?.id ?? null;
  if (!tryonState.saved.some(s => s.saved_id === tryonState.savedId)) tryonState.savedId = null;
  drawTryon();
}

function drawTryonSetup() {
  const k = tryonState.key;
  const form = `<form id="fashn-form" class="key-form">
      <label>FASHN API key <input name="key" type="password" autocomplete="off" placeholder="Your FASHN API key"></label>
      <button type="submit" class="secondary">Save key</button>
      ${k.source === 'saved in the app' ? '<button type="button" class="link" id="fashn-remove">Remove key</button>' : ''}
    </form><p id="fashn-error" class="error" hidden></p>`;
  $('#tryon-setup').innerHTML = k.configured
    ? `<p class="muted shop-key">Try-on service: FASHN key ${esc(k.source)}. <button type="button" class="link" id="fashn-change">Change key</button></p>
       <div id="fashn-edit" hidden>${form}</div>`
    : `<section class="card"><h2>Connect the try-on service</h2>
        <p class="hint">Try-on uses <a href="https://fashn.ai" target="_blank" rel="noopener">FASHN</a>, a service built for
          virtual try-on. Create an account, buy a few credits (roughly $0.05–0.08 per try-on), and copy an API key from
          <a href="https://app.fashn.ai/api" target="_blank" rel="noopener">app.fashn.ai/api</a>.</p>
        ${form}
        <p class="muted small-print">The key is saved only on this computer (<code>data/settings.json</code>), or set <code>FASHN_API_KEY</code>.</p></section>`;
}

function photoPicker() {
  const photos = tryonState.photos;
  return `<section class="card">
    <h2>1. Your photo</h2>
    <p class="hint">A photo from head to at least your hips (full length is best for trousers and dresses),
      facing the camera, arms by your sides, in fitted clothes against a plain background.
      These are separate from your colour photos.</p>
    <div class="pick-grid">${photos.map(p => `
      <label class="pick-card${p.id === tryonState.photoId ? ' selected' : ''}">
        <input type="radio" name="tryon-photo" value="${p.id}"${p.id === tryonState.photoId ? ' checked' : ''}>
        <img src="/api/photos/${p.id}/image" alt="Your photo ${p.id}" loading="lazy">
      </label>`).join('')}
      <label class="pick-card add">
        <input type="file" id="body-photo-input" accept="image/*,.heic,.heif">
        <span>+ Add photo</span>
      </label>
    </div>
    <p id="body-photo-status" class="status"></p>
  </section>`;
}

function garmentPicker() {
  const items = tryonState.saved;
  const upload = tryonState.garmentUpload;
  return `<section class="card">
    <h2>2. What to try on</h2>
    ${items.length ? `<p class="hint">Pick a saved item. Shop thumbnails are small, so if a result looks blurry, save a
      clearer product picture from the shop's page and upload it below.</p>` :
      '<p class="hint">Save items from the <a href="#" data-goto="shop">Shop</a> tab, or upload a picture of a garment below.</p>'}
    <div class="pick-grid">${items.map(s => {
      const ok = s.garment in TRYON_TYPES;
      return `<label class="pick-card item${s.saved_id === tryonState.savedId && !upload ? ' selected' : ''}${ok ? '' : ' disabled'}"
          title="${esc(s.title)}${ok ? '' : ' (try-on works for clothing, not shoes or accessories)'}">
        <input type="radio" name="tryon-item" value="${s.saved_id}"${s.saved_id === tryonState.savedId && !upload ? ' checked' : ''}${ok ? '' : ' disabled'}>
        ${s.thumbnail ? `<img src="${esc(s.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ''}
        <span class="pick-title">${esc(s.title)}</span>
      </label>`;
    }).join('')}</div>
    <div class="garment-upload">
      <label class="upload-btn secondary">Upload a garment picture<input type="file" id="garment-input" accept="image/*"></label>
      ${upload ? `<img src="${upload.dataUrl}" alt="Uploaded garment" class="garment-thumb">
        <label>It's a <select id="garment-type">${Object.entries(TRYON_TYPES).map(([k, v]) =>
          `<option value="${k}"${upload.type === k ? ' selected' : ''}>${esc(v)}</option>`).join('')}</select></label>
        <button type="button" class="link" id="garment-clear">Use a saved item instead</button>` : ''}
    </div>
  </section>`;
}

function tryonCard(t) {
  const item = t.item;
  return `<article class="card tryon-result">
    <div class="before-after">
      <figure><img src="/api/photos/${t.photo_id}/image" alt="Before" loading="lazy"><figcaption>Before</figcaption></figure>
      <figure><img src="/api/tryons/${t.id}/image" alt="Wearing ${esc(item?.title || 'the garment')}" loading="lazy"><figcaption>Try-on</figcaption></figure>
    </div>
    <p>${item ? `<a href="${esc(item.link)}" target="_blank" rel="noopener">${esc(item.title)}</a>
      <span class="muted">${esc(item.source || '')}${item.price ? ` · ${esc(item.price)}` : ''}</span>` : '<span class="muted">Uploaded garment</span>'}</p>
    <div class="actions">
      <a class="small-link" href="/api/tryons/${t.id}/image" download="try-on-${t.id}.jpg">Download</a>
      <button type="button" class="danger small" data-delete-tryon="${t.id}">Delete</button>
    </div>
  </article>`;
}

function drawTryon() {
  drawTryonSetup();
  const s = tryonState;
  const ready = s.key.configured && s.photoId && (s.savedId || s.garmentUpload) && !s.busy;
  $('#tryon-content').innerHTML = `
    <div class="tryon-steps">${photoPicker()}${garmentPicker()}</div>
    <div class="actions tryon-go">
      <button type="button" id="tryon-go"${ready ? '' : ' disabled'}>${s.busy ? 'Dressing you…' : 'Try it on'}</button>
      <span class="status">${s.busy ? 'This usually takes 10–20 seconds.' :
        !s.key.configured ? 'Add a FASHN key above first.' : !s.photoId ? 'Add a photo of yourself.' :
        !(s.savedId || s.garmentUpload) ? 'Pick something to try on.' : ''}</span>
    </div>
    <p class="muted small-print">Your photo and the garment picture are sent to FASHN to create the image. The app asks
      FASHN to return the result directly rather than store it, and keeps it only on this computer (<code>data/tryons</code>).
      Try-on shows how a style and colour look on you. It can't show how a particular size will fit.</p>
    ${s.error ? `<p class="error">${esc(s.error)}</p>` : ''}
    ${s.results.length ? `<h2 class="section-heading">Your try-ons</h2><div class="tryon-grid">${s.results.map(tryonCard).join('')}</div>` : ''}`;
}

function readFileAsDataUrl(file) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(r.result);
    r.onerror = reject;
    r.readAsDataURL(file);
  });
}

// Called from the Shop tab's saved items.
async function tryonWith(savedId, profileId) {
  show('tryon');
  if (profileId) $('#tryon-profile').value = profileId;
  tryonState.savedId = savedId;
  tryonState.garmentUpload = null;
  await renderTryon();
  tryonState.savedId = savedId;
  drawTryon();
}

function wireTryon() {
  $('#tryon-profile').addEventListener('change', () => { tryonState.photoId = tryonState.savedId = null; renderTryon(); });
  const root = $('#view-tryon');
  root.addEventListener('change', async e => {
    const t = e.target;
    if (t.name === 'tryon-photo') { tryonState.photoId = Number(t.value); drawTryon(); }
    if (t.name === 'tryon-item') { tryonState.savedId = Number(t.value); tryonState.garmentUpload = null; drawTryon(); }
    if (t.id === 'garment-type') tryonState.garmentUpload.type = t.value;
    if (t.id === 'garment-input' && t.files[0]) {
      tryonState.garmentUpload = { dataUrl: await readFileAsDataUrl(t.files[0]), type: 'tops' };
      drawTryon();
    }
    if (t.id === 'body-photo-input' && t.files[0]) {
      $('#body-photo-status').textContent = 'Uploading…';
      const res = await fetch(`/api/profiles/${$('#tryon-profile').value}/body-photos`, {
        method: 'POST', body: t.files[0], headers: { 'Content-Type': t.files[0].type || 'application/octet-stream' } });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) { $('#body-photo-status').textContent = data.detail || 'Upload failed.'; return; }
      tryonState.photoId = data.id;
      await renderTryon();
    }
  });
  root.addEventListener('submit', async e => {
    if (e.target.id !== 'fashn-form') return;
    e.preventDefault();
    try {
      tryonState.key = await api('/api/settings/fashn', { method: 'PUT', body: { key: e.target.key.value } });
      drawTryon();
    } catch (err) {
      $('#fashn-error').textContent = err.message;
      $('#fashn-error').hidden = false;
    }
  });
  root.addEventListener('click', async e => {
    const t = e.target;
    if (t.id === 'fashn-change') $('#fashn-edit').hidden = false;
    if (t.id === 'fashn-remove') { tryonState.key = await api('/api/settings/fashn', { method: 'PUT', body: { key: '' } }); drawTryon(); }
    if (t.id === 'garment-clear') { tryonState.garmentUpload = null; drawTryon(); }
    if (t.dataset.deleteTryon && confirm('Delete this try-on?')) {
      await api(`/api/tryons/${t.dataset.deleteTryon}`, { method: 'DELETE' });
      tryonState.results = await api(`/api/profiles/${$('#tryon-profile').value}/tryons`);
      drawTryon();
    }
    if (t.id === 'tryon-go') {
      const s = tryonState;
      const body = { photo_id: s.photoId };
      if (s.garmentUpload) Object.assign(body, { garment_image: s.garmentUpload.dataUrl, garment_type: s.garmentUpload.type });
      else body.saved_id = s.savedId;
      s.busy = true; s.error = '';
      drawTryon();
      try {
        const result = await api(`/api/profiles/${$('#tryon-profile').value}/tryons`, { method: 'POST', body });
        s.results = [result, ...s.results];
      } catch (err) {
        s.error = err.message;
      }
      s.busy = false;
      drawTryon();
      $('.tryon-result')?.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    }
  });
}

wireTryon();
