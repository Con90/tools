// Shop tab: product search ranked by palette match, with size advice and saved items.
// Uses helpers from app.js ($, $$, api, esc, fillSelect, state, show).

const shopState = { settings: null, last: null, saved: [], brief: null, busy: false };

const MATCH_TEXT = {
  great: 'In your palette', good: 'Close to your palette', off: 'Outside your palette',
  avoid: 'Harder colour for you', unknown: 'Colour not checked',
};

async function renderShop() {
  const sel = $('#shop-profile');
  fillSelect(sel, state.profiles.map(p => [p.id, p.name]), sel.value || state.profiles[0]?.id);
  $('#shop-form').hidden = !state.profiles.length;
  if (!state.profiles.length) {
    $('#shop-setup').innerHTML = '<p class="hint">First <a href="#" data-goto="profile">create a profile</a>.</p>';
    return;
  }
  const garmentSel = $('#shop-garment');
  if (!garmentSel.options.length) {
    fillSelect(garmentSel, [...Object.entries(state.meta.garments).map(([k, g]) => [k, g.label]),
      ['accessories', 'Accessories']], 'tops');
  }
  const pid = sel.value;
  const [settings, saved, style] = await Promise.all([
    api('/api/settings/serpapi'), api(`/api/profiles/${pid}/saved`), api(`/api/profiles/${pid}/style`),
  ]);
  shopState.settings = settings;
  shopState.saved = saved;
  shopState.brief = style.brief?.brief || null;
  const countrySel = $('#shop-country');
  fillSelect(countrySel, Object.entries(settings.countries), countrySel.value || settings.country);
  drawShopSetup();
  drawBriefPicks();
  drawSaved();
}

function drawShopSetup() {
  const s = shopState.settings;
  $('#shop-setup').innerHTML = s.configured
    ? `<p class="muted shop-key">Search API: SerpAPI key saved. <button type="button" class="link" id="serp-check">Check searches left</button>
        <button type="button" class="link" id="serp-change">Change key</button></p>
       <div id="serp-edit" hidden>${serpKeyForm()}</div>`
    : `<section class="card"><h2>Connect a shopping search</h2>
        <p class="hint">Product search uses <a href="https://serpapi.com/users/sign_up" target="_blank" rel="noopener">SerpAPI</a>,
          which searches Google Shopping. Its free plan gives about 100 searches a month, which is plenty for personal use,
          and the app remembers each search for a day so repeats are free.
          Sign up, copy your key from <a href="https://serpapi.com/manage-api-key" target="_blank" rel="noopener">your SerpAPI dashboard</a>, and paste it here.</p>
        ${serpKeyForm()}</section>`;
}

function serpKeyForm() {
  return `<form id="serp-form" class="key-form">
    <label>SerpAPI key <input name="key" type="password" autocomplete="off" placeholder="Your SerpAPI key"></label>
    <button type="submit" class="secondary">Save key</button>
    ${shopState.settings.configured ? '<button type="button" class="link" id="serp-remove">Remove key</button>' : ''}
  </form><p class="muted small-print">Saved only on this computer (<code>data/settings.json</code>).</p><p id="serp-error" class="error" hidden></p>`;
}

function drawBriefPicks() {
  const items = shopState.brief?.shopping_list || [];
  $('#brief-picks').innerHTML = items.length
    ? `<p class="muted picks-label">From your style brief:</p><div class="chip-picks">${items.map(i =>
        `<button type="button" class="pick brief-pick" data-find="${esc(i.search_query)}" data-garment="${esc(i.category)}">${esc(i.item)}</button>`).join('')}</div>`
    : '';
}

function sizeLine(p, general) {
  if (p.size) {
    const eq = equivalentsText(p.size.equivalents);
    return `<p class="size-line"><b>Your ${esc(p.size.brand)} size: ${esc(p.size.size)}${p.size.length ? ` ${esc(p.size.length)}` : ''}</b>${eq ? ` <span class="muted">(${esc(eq)})</span>` : ''}</p>`;
  }
  if (general) {
    const prefix = SIZE_PREFIX[general.system] ? `${general.system} ` : '';
    return `<p class="size-line muted">Your usual size: ${esc(prefix + general.size)}${general.length ? ` ${esc(general.length)} leg` : ''}. Check the shop's size guide</p>`;
  }
  return '';
}

function productCard(p, general, { savedView = false } = {}) {
  const c = p.colour || { label: 'unknown' };
  const colourPill = `<span class="cmatch m-${c.label}">${c.hex ? `<i style="background:${c.hex}"></i>` : ''}${MATCH_TEXT[c.label]}
    ${c.nearest && (c.label === 'great' || c.label === 'good') ? `<i class="nearest" style="background:${c.nearest}" title="Closest palette colour ${c.nearest}"></i>` : ''}</span>`;
  return `<article class="card product">
    <a class="product-img" href="${esc(p.link)}" target="_blank" rel="noopener">${p.thumbnail ? `<img src="${esc(p.thumbnail)}" alt="" loading="lazy" referrerpolicy="no-referrer">` : ''}</a>
    ${colourPill}
    <h3><a href="${esc(p.link)}" target="_blank" rel="noopener">${esc(p.title)}</a></h3>
    <p class="muted shop-line">${esc(p.source)}${p.price ? ` · <b class="price">${esc(p.price)}</b>` : ''}</p>
    ${savedView ? (p.size ? sizeLine(p) : '') : sizeLine(p, general)}
    ${p.flags?.length ? `<p class="flag">Mentions ${esc(p.flags.join(', '))}, which you said you don't wear</p>` : ''}
    <div class="actions">
      ${savedView
        ? `<button type="button" class="small" data-tryon="${p.saved_id}">Try on</button>
           <button type="button" class="secondary small" data-unsave="${p.saved_id}">Remove</button>`
        : `<button type="button" class="small${p.saved ? ' secondary' : ''}" data-save="${esc(p.id)}"${p.saved ? ' disabled' : ''}>${p.saved ? 'Saved' : 'Save'}</button>`}
      <a class="small-link" href="${esc(p.link)}" target="_blank" rel="noopener">View in shop ↗</a>
    </div>
  </article>`;
}

function drawResults() {
  const r = shopState.last;
  if (!r) return;
  const g = r.general_size;
  const eq = g ? equivalentsText(g.equivalents) : '';
  $('#shop-summary').innerHTML = `<p class="muted">
    ${r.shown} result${r.shown === 1 ? '' : 's'} for “${esc(r.query)}”${r.shown < r.total ? ` (${r.total - r.shown} outside your price range)` : ''}
    ${r.season ? ` · sorted by how well the colour suits you (${esc(r.season.name)})` : ' · <a href="#" data-goto="colour">add photos in Colours</a> to sort by your palette'}
    ${g ? ` · your usual size: <b>${esc((SIZE_PREFIX[g.system] ? g.system + ' ' : '') + g.size)}</b>${eq ? ` (${esc(eq)})` : ''}` : ''}
    ${r.cached ? ' · from a search earlier today (no search used)' : ''}</p>`;
  $('#shop-results').innerHTML = r.results.length
    ? r.results.map(p => productCard(p, g)).join('')
    : '<p class="hint">No products found. Try fewer or different words.</p>';
}

function drawSaved() {
  $('#saved-heading').hidden = !shopState.saved.length;
  $('#saved-items').innerHTML = shopState.saved.map(p => productCard(p, null, { savedView: true })).join('');
}

async function runShopSearch() {
  const f = $('#shop-form');
  const status = $('#shop-status');
  const body = {
    query: f.query.value.trim(), garment: f.garment.value, country: f.country.value,
    min_price: f.min_price.value ? Number(f.min_price.value) : null,
    max_price: f.max_price.value ? Number(f.max_price.value) : null,
  };
  status.textContent = 'Searching and checking colours…';
  status.classList.remove('error');
  $('#shop-results').setAttribute('aria-busy', 'true');
  try {
    shopState.last = await api(`/api/profiles/${$('#shop-profile').value}/shop/search`, { method: 'POST', body });
    status.textContent = '';
    drawResults();
  } catch (err) {
    status.textContent = err.message;
    status.classList.add('error');
  }
  $('#shop-results').removeAttribute('aria-busy');
}

// Called from the style brief's "Find" buttons.
async function shopSearchFor(query, garment, profileId) {
  show('shop');
  await renderShop();
  if (profileId) $('#shop-profile').value = profileId;
  const f = $('#shop-form');
  f.query.value = query;
  if ([...f.garment.options].some(o => o.value === garment)) f.garment.value = garment;
  if (shopState.settings.configured) runShopSearch();
}

function wireShop() {
  $('#shop-profile').addEventListener('change', () => { shopState.last = null; $('#shop-results').innerHTML = $('#shop-summary').innerHTML = ''; renderShop(); });
  $('#shop-form').addEventListener('submit', e => { e.preventDefault(); runShopSearch(); });
  $('#shop-country').addEventListener('change', e => api('/api/settings/serpapi', { method: 'PUT', body: { country: e.target.value } }));
  const root = $('#view-shop');
  root.addEventListener('submit', async e => {
    if (e.target.id !== 'serp-form') return;
    e.preventDefault();
    try {
      shopState.settings = await api('/api/settings/serpapi', { method: 'PUT', body: { key: e.target.key.value } });
      drawShopSetup();
    } catch (err) {
      $('#serp-error').textContent = err.message;
      $('#serp-error').hidden = false;
    }
  });
  root.addEventListener('click', async e => {
    const t = e.target;
    if (t.dataset.find) {
      const f = $('#shop-form');
      f.query.value = t.dataset.find;
      if ([...f.garment.options].some(o => o.value === t.dataset.garment)) f.garment.value = t.dataset.garment;
      runShopSearch();
    }
    if (t.dataset.save) {
      const product = shopState.last.results.find(p => p.id === t.dataset.save);
      await api(`/api/profiles/${$('#shop-profile').value}/saved`, { method: 'POST', body: { product } });
      product.saved = true;
      shopState.saved = await api(`/api/profiles/${$('#shop-profile').value}/saved`);
      drawResults(); drawSaved();
    }
    if (t.dataset.unsave) {
      await api(`/api/saved/${t.dataset.unsave}`, { method: 'DELETE' });
      shopState.saved = await api(`/api/profiles/${$('#shop-profile').value}/saved`);
      shopState.last?.results.forEach(p => { p.saved = shopState.saved.some(s => s.id === p.id); });
      drawResults(); drawSaved();
    }
    if (t.dataset.tryon) {
      tryonWith(Number(t.dataset.tryon), $('#shop-profile').value);
      return;
    }
    if (t.id === 'serp-change') $('#serp-edit').hidden = false;
    if (t.id === 'serp-remove') {
      shopState.settings = await api('/api/settings/serpapi', { method: 'PUT', body: { key: '' } });
      drawShopSetup();
    }
    if (t.id === 'serp-check') {
      t.textContent = 'Checking…';
      const s = await api('/api/settings/serpapi?check=true');
      t.textContent = s.searches_left == null ? "Couldn't check" : `${s.searches_left} searches left this month`;
    }
  });
}

wireShop();
