# Seal Pomodoro

A Pomodoro timer that isn't a window — it's a harbour seal hauled out on your
desktop. No frame, no panel, no box: just the seal, always on top if you want it
there, with the countdown on its flank.

![the seal](icons/seal-pomodoro-256.png)

## Install

```bash
./install.sh
```

That renders the icons, installs them into your icon theme, adds a menu entry
and drops a launcher on your desktop. Search the menu for "Seal", or use the
desktop icon.

To run it without installing:

```bash
python3 seal_pomodoro.py
```

## Using it

| Action | What it does |
| --- | --- |
| Click the seal | Start / pause |
| Drag the seal | Move it around the desktop |
| Hover | Reveals the control buttons underneath |
| Scroll on the seal | Add / remove a minute (while paused) |
| Right-click | Menu: start, reset, skip, always-on-top, settings, quit |

Keyboard, when the seal has focus: `space` start/pause, `r` reset, `s` skip,
`t` toggle always-on-top, `,` settings, `q` quit.

The hover buttons are, left to right: start/pause, reset, skip session,
always-on-top (filled = pinned), settings, quit.

## How it reads

- The **coloured line** across the body is the time remaining — it drains from
  the seal's back down to its belly over the session.
- The **eyes** are open while the clock is running and settle into a contented
  squint when it's paused.
- The **dots** under the clock are focus sessions completed toward the next long
  break.
- The accent colour is orange for focus, green for a short break, blue for a
  long one. When a session ends the seal bounces and claps its flippers.

## Settings

Right-click → Settings, or the gear button. Session lengths, sessions per long
break, seal size, end-of-session sound and notification, and auto-start of the
next session. Settings, window position and always-on-top are saved to
`~/.config/seal-pomodoro/config.json`.

## Requirements

Python 3, PyGObject (GTK 3) and pycairo — all present by default on Mint,
Ubuntu and most GTK desktops. The transparent, seal-shaped window needs a
compositing window manager (Cinnamon, Mutter, KWin, Xfwm with compositing on).
Without one the app still runs, but it falls back to a dark rectangular
background instead of a shaped window.

Sounds use `paplay` with the freedesktop sound theme; notifications use
`notify-send`. Both are optional and degrade quietly if missing.

## Files

- `seal_pomodoro.py` — the app; the seal is drawn in cairo, no image assets.
- `make_icon.py` — renders `icons/` (SVG + PNGs) using the app's own drawing
  code, so the icon and the app can't drift apart.
- `install.sh` — icon theme, menu entry, desktop launcher.
