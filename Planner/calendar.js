/* Planner — calendar view: time grid, event rendering, drag interactions. */
'use strict';

const calScroll = el('calScroll');
const dayColsEl = el('dayCols');
const dayHeadsEl = el('dayHeads');

function visibleDays() {
  if (state.view === '3day') {
    return Array.from({ length: 3 }, (_, i) => addDays(state.anchor, i));
  }
  const s = startOfWeek(state.anchor);
  return Array.from({ length: 7 }, (_, i) => addDays(s, i));
}

function renderTimeGutter() {
  const g = el('timeGutter');
  const frag = document.createDocumentFragment();
  for (let h = 1; h < 24; h++) {
    const lbl = document.createElement('div');
    lbl.className = 'time-label';
    lbl.style.top = `${h * HOUR_PX}px`;
    lbl.textContent = `${pad(h)}:00`;
    frag.appendChild(lbl);
  }
  g.replaceChildren(frag);
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

function renderCalendar() {
  const days = visibleDays();
  renderRangeLabel(days);
  const todayKey = toKey(new Date());

  const heads = document.createDocumentFragment();
  for (const d of days) {
    const key = toKey(d);
    const h = document.createElement('div');
    h.className = 'day-head' + (key === todayKey ? ' today' : '');
    h.innerHTML = `<div class="dow">${DOWS[(d.getDay() + 6) % 7]}</div><div class="dom">${d.getDate()}</div>`;
    heads.appendChild(h);
  }
  dayHeadsEl.replaceChildren(heads);

  const cols = document.createDocumentFragment();
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

    const occs = [];
    for (const t of state.tasks) {
      if (occursOn(t, key)) occs.push({ task: t, start: t.start, duration: t.duration, date: key });
    }
    layoutLanes(occs);
    for (const o of occs) col.appendChild(buildEventEl(o));

    cols.appendChild(col);
  }
  dayColsEl.replaceChildren(cols);
}

// Frees the grid's DOM nodes while the Tasks tab is showing.
function clearCalendarDom() {
  dayColsEl.replaceChildren();
  dayHeadsEl.replaceChildren();
}

function buildEventEl(occ) {
  const t = occ.task;
  const c = colorOf(t.color);
  const dark = isDark();
  const ev = document.createElement('div');
  ev.className = 'event' + (t.done ? ' done' : '');
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

  const notes = (t.notes || '').trim();
  ev.title = `${t.title || '(untitled)'}\n${fmtTime(occ.start)} – ${fmtTime(occ.start + occ.duration)} · ${fmtDur(occ.duration)}`
    + (notes ? `\n\n${notes}` : '');
  const showTime = occ.duration >= 30;
  const badges = ((t.repeat && t.repeat !== 'none') ? '⟳' : '') + (notes ? '✎' : '') + (isOnBoard(t) ? '▦' : '');
  ev.innerHTML =
    `<div class="ev-title">${escapeHtml(t.title || '(untitled)')}</div>` +
    (showTime ? `<div class="ev-time">${fmtTime(occ.start)} – ${fmtTime(occ.start + occ.duration)} · ${fmtDur(occ.duration)}</div>` : '') +
    (badges ? `<div class="ev-repeat">${badges}</div>` : '') +
    `<div class="resize-handle"></div>`;
  return ev;
}

function positionNowLine(node) {
  const now = new Date();
  node.style.top = `${((now.getHours() * 60 + now.getMinutes()) / 60) * HOUR_PX}px`;
}

setInterval(() => {
  if (state.tab !== 'calendar') return;
  const n = el('nowLine');
  if (n) positionNowLine(n);
}, 60000);

function resetScroll() {
  calScroll.scrollTop = SCROLL_TO_HOUR * HOUR_PX - 6;
}

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
    const task = getTask(evEl.dataset.taskId);
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
    if (dist < DRAG_THRESHOLD && !drag.moved) return;
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

document.addEventListener('pointerup', () => {
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
      renderCalendar();
      return;
    }
    if (d.copy) {
      state.tasks.push(copyOf(d.task, d.curDate, d.curStart));
    } else if (d.task.repeat && d.task.repeat !== 'none' && d.occDate !== d.task.date) {
      // Moving a non-base occurrence of a repeating task detaches just that day.
      d.task.exdates = d.task.exdates || [];
      d.task.exdates.push(d.occDate);
      state.tasks.push(copyOf(d.task, d.curDate, d.curStart));
    } else {
      d.task.date = d.curDate;
      d.task.start = d.curStart;
    }
    scheduleSave();
    renderCalendar();
    return;
  }

  if (d.mode === 'resize') {
    if (d.newDuration) {
      d.task.duration = d.newDuration;
      scheduleSave();
    }
    renderCalendar();
  }
});

// A dragged copy is a standalone, one-off calendar entry; it is not
// placed on the board (the original keeps that placement).
function copyOf(task, date, start) {
  return {
    id: uid(), title: task.title, date, start,
    duration: task.duration, color: task.color, repeat: 'none',
    notes: task.notes || '', exdates: [],
    sprintId: null, order: 0, done: false
  };
}

let ghostEl = null;
function drawGhost(dateKey, start, duration, title, colorName) {
  removeGhost();
  const col = colByDate(dateKey);
  if (!col) return;
  const c = colorOf(colorName);
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
  dayColsEl.querySelectorAll('.event[data-hidden="1"]').forEach((n) => {
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
