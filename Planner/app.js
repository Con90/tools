/* Planner — tab switching, top bar wiring, startup. */
'use strict';

function renderCurrentView() {
  if (state.tab === 'calendar') renderCalendar();
  else renderBoard();
}

function setTab(tab) {
  if (state.tab === tab) return;
  state.tab = tab;
  const onCal = tab === 'calendar';

  el('tabCalendar').classList.toggle('active', onCal);
  el('tabTasks').classList.toggle('active', !onCal);
  el('calendarView').classList.toggle('hidden', !onCal);
  el('boardView').classList.toggle('hidden', onCal);
  // Calendar-only controls.
  el('calNav').classList.toggle('hidden', !onCal);
  el('viewToggle').classList.toggle('hidden', !onCal);
  el('hintCalendar').classList.toggle('hidden', !onCal);
  el('hintBoard').classList.toggle('hidden', onCal);

  // Drop the hidden view's nodes rather than keeping two DOM trees alive.
  if (onCal) {
    clearBoardDom();
    renderCalendar();
    resetScroll();
  } else {
    clearCalendarDom();
    renderBoard();
  }
}

el('tabCalendar').addEventListener('click', () => setTab('calendar'));
el('tabTasks').addEventListener('click', () => setTab('tasks'));

el('btnToday').addEventListener('click', () => {
  state.anchor = new Date();
  renderCalendar();
  resetScroll();
});
el('btnPrev').addEventListener('click', () => {
  state.anchor = addDays(state.anchor, state.view === 'week' ? -7 : -1);
  renderCalendar();
  resetScroll();
});
el('btnNext').addEventListener('click', () => {
  state.anchor = addDays(state.anchor, state.view === 'week' ? 7 : 1);
  renderCalendar();
  resetScroll();
});
el('btnWeek').addEventListener('click', () => setCalView('week'));
el('btnDay').addEventListener('click', () => setCalView('3day'));

function setCalView(v) {
  state.view = v;
  el('btnWeek').classList.toggle('active', v === 'week');
  el('btnDay').classList.toggle('active', v === '3day');
  el('calendarView').classList.toggle('narrow', v === '3day');
  renderCalendar();
}

el('btnNew').addEventListener('click', () => {
  if (state.tab === 'calendar') openModal({ date: toKey(state.anchor), start: 9 * 60, duration: 30 });
  else openModal({ sprintId: BACKLOG_ID, scheduled: false });
});

window.matchMedia('(prefers-color-scheme: dark)').addEventListener('change', renderCurrentView);

// ---------- Init ----------
(async function init() {
  const data = (await storage.load()) || {};
  state.tasks = data.tasks || [];
  state.sprints = data.sprints || [];
  // Tasks saved before the board existed have no placement fields.
  for (const t of state.tasks) {
    if (t.sprintId === undefined) t.sprintId = null;
    if (t.order === undefined) t.order = 0;
    if (t.done === undefined) t.done = false;
  }
  renderTimeGutter();
  renderCalendar();
  resetScroll();
})();
