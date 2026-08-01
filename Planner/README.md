# Planner

A simple, elegant daily/weekly planner. Cross-platform (Linux, Windows, macOS) via Electron.

## Run

```bash
npm install
npm start
```

Or double-click `Planner.desktop` / `run-planner.sh` (copies live on the Desktop).

## Features

- **Week view** (default) and **3-day view**; navigate with ‹ / › / Today.
- 24-hour grid, auto-scrolled to the 08:00–18:00 window on launch.
- **Drag on empty grid** to create a task (15-min snapping), then name it in the dialog.
- **Drag a task** to move it (across days too). **Right-drag** (or Alt-drag) to copy it.
- **Drag the bottom edge** to resize (5-min snapping) — 20-minute tasks are fine.
- **Click a task** to edit: title, date, start, duration (with quick chips), color, repeat.
- **Repeats**: every day, weekdays (Mon–Fri), or weekly. Deleting a repeating task
  asks "only this day" or "entire series". Dragging a single occurrence detaches
  just that day.
- Dark mode follows the system theme.

## Data

Tasks are stored as JSON in Electron's user-data folder
(`~/.config/planner/tasks.json` on Linux). Each task:

```json
{
  "id": "…",
  "title": "Study finance",
  "date": "2026-08-01",
  "start": 540,
  "duration": 20,
  "color": "blue",
  "repeat": "none | daily | weekdays | weekly",
  "exdates": ["2026-08-05"]
}
```

`start`/`duration` are minutes; `exdates` are skipped occurrences of a repeating task.
Stable IDs + this schema are designed so a future **Outlook sync** (Microsoft Graph
`POST /me/events`, with `seriesMaster`/recurrence mapping) can mirror tasks 1:1.

## Package installers

```bash
npm run dist:linux   # AppImage + .deb
npm run dist:win     # NSIS installer (build on Windows, or use wine)
npm run dist:mac     # DMG (must be built on macOS)
```
