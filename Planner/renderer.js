/* Planner — renderer */
'use strict';

// ---------- Constants ----------
const HOUR_PX = 56;
const SNAP_MOVE = 15;    // minutes
const SNAP_RESIZE = 5;   // minutes
const MIN_DURATION = 10; // minutes
const DAY_MIN = 24 * 60;
const SCROLL_TO_HOUR = 8;

const COLORS = [
  { name: 'blue',   bg: '#dbe4ff', edge: '#4f6df5', text: '#2a3d9e', dbg: '#2b3557', dtext: '#c3d0ff' },
  { name: 'green',  bg: '#d9f2e3', edge: '#2f9e6e', text: '#1d6647', dbg: '#22423a', dtext: '#b5e8cd' },
  { name: 'amber',  bg: '#fdeeD3', edge: '#e8a13a', text: '#8a5a13', dbg: '#4a3b22', dtext: '#f5d9a0' },
  { name: 'red',    bg: '#fbdfdf', edge: '#d94f4f', text: '#8f2525', dbg: '#4a2929', dtext: '#f3b8b8' },
  { name: 'purple', bg: '#ecdff7', edge: '#9b59d0', text: '#5e2d85', dbg: '#3c2d4d', dtext: '#ddc2f2' },
  { name: 'teal',   bg: '#d7f0f2', edge: '#2fa7b5', text: '#176671', dbg: '#22414a', dtext: '#b0e4ea' },
  { name: 'gray',   bg: '#e7e9ee', edge: '#7a8194', text: '#3c4356', dbg: '#33363e', dtext: '#c8ccd6' }
];

const isDark = () => window.matchMedia('(prefers-color-scheme: dark)').matches;

// ---------- Date helpers ----------
const pad = (n) => String(n).padStart(2, '0');
const toKey = (d) => `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
const fromKey = (k) => {
  const [y, m, d] = k.split('-').map(Number);
  return new Date(y, m - 1, d);
};
const addDays = (d, n) => {
  const r = new Date(d);
  r.setDate(r.getDate() + n);
  return r;
};
const startOfWeek = (d) => {
  const r = new Date(d);
  const dow = (r.getDay() + 6) % 7; // Monday = 0
  return addDays(r, -dow);
};
const fmtTime = (min) => `${pad(Math.floor(min / 60))}:${pad(min % 60)}`;
const fmtDur = (min) => {
  if (min < 60) return `${min}m`;
  const h = Math.floor(min / 60), m = min % 60;
  return m ? `${h}h ${m}m` : `${h}h`;
};
const MONTHS = ['January','February','March','April','May','June','July','August','September','October','November','December'];
const DOWS = ['Mon','Tue','Wed','Thu','Fri','Sat','Sun'];

// ---------- Storage ----------
const storage = {
  async load() {
    if (window.plannerAPI) return await window.plannerAPI.load();
    try {
      return JSON.parse(localStorage.getItem('planner-data')) || { version: 1, tasks: [] };
    } catch {
      return { version: 1, tasks: [] };
    }
  },
  async save(data) {
    if (window.plannerAPI) return await window.plannerAPI.save(data);
    localStorage.setItem('planner-data', JSON.stringify(data));
  }
};

let saveTimer = null;
function scheduleSave() {
  clearTimeout(saveTimer);
  saveTimer = setTimeout(() => storage.save({ version: 1, tasks: state.tasks }), 250);
}

// ---------- State ----------
const state = {
  view: 'week',            // 'week' | '3day'
  anchor: new Date(),      // any date inside the visible range
  tasks: [],               // {id,title,date,start,duration,color,repeat,exdates:[]}
  editing: null            // {taskId, occDate} while modal open
};

const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);

// ---------- Recurrence ----------
function occursOn(task, dateKey) {
  if ((task.exdates || []).includes(dateKey)) return false;
  if (task.date === dateKey) return true;
  const freq = task.repeat || 'none';
  if (freq === 'none') return false;
  if (dateKey < task.date) return false;
  const d = fromKey(dateKey);
  const dow = (d.getDay() + 6) % 7; // Mon=0
  if (freq === 'daily') return true;
  if (freq === 'every2days' || freq === 'every3days') {
    const gap = Math.round((d - fromKey(task.date)) / 86400000);
    return gap % (freq === 'every2days' ? 2 : 3) === 0;
  }
  if (freq === 'weekdays') return dow <= 4;
  if (freq === 'weekly') {
    const base = fromKey(task.date);
    return ((base.getDay() + 6) % 7) === dow;
  }
  return false;
}

function visibleDays() {
  if (state.view === '3day') {
    return Array.from({ length: 3 }, (_, i) => addDays(state.anchor, i));
  }
  const s = startOfWeek(state.anchor);
  return Array.from({ length: 7 }, (_, i) => addDays(s, i));
}

// ---------- Rendering ----------
const el = (id) => document.getElementById(id);
const calScroll = el('calScroll');
const dayColsEl = el('dayCols');
const dayHeadsEl = el('dayHeads');

function renderTimeGutter() {
  const g = el('timeGutter');
  g.innerHTML = '';
  for (let h = 1; h < 24; h++) {
    const lbl = document.createElement('div');
    lbl.className = 'time-label';
    lbl.style.top = `${h * HOUR_PX}px`;
    lbl.textContent = `${pad(h)}:00`;
    g.appendChild(lbl);
  }
}

function renderRangeLabel(days) {
  const a = days[0], b = days[days.length - 1];
  let label;
  if (a.getMonth() === b.getMonth()) {
    label = `${a.getDate()}–${b.getDate()} ${MONTHS[a.getMonth()]} ${a.getFullYear()}`;
  } else {
    label = `${a.getDate()} ${MONTHS[a.getMonth()].slice(0,3)} – ${b.getDate()} ${MONTHS[b.getMonth()].slice(0,3)} ${b.getFullYear()}`;
  }
  el('rangeLabel').textContent = label;
}

// Assign side-by-side lanes to overlapping events.
function layoutLanes(occs) {
  const sorted = [...occs].sort((x, y) => x.start - y.start || y.duration - x.duration);
  const clusters = [];
  let cluster = null, clusterEnd = -1;
  for (const o of sorted) {
    if (!cluster || o.start >= clusterEnd) {
      cluster = [];
      clusters.push(cluster);
      clusterEnd = o.start + o.duration;
    } else {
      clusterEnd = Math.max(clusterEnd, o.start + o.duration);
    }
    cluster.push(o);
  }
  for (const c of clusters) {
    const laneEnds = [];
    for (const o of c) {
      let lane = laneEnds.findIndex((end) => o.start >= end);
      if (lane === -1) { lane = laneEnds.length; laneEnds.push(0); }
      laneEnds[lane] = o.start + o.duration;
      o._lane = lane;
    }
    for (const o of c) o._lanes = laneEnds.length;
  }
}

function renderAll() {
  const days = visibleDays();
  renderRangeLabel(days);
  const todayKey = toKey(new Date());

  // headers
  dayHeadsEl.innerHTML = '';
  for (const d of days) {
    const key = toKey(d);
    const h = document.createElement('div');
    h.className = 'day-head' + (key === todayKey ? ' today' : '');
    h.innerHTML = `<div class="dow">${DOWS[(d.getDay() + 6) % 7]}</div><div class="dom">${d.getDate()}</div>`;
    dayHeadsEl.appendChild(h);
  }

  // columns
  dayColsEl.innerHTML = '';
  for (const d of days) {
    const key = toKey(d);
    const col = document.createElement('div');
    col.className = 'day-col' + (key === todayKey ? ' today' : '');
    col.dataset.date = key;

    for (let h = 1; h < 24; h++) {
      const line = document.createElement('div');
      line.className = 'hour-line';
      line.style.top = `${h * HOUR_PX}px`;
      col.appendChild(line);
      const half = document.createElement('div');
      half.className = 'half-line';
      half.style.top = `${(h - 0.5) * HOUR_PX}px`;
      col.appendChild(half);
    }
    if (key === todayKey) {
      const now = document.createElement('div');
      now.className = 'now-line';
      now.id = 'nowLine';
      col.appendChild(now);
      positionNowLine(now);
    }

    // occurrences for this day
    const occs = [];
    for (const t of state.tasks) {
      if (occursOn(t, key)) occs.push({ task: t, start: t.start, duration: t.duration, date: key });
    }
    layoutLanes(occs);
    for (const o of occs) col.appendChild(buildEventEl(o));

    dayColsEl.appendChild(col);
  }
}

function buildEventEl(occ) {
  const t = occ.task;
  const c = COLORS.find((x) => x.name === t.color) || COLORS[0];
  const dark = isDark();
  const ev = document.createElement('div');
  ev.className = 'event';
  ev.dataset.taskId = t.id;
  ev.dataset.occDate = occ.date;
  ev.style.top = `${(occ.start / 60) * HOUR_PX}px`;
  ev.style.height = `${Math.max((occ.duration / 60) * HOUR_PX, 18)}px`;
  const lanes = occ._lanes || 1, lane = occ._lane || 0;
  const wPct = 100 / lanes;
  ev.style.left = `calc(${lane * wPct}% + 2px)`;
  ev.style.width = `calc(${wPct}% - 5px)`;
  ev.style.background = dark ? c.dbg : c.bg;
  ev.style.color = dark ? c.dtext : c.text;
  ev.style.borderLeftColor = c.edge;

  ev.title = `${t.title || '(untitled)'}\n${fmtTime(occ.start)} – ${fmtTime(occ.start + occ.duration)} · ${fmtDur(occ.duration)}`;
  const showTime = occ.duration >= 30;
  ev.innerHTML =
    `<div class="ev-title">${escapeHtml(t.title || '(untitled)')}</div>` +
    (showTime ? `<div class="ev-time">${fmtTime(occ.start)} – ${fmtTime(occ.start + occ.duration)} · ${fmtDur(occ.duration)}</div>` : '') +
    ((t.repeat && t.repeat !== 'none') ? `<div class="ev-repeat">⟳</div>` : '') +
    `<div class="resize-handle"></div>`;
  return ev;
}

function escapeHtml(s) {
  return s.replace(/[&<>"']/g, (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));
}

function positionNowLine(node) {
  const now = new Date();
  node.style.top = `${((now.getHours() * 60 + now.getMinutes()) / 60) * HOUR_PX}px`;
}

setInterval(() => {
  const n = document.getElementById('nowLine');
  if (n) positionNowLine(n);
}, 60000);

// ---------- Pointer interactions ----------
let drag = null; // {mode:'create'|'move'|'resize', ...}

function yToMinutes(clientY, snap) {
  const rect = dayColsEl.getBoundingClientRect();
  const y = clientY - rect.top;
  const min = (y / HOUR_PX) * 60;
  return Math.round(min / snap) * snap;
}

function xToDate(clientX) {
  const cols = [...dayColsEl.children];
  for (const col of cols) {
    const r = col.getBoundingClientRect();
    if (clientX >= r.left && clientX < r.right) return col.dataset.date;
  }
  if (!cols.length) return null;
  const first = cols[0].getBoundingClientRect();
  return clientX < first.left ? cols[0].dataset.date : cols[cols.length - 1].dataset.date;
}

function colByDate(key) {
  return dayColsEl.querySelector(`.day-col[data-date="${key}"]`);
}

dayColsEl.addEventListener('contextmenu', (e) => e.preventDefault());

dayColsEl.addEventListener('pointerdown', (e) => {
  const rightBtn = e.button === 2;
  if (e.button !== 0 && !rightBtn) return;
  const evEl = e.target.closest('.event');
  if (evEl) {
    const task = state.tasks.find((t) => t.id === evEl.dataset.taskId);
    if (!task) return;
    const occDate = evEl.dataset.occDate;
    if (e.target.classList.contains('resize-handle') && !rightBtn) {
      drag = { mode: 'resize', task, occDate, startY: e.clientY, origDuration: task.duration, moved: false };
    } else {
      const grabOffset = yToMinutes(e.clientY, 1) - task.start;
      drag = {
        mode: 'move', task, occDate, copy: rightBtn || e.altKey, copyLock: rightBtn,
        grabOffset, startX: e.clientX, startY: e.clientY, moved: false,
        curDate: occDate, curStart: task.start
      };
    }
  } else {
    if (rightBtn) return;
    const date = xToDate(e.clientX);
    if (!date) return;
    const start = Math.max(0, Math.min(yToMinutes(e.clientY, SNAP_MOVE), DAY_MIN - SNAP_MOVE));
    drag = { mode: 'create', date, anchorMin: start, start, duration: SNAP_MOVE, moved: false };
  }
  e.preventDefault();
});

document.addEventListener('pointermove', (e) => {
  if (!drag) return;
  const dist = Math.abs(e.clientX - (drag.startX ?? e.clientX)) + Math.abs(e.clientY - (drag.startY ?? e.clientY));

  if (drag.mode === 'create') {
    drag.moved = true;
    const cur = Math.max(0, Math.min(yToMinutes(e.clientY, SNAP_MOVE), DAY_MIN));
    drag.start = Math.min(drag.anchorMin, cur);
    drag.duration = Math.max(Math.abs(cur - drag.anchorMin), SNAP_MOVE);
    drawGhost(drag.date, drag.start, drag.duration, 'New task');
  } else if (drag.mode === 'move') {
    if (dist < 4 && !drag.moved) return;
    drag.moved = true;
    drag.copy = drag.copyLock || e.altKey;
    const date = xToDate(e.clientX) || drag.curDate;
    let start = yToMinutes(e.clientY, SNAP_MOVE) - Math.round(drag.grabOffset / SNAP_MOVE) * SNAP_MOVE;
    start = Math.max(0, Math.min(start, DAY_MIN - drag.task.duration));
    drag.curDate = date;
    drag.curStart = start;
    drawGhost(date, start, drag.task.duration, (drag.copy ? '⧉ ' : '') + (drag.task.title || '(untitled)'), drag.task.color);
    hideOriginal(drag, !drag.copy);
  } else if (drag.mode === 'resize') {
    drag.moved = true;
    const endMin = Math.max(drag.task.start + MIN_DURATION, Math.min(yToMinutes(e.clientY, SNAP_RESIZE), DAY_MIN));
    drag.newDuration = endMin - drag.task.start;
    drawGhost(drag.occDate, drag.task.start, drag.newDuration, drag.task.title || '(untitled)', drag.task.color);
    hideOriginal(drag, true);
  }
});

document.addEventListener('pointerup', (e) => {
  if (!drag) return;
  const d = drag;
  drag = null;
  removeGhost();

  if (d.mode === 'create') {
    const start = d.moved ? d.start : d.anchorMin;
    const duration = d.moved ? d.duration : 30;
    openModal({ date: d.date, start, duration });
    return;
  }

  if (d.mode === 'move') {
    if (!d.moved) {
      if (!d.copyLock) openModal({ taskId: d.task.id, occDate: d.occDate });
      renderAll();
      return;
    }
    if (d.copy) {
      state.tasks.push({
        id: uid(), title: d.task.title, date: d.curDate, start: d.curStart,
        duration: d.task.duration, color: d.task.color, repeat: 'none', exdates: []
      });
    } else if (d.task.repeat && d.task.repeat !== 'none' && d.occDate !== d.task.date) {
      // Moving a non-base occurrence of a repeating task detaches just that day.
      d.task.exdates = d.task.exdates || [];
      d.task.exdates.push(d.occDate);
      state.tasks.push({
        id: uid(), title: d.task.title, date: d.curDate, start: d.curStart,
        duration: d.task.duration, color: d.task.color, repeat: 'none', exdates: []
      });
    } else {
      d.task.date = d.curDate;
      d.task.start = d.curStart;
    }
    scheduleSave();
    renderAll();
    return;
  }

  if (d.mode === 'resize') {
    if (d.newDuration) {
      d.task.duration = d.newDuration;
      scheduleSave();
    }
    renderAll();
  }
});

let ghostEl = null;
function drawGhost(dateKey, start, duration, title, colorName) {
  removeGhost();
  const col = colByDate(dateKey);
  if (!col) return;
  const c = COLORS.find((x) => x.name === colorName) || COLORS[0];
  const dark = isDark();
  ghostEl = document.createElement('div');
  ghostEl.className = 'event ghost';
  ghostEl.style.top = `${(start / 60) * HOUR_PX}px`;
  ghostEl.style.height = `${Math.max((duration / 60) * HOUR_PX, 18)}px`;
  ghostEl.style.left = '2px';
  ghostEl.style.right = '3px';
  ghostEl.style.background = dark ? c.dbg : c.bg;
  ghostEl.style.color = dark ? c.dtext : c.text;
  ghostEl.style.borderLeftColor = c.edge;
  ghostEl.innerHTML = `<div class="ev-title">${escapeHtml(title)}</div>` +
    `<div class="ev-time">${fmtTime(start)} – ${fmtTime(start + duration)} · ${fmtDur(duration)}</div>`;
  col.appendChild(ghostEl);
}

function removeGhost() {
  if (ghostEl) { ghostEl.remove(); ghostEl = null; }
  document.querySelectorAll('.event[data-hidden="1"]').forEach((n) => {
    n.style.opacity = '';
    delete n.dataset.hidden;
  });
}

function hideOriginal(d, hide) {
  const sel = `.event[data-task-id="${d.task.id}"][data-occ-date="${d.occDate}"]`;
  const node = dayColsEl.querySelector(sel + ':not(.ghost)');
  if (node && hide) {
    node.style.opacity = '0.25';
    node.dataset.hidden = '1';
  }
}

// ---------- Modal ----------
const backdrop = el('modalBackdrop');
let selectedColor = COLORS[0].name;

function buildSwatches() {
  const wrap = el('fSwatches');
  wrap.innerHTML = '';
  for (const c of COLORS) {
    const s = document.createElement('div');
    s.className = 'swatch' + (c.name === selectedColor ? ' selected' : '');
    s.style.background = c.edge;
    s.title = c.name;
    s.addEventListener('click', () => {
      selectedColor = c.name;
      buildSwatches();
    });
    wrap.appendChild(s);
  }
}

function openModal(opts) {
  const isEdit = !!opts.taskId;
  const task = isEdit ? state.tasks.find((t) => t.id === opts.taskId) : null;
  state.editing = { taskId: opts.taskId || null, occDate: opts.occDate || opts.date };

  el('modalTitle').textContent = isEdit ? 'Edit task' : 'New task';
  el('fTitle').value = task ? task.title : '';
  el('fDate').value = task ? task.date : opts.date;
  el('fStart').value = fmtTime(task ? task.start : opts.start);
  el('fDuration').value = task ? task.duration : opts.duration;
  el('fRepeat').value = task ? (task.repeat || 'none') : 'none';
  selectedColor = task ? task.color : selectedColor;
  buildSwatches();

  el('btnDelete').classList.toggle('hidden', !isEdit);
  el('confirmRow').classList.add('hidden');
  el('repeatNote').classList.toggle('hidden', !(task && task.repeat && task.repeat !== 'none'));

  backdrop.classList.remove('hidden');
  el('fTitle').focus();
}

function closeModal() {
  backdrop.classList.add('hidden');
  state.editing = null;
}

function parseTimeInput(v) {
  const [h, m] = (v || '0:0').split(':').map(Number);
  return (h * 60 + m) || 0;
}

el('btnSave').addEventListener('click', () => {
  const title = el('fTitle').value.trim() || 'Untitled';
  const date = el('fDate').value;
  const start = parseTimeInput(el('fStart').value);
  const duration = Math.max(5, Math.min(parseInt(el('fDuration').value, 10) || 30, DAY_MIN));
  const repeat = el('fRepeat').value;

  if (state.editing && state.editing.taskId) {
    const task = state.tasks.find((t) => t.id === state.editing.taskId);
    if (task) Object.assign(task, { title, date, start, duration, color: selectedColor, repeat });
  } else {
    state.tasks.push({ id: uid(), title, date, start, duration, color: selectedColor, repeat, exdates: [] });
  }
  scheduleSave();
  closeModal();
  renderAll();
});

el('btnCancel').addEventListener('click', closeModal);
backdrop.addEventListener('pointerdown', (e) => {
  if (e.target === backdrop) closeModal();
});

el('btnDelete').addEventListener('click', () => {
  const { taskId } = state.editing || {};
  const task = state.tasks.find((t) => t.id === taskId);
  if (!task) return closeModal();
  if (task.repeat && task.repeat !== 'none') {
    el('confirmRow').classList.remove('hidden');
    return;
  }
  state.tasks = state.tasks.filter((t) => t.id !== taskId);
  scheduleSave();
  closeModal();
  renderAll();
});

el('btnDelOne').addEventListener('click', () => {
  const { taskId, occDate } = state.editing || {};
  const task = state.tasks.find((t) => t.id === taskId);
  if (task) {
    if (occDate === task.date) {
      // Removing the base date: shift base to the next occurrence.
      let next = addDays(fromKey(task.date), 1);
      for (let i = 0; i < 370; i++) {
        if (occursOn(task, toKey(next))) break;
        next = addDays(next, 1);
      }
      task.exdates = (task.exdates || []).filter((x) => x !== toKey(next));
      task.date = toKey(next);
    } else {
      task.exdates = task.exdates || [];
      task.exdates.push(occDate);
    }
    scheduleSave();
  }
  closeModal();
  renderAll();
});

el('btnDelAll').addEventListener('click', () => {
  const { taskId } = state.editing || {};
  state.tasks = state.tasks.filter((t) => t.id !== taskId);
  scheduleSave();
  closeModal();
  renderAll();
});

el('durationChips').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-min]');
  if (b) el('fDuration').value = b.dataset.min;
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const sb = document.getElementById('syncBackdrop');
    if (sb && !sb.classList.contains('hidden')) sb.classList.add('hidden');
  }
  if (e.key === 'Escape' && !backdrop.classList.contains('hidden')) closeModal();
  if (e.key === 'Enter' && !backdrop.classList.contains('hidden') && e.target.tagName !== 'SELECT') {
    el('btnSave').click();
  }
});

// ---------- Top bar ----------
function resetScroll() {
  calScroll.scrollTop = SCROLL_TO_HOUR * HOUR_PX - 6;
}

el('btnToday').addEventListener('click', () => {
  state.anchor = new Date();
  renderAll();
  resetScroll();
});
el('btnPrev').addEventListener('click', () => {
  state.anchor = addDays(state.anchor, state.view === 'week' ? -7 : -1);
  renderAll();
  resetScroll();
});
el('btnNext').addEventListener('click', () => {
  state.anchor = addDays(state.anchor, state.view === 'week' ? 7 : 1);
  renderAll();
  resetScroll();
});
el('btnWeek').addEventListener('click', () => setView('week'));
el('btnDay').addEventListener('click', () => setView('3day'));

function setView(v) {
  state.view = v;
  el('btnWeek').classList.toggle('active', v === 'week');
  el('btnDay').classList.toggle('active', v === '3day');
  document.querySelector('.calendar').classList.toggle('narrow', v === '3day');
  renderAll();
}

el('btnNew').addEventListener('click', () => {
  openModal({ date: toKey(state.anchor), start: 9 * 60, duration: 30 });
});

window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', renderAll);

// ---------- Outlook sync UI ----------
const syncBackdrop = el('syncBackdrop');
const syncAPI = window.plannerAPI && window.plannerAPI.sync;

function renderSyncStatus(s) {
  el('syncDot').classList.toggle('hidden', !(s && s.connected));
  if (!s) return;
  el('syncSetup').classList.toggle('hidden', s.connected);
  el('syncConnected').classList.toggle('hidden', !s.connected);
  el('fClientId').value = s.clientId || '';
  el('syncUser').textContent = s.username || '';
  el('btnSyncNow').disabled = !!s.busy;
  el('btnSyncNow').textContent = s.busy ? 'Syncing…' : 'Sync now';
  const last = s.lastSync;
  el('syncLastLine').textContent = last
    ? `Last sync ${new Date(last.at).toLocaleString()} — ${last.created} added, ${last.updated} updated, ${last.deleted} removed.`
    : 'Not synced yet.';
  el('syncError').classList.toggle('hidden', !s.lastError);
  el('syncError').textContent = s.lastError ? `Sync error: ${s.lastError}` : '';
  if (s.connected) el('deviceCodeBox').classList.add('hidden');
}

el('btnSyncOpen').addEventListener('click', async () => {
  syncBackdrop.classList.remove('hidden');
  if (!syncAPI) {
    el('syncUnavailable').style.display = '';
    el('syncSetup').classList.add('hidden');
    el('syncConnected').classList.add('hidden');
    return;
  }
  renderSyncStatus(await syncAPI.getStatus());
});

el('btnSyncClose').addEventListener('click', () => syncBackdrop.classList.add('hidden'));
syncBackdrop.addEventListener('pointerdown', (e) => {
  if (e.target === syncBackdrop) syncBackdrop.classList.add('hidden');
});

if (syncAPI) {
  syncAPI.onStatus(renderSyncStatus);

  syncAPI.onDeviceCode((info) => {
    el('deviceCodeBox').classList.remove('hidden');
    el('dcCode').textContent = info.userCode;
    const a = el('dcLink');
    a.textContent = info.verificationUri;
    a.href = info.verificationUri;
  });

  el('btnConnect').addEventListener('click', async () => {
    el('syncError').classList.add('hidden');
    try {
      await syncAPI.setClientId(el('fClientId').value);
      renderSyncStatus(await syncAPI.connect());
    } catch (err) {
      el('syncError').classList.remove('hidden');
      el('syncError').textContent = `Connect failed: ${err.message.replace(/^.*Error invoking remote method '[^']+': (Error: )?/, '')}`;
    }
  });

  el('btnDisconnect').addEventListener('click', async () => {
    await syncAPI.disconnect();
    renderSyncStatus(await syncAPI.getStatus());
  });

  el('btnSyncNow').addEventListener('click', () => syncAPI.now());

  syncAPI.getStatus().then(renderSyncStatus);
}

// ---------- Init ----------
(async function init() {
  const data = await storage.load();
  state.tasks = (data && data.tasks) || [];
  renderTimeGutter();
  renderAll();
  calScroll.scrollTop = SCROLL_TO_HOUR * HOUR_PX - 6;
})();
