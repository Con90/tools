/* Planner — the task dialog, shared by the calendar and the board.
 *
 * The same dialog edits both placements: the Sprint select puts a task on
 * the board, the "Schedule on calendar" switch puts it on the calendar.
 * A task must keep at least one placement, so an unscheduled task that
 * belongs to no sprint falls back to the Backlog. */
'use strict';

const backdrop = el('modalBackdrop');
let selectedColor = COLORS[0].name;

function buildSwatches() {
  const wrap = el('fSwatches');
  const frag = document.createDocumentFragment();
  for (const c of COLORS) {
    const s = document.createElement('div');
    s.className = 'swatch' + (c.name === selectedColor ? ' selected' : '');
    s.style.background = c.edge;
    s.title = c.name;
    s.addEventListener('click', () => {
      selectedColor = c.name;
      buildSwatches();
    });
    frag.appendChild(s);
  }
  wrap.replaceChildren(frag);
}

function buildSprintOptions(selected) {
  const sel = el('fSprint');
  const opts = [{ id: '', name: 'Not on the board' },
                { id: BACKLOG_ID, name: 'Backlog' },
                ...state.sprints];
  sel.replaceChildren(...opts.map((o) => {
    const opt = document.createElement('option');
    opt.value = o.id;
    opt.textContent = o.name;
    return opt;
  }));
  sel.value = selected || '';
}

function setScheduleVisible(on) {
  el('chkScheduled').checked = on;
  el('scheduleFields').classList.toggle('hidden', !on);
}

function openModal(opts) {
  const task = opts.taskId ? getTask(opts.taskId) : null;
  state.editing = { taskId: opts.taskId || null, occDate: opts.occDate || opts.date };

  const scheduled = task ? (isScheduled(task) || !!opts.scheduled)
                         : (opts.scheduled !== false && !!opts.date);

  el('modalTitle').textContent = task ? 'Edit task' : 'New task';
  el('fTitle').value = task ? task.title : '';
  el('fDate').value = (task && task.date) || opts.date || toKey(new Date());
  el('fStart').value = fmtTime(task && task.start != null ? task.start : (opts.start ?? 9 * 60));
  el('fDuration').value = task && task.duration ? task.duration : (opts.duration || 30);
  el('fRepeat').value = task ? (task.repeat || 'none') : 'none';
  el('fNotes').value = task ? (task.notes || '') : '';
  selectedColor = task ? task.color : selectedColor;
  buildSwatches();
  buildSprintOptions(task ? task.sprintId : (opts.sprintId || ''));
  setScheduleVisible(scheduled);

  el('btnDelete').classList.toggle('hidden', !task);
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

el('chkScheduled').addEventListener('change', (e) => {
  el('scheduleFields').classList.toggle('hidden', !e.target.checked);
});

el('btnSave').addEventListener('click', () => {
  if (backdrop.classList.contains('hidden')) return;   // never save a closed dialog
  const scheduled = el('chkScheduled').checked;
  let sprintId = el('fSprint').value || null;
  // A task needs somewhere to live: unscheduled and off the board would
  // make it invisible, so it lands in the Backlog instead.
  if (!scheduled && !sprintId) sprintId = BACKLOG_ID;

  const fields = {
    title: el('fTitle').value.trim() || 'Untitled',
    color: selectedColor,
    notes: el('fNotes').value.trim()
  };
  if (scheduled) {
    fields.date = el('fDate').value;
    fields.start = parseTimeInput(el('fStart').value);
    fields.duration = Math.max(5, Math.min(parseInt(el('fDuration').value, 10) || 30, DAY_MIN));
    fields.repeat = el('fRepeat').value;
  } else {
    fields.date = null;
    fields.repeat = 'none';
    fields.exdates = [];
  }

  const existing = state.editing && state.editing.taskId ? getTask(state.editing.taskId) : null;
  if (existing) {
    const movedBoard = sprintId && sprintId !== existing.sprintId;
    Object.assign(existing, fields);
    if (movedBoard) appendToSprint(existing, sprintId);
    else existing.sprintId = sprintId;
  } else {
    const task = {
      id: uid(), start: parseTimeInput(el('fStart').value),
      duration: Math.max(5, Math.min(parseInt(el('fDuration').value, 10) || 30, DAY_MIN)),
      exdates: [], sprintId: null, order: 0, done: false, ...fields
    };
    state.tasks.push(task);
    if (sprintId) appendToSprint(task, sprintId);
  }
  scheduleSave();
  closeModal();
  renderCurrentView();
});

el('btnCancel').addEventListener('click', closeModal);
backdrop.addEventListener('pointerdown', (e) => {
  if (e.target === backdrop) closeModal();
});

el('btnDelete').addEventListener('click', () => {
  const { taskId } = state.editing || {};
  const task = getTask(taskId);
  if (!task) return closeModal();
  if (task.repeat && task.repeat !== 'none') {
    el('confirmRow').classList.remove('hidden');
    return;
  }
  state.tasks = state.tasks.filter((t) => t.id !== taskId);
  scheduleSave();
  closeModal();
  renderCurrentView();
});

el('btnDelOne').addEventListener('click', () => {
  const { taskId, occDate } = state.editing || {};
  const task = getTask(taskId);
  if (task) {
    if (occDate === task.date) {
      // Removing the base date: shift the base to the next occurrence.
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
  renderCurrentView();
});

el('btnDelAll').addEventListener('click', () => {
  const { taskId } = state.editing || {};
  state.tasks = state.tasks.filter((t) => t.id !== taskId);
  scheduleSave();
  closeModal();
  renderCurrentView();
});

el('durationChips').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-min]');
  if (b) el('fDuration').value = b.dataset.min;
});

document.addEventListener('keydown', (e) => {
  if (e.key === 'Escape') {
    const sb = el('syncBackdrop');
    if (sb && !sb.classList.contains('hidden')) sb.classList.add('hidden');
    if (!backdrop.classList.contains('hidden')) closeModal();
  }
  // Enter saves, except in the notes box and the pickers where it types.
  if (e.key === 'Enter' && !backdrop.classList.contains('hidden')
      && e.target.tagName !== 'SELECT' && e.target.tagName !== 'TEXTAREA') {
    el('btnSave').click();
  }
});
