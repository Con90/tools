/* Planner — shared core: constants, date helpers, state, storage.
 *
 * A task is one record with two optional placements:
 *   scheduled  -> has date/start/duration  (shows on the Calendar)
 *   on a board -> has sprintId + order     (shows on the Tasks board)
 * Either, or both. That is what makes "send to tasks" and "send to
 * calendar" cheap: the record gains a placement, nothing is copied. */
'use strict';

// ---------- Constants ----------
const HOUR_PX = 56;
const SNAP_MOVE = 15;    // minutes
const SNAP_RESIZE = 5;   // minutes
const MIN_DURATION = 10; // minutes
const DAY_MIN = 24 * 60;
const SCROLL_TO_HOUR = 8;
const BACKLOG_ID = 'backlog';
const DRAG_THRESHOLD = 4; // px before a press becomes a drag

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
const colorOf = (name) => COLORS.find((c) => c.name === name) || COLORS[0];

// ---------- Small helpers ----------
const el = (id) => document.getElementById(id);
const uid = () => Date.now().toString(36) + Math.random().toString(36).slice(2, 8);
const escapeHtml = (s) => String(s).replace(/[&<>"']/g,
  (ch) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[ch]));

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

// ---------- State ----------
const state = {
  tab: 'calendar',         // 'calendar' | 'tasks'
  view: 'week',            // 'week' | '3day'
  anchor: new Date(),      // any date inside the visible range
  tasks: [],
  sprints: [],             // [{id, name}]
  editing: null            // {taskId, occDate} while the dialog is open
};

const getTask = (id) => state.tasks.find((t) => t.id === id);
const isScheduled = (t) => !!t.date;
const isOnBoard = (t) => !!t.sprintId;

// ---------- Storage ----------
const storage = {
  async load() {
    if (window.plannerAPI) return await window.plannerAPI.load();
    try {
      return JSON.parse(localStorage.getItem('planner-data')) || {};
    } catch {
      return {};
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
  saveTimer = setTimeout(() => {
    storage.save({ version: 2, tasks: state.tasks, sprints: state.sprints });
  }, 250);
}

// ---------- Recurrence ----------
function occursOn(task, dateKey) {
  if (!task.date) return false;                       // board-only task
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
