/* Planner — Tasks board: sprint columns with drag-and-drop cards.
 *
 * Rendering is deliberately plain DOM with delegated listeners: one
 * pointerdown/click handler on the board, no per-card listeners, and no
 * framework. While dragging, the card being moved *is* the placeholder —
 * it is re-inserted between siblings — so a drag costs a couple of
 * insertBefore calls rather than a re-render. */
'use strict';

const boardEl = el('board');

const sprintName = (id) => id === BACKLOG_ID
  ? 'Backlog'
  : (state.sprints.find((s) => s.id === id) || {}).name || 'Backlog';

const columns = () => [{ id: BACKLOG_ID, name: 'Backlog' }, ...state.sprints];

const cardsIn = (sprintId) => state.tasks
  .filter((t) => t.sprintId === sprintId)
  .sort((a, b) => (a.order ?? 0) - (b.order ?? 0));

// ---------- Rendering ----------
function renderBoard() {
  const frag = document.createDocumentFragment();
  for (const col of columns()) frag.appendChild(buildColumn(col));
  frag.appendChild(buildAddColumn());
  boardEl.replaceChildren(frag);
}

function clearBoardDom() {
  boardEl.replaceChildren();
}

function buildColumn(col) {
  const cards = cardsIn(col.id);
  const wrap = document.createElement('div');
  wrap.className = 'column';
  wrap.dataset.sprint = col.id;

  const head = document.createElement('div');
  head.className = 'col-head';
  head.innerHTML =
    `<div class="col-name" title="${escapeHtml(col.name)}">${escapeHtml(col.name)}</div>` +
    `<div class="col-count">${cards.length}</div>` +
    (col.id === BACKLOG_ID ? '' : `<button class="col-menu icon-only" data-act="sprint-menu" title="Sprint options">⋯</button>`);
  wrap.appendChild(head);

  const list = document.createElement('div');
  list.className = 'col-cards';
  list.dataset.sprint = col.id;
  if (!cards.length) {
    const empty = document.createElement('div');
    empty.className = 'col-empty';
    empty.textContent = 'Drop tasks here';
    list.appendChild(empty);
  }
  for (const t of cards) list.appendChild(buildCard(t));
  wrap.appendChild(list);

  const add = document.createElement('button');
  add.className = 'col-add';
  add.dataset.act = 'add-task';
  add.textContent = '+ Add task';
  wrap.appendChild(add);
  return wrap;
}

function buildCard(t) {
  const c = colorOf(t.color);
  const card = document.createElement('div');
  card.className = 'card' + (t.done ? ' done' : '');
  card.dataset.id = t.id;
  card.style.borderLeftColor = c.edge;

  const notes = (t.notes || '').trim();
  const bits = [];
  if (isScheduled(t)) {
    const d = fromKey(t.date);
    bits.push(`<span class="card-when">📅 ${DOWS[(d.getDay() + 6) % 7]} ${d.getDate()} ${MONTHS[d.getMonth()].slice(0, 3)} · ${fmtTime(t.start)}</span>`);
  }
  if (t.repeat && t.repeat !== 'none') bits.push('<span title="Repeats">⟳</span>');
  if (notes) bits.push('<span title="Has notes">✎</span>');

  card.innerHTML =
    `<input type="checkbox" class="card-check" data-act="toggle-done"${t.done ? ' checked' : ''} title="Mark done">` +
    `<div class="card-body">` +
      `<div class="card-title">${escapeHtml(t.title || '(untitled)')}</div>` +
      (bits.length ? `<div class="card-meta">${bits.join('')}</div>` : '') +
    `</div>` +
    `<button class="card-menu icon-only" data-act="card-menu" title="Task options">⋯</button>`;
  card.title = (t.title || '(untitled)') + (notes ? `\n\n${notes}` : '');
  return card;
}

// ---------- Card drag & drop ----------
let bdrag = null; // {task, node, float, grabX, grabY, moved}

boardEl.addEventListener('pointerdown', (e) => {
  if (e.button !== 0) return;
  if (e.target.closest('[data-act]')) return;         // checkbox / menu / add
  const node = e.target.closest('.card');
  if (!node) return;
  const task = getTask(node.dataset.id);
  if (!task) return;
  const r = node.getBoundingClientRect();
  bdrag = {
    task, node, float: null, moved: false,
    grabX: e.clientX - r.left, grabY: e.clientY - r.top,
    startX: e.clientX, startY: e.clientY, width: r.width
  };
  e.preventDefault();
});

document.addEventListener('pointermove', (e) => {
  if (!bdrag) return;
  if (!bdrag.moved) {
    const dist = Math.abs(e.clientX - bdrag.startX) + Math.abs(e.clientY - bdrag.startY);
    if (dist < DRAG_THRESHOLD) return;
    bdrag.moved = true;
    const float = bdrag.node.cloneNode(true);
    float.classList.add('card-float');
    float.style.width = `${bdrag.width}px`;
    document.body.appendChild(float);
    bdrag.float = float;
    bdrag.node.classList.add('card-placeholder');
  }
  bdrag.float.style.transform =
    `translate(${e.clientX - bdrag.grabX}px, ${e.clientY - bdrag.grabY}px)`;

  const list = listUnder(e.clientX, e.clientY);
  if (list) placeInto(list, e.clientY);
});

document.addEventListener('pointerup', () => {
  if (!bdrag) return;
  const d = bdrag;
  bdrag = null;

  if (!d.moved) {                       // a click, not a drag
    openModal({ taskId: d.task.id });
    return;
  }

  d.float.remove();
  d.node.classList.remove('card-placeholder');

  const list = d.node.closest('.col-cards');
  if (list) {
    const sprintId = list.dataset.sprint;
    d.task.sprintId = sprintId;
    // Renumber just this column; orders stay small integers.
    [...list.querySelectorAll('.card')].forEach((node, i) => {
      const t = getTask(node.dataset.id);
      if (t) t.order = i;
    });
    scheduleSave();
  }
  renderBoard();
});

function listUnder(x, y) {
  for (const list of boardEl.querySelectorAll('.col-cards')) {
    const r = list.parentElement.getBoundingClientRect();
    if (x >= r.left && x < r.right && y >= r.top && y < r.bottom) return list;
  }
  return null;
}

// Insert the dragged node at the position matching the pointer.
function placeInto(list, y) {
  const empty = list.querySelector('.col-empty');
  if (empty) empty.remove();
  const siblings = [...list.querySelectorAll('.card')].filter((n) => n !== bdrag.node);
  const before = siblings.find((n) => {
    const r = n.getBoundingClientRect();
    return y < r.top + r.height / 2;
  });
  if (before) list.insertBefore(bdrag.node, before);
  else list.appendChild(bdrag.node);
}

// ---------- Clicks: checkboxes, menus, add buttons ----------
boardEl.addEventListener('click', (e) => {
  const actEl = e.target.closest('[data-act]');
  if (!actEl) return;
  const act = actEl.dataset.act;
  const card = actEl.closest('.card');
  const column = actEl.closest('.column');

  if (act === 'toggle-done' && card) {
    const t = getTask(card.dataset.id);
    if (!t) return;
    t.done = actEl.checked;
    card.classList.toggle('done', t.done);
    scheduleSave();
  } else if (act === 'card-menu' && card) {
    openCardMenu(actEl, getTask(card.dataset.id));
  } else if (act === 'sprint-menu' && column) {
    openSprintMenu(actEl, column.dataset.sprint);
  } else if (act === 'add-task' && column) {
    openModal({ sprintId: column.dataset.sprint, scheduled: false });
  } else if (act === 'add-sprint') {
    startSprintInput(actEl);
  }
});

// ---------- Popup menu (one shared element) ----------
let menuEl = null;

function closeMenu() {
  if (menuEl) { menuEl.remove(); menuEl = null; }
}

function openMenu(anchor, items) {
  closeMenu();
  menuEl = document.createElement('div');
  menuEl.className = 'popup-menu';
  for (const it of items) {
    if (it.sep) { menuEl.appendChild(document.createElement('hr')); continue; }
    const b = document.createElement('button');
    b.textContent = it.label;
    if (it.danger) b.className = 'danger';
    b.addEventListener('click', () => { closeMenu(); it.run(); });
    menuEl.appendChild(b);
  }
  document.body.appendChild(menuEl);
  const r = anchor.getBoundingClientRect();
  const mw = menuEl.offsetWidth, mh = menuEl.offsetHeight;
  menuEl.style.left = `${Math.min(r.left, window.innerWidth - mw - 8)}px`;
  menuEl.style.top = `${Math.min(r.bottom + 4, window.innerHeight - mh - 8)}px`;
}

document.addEventListener('pointerdown', (e) => {
  if (menuEl && !e.target.closest('.popup-menu') && !e.target.closest('[data-act]')) closeMenu();
}, true);
document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeMenu(); });

function openCardMenu(anchor, t) {
  if (!t) return;
  const items = [
    { label: 'Edit…', run: () => openModal({ taskId: t.id }) },
    { label: isScheduled(t) ? 'Reschedule…' : 'Send to calendar…',
      run: () => openModal({ taskId: t.id, scheduled: true }) }
  ];
  if (isScheduled(t)) {
    items.push({ label: 'Remove from board', run: () => {
      t.sprintId = null;
      scheduleSave();
      renderBoard();
    } });
  }
  items.push({ sep: true });
  items.push({ label: 'Delete task', danger: true, run: () => {
    state.tasks = state.tasks.filter((x) => x.id !== t.id);
    scheduleSave();
    renderBoard();
  } });
  openMenu(anchor, items);
}

function openSprintMenu(anchor, sprintId) {
  openMenu(anchor, [
    { label: 'Rename…', run: () => startRename(sprintId) },
    { sep: true },
    { label: 'Delete sprint', danger: true, run: () => {
      // Cards survive: they fall back to the Backlog.
      for (const t of state.tasks) if (t.sprintId === sprintId) t.sprintId = BACKLOG_ID;
      state.sprints = state.sprints.filter((s) => s.id !== sprintId);
      scheduleSave();
      renderBoard();
    } }
  ]);
}

// ---------- Sprint create / rename ----------
function buildAddColumn() {
  const wrap = document.createElement('div');
  wrap.className = 'column add-column';
  wrap.innerHTML = `<button class="col-add-sprint" data-act="add-sprint">+ Add sprint</button>`;
  return wrap;
}

function startSprintInput(button) {
  const input = document.createElement('input');
  input.className = 'sprint-input';
  input.placeholder = 'Sprint name…';
  const commit = (save) => {
    const name = input.value.trim();
    input.replaceWith(button);
    if (save && name) {
      state.sprints.push({ id: uid(), name });
      scheduleSave();
      renderBoard();
    }
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') commit(true);
    if (e.key === 'Escape') commit(false);
  });
  input.addEventListener('blur', () => commit(true));
  button.replaceWith(input);
  input.focus();
}

function startRename(sprintId) {
  const head = boardEl.querySelector(`.column[data-sprint="${sprintId}"] .col-name`);
  const sprint = state.sprints.find((s) => s.id === sprintId);
  if (!head || !sprint) return;
  const input = document.createElement('input');
  input.className = 'sprint-input';
  input.value = sprint.name;
  const commit = (save) => {
    const name = input.value.trim();
    if (save && name) {
      sprint.name = name;
      scheduleSave();
    }
    renderBoard();
  };
  input.addEventListener('keydown', (e) => {
    if (e.key === 'Enter') commit(true);
    if (e.key === 'Escape') commit(false);
  });
  input.addEventListener('blur', () => commit(true));
  head.replaceWith(input);
  input.focus();
  input.select();
}

// Places a task at the end of a column (used when a task joins the board).
function appendToSprint(task, sprintId) {
  const others = cardsIn(sprintId).filter((t) => t.id !== task.id);
  task.sprintId = sprintId;
  task.order = others.reduce((max, t) => Math.max(max, (t.order ?? 0) + 1), 0);
}
