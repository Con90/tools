#!/usr/bin/env python3
"""Seal Pomodoro — a Pomodoro timer that is just a seal lying on your desktop.

No window frame and no panel: a shaped, transparent, always-on-top harbour
seal hauled out on your wallpaper.

  click the seal ....... start / pause
  drag the seal ........ move it
  hover ................ reveal the little control buttons
  scroll ............... add / remove a minute (while paused)
  right-click .......... menu
"""

import json
import math
import os
import random
import shutil
import subprocess
import time

import cairo
import gi

gi.require_version("Gtk", "3.0")
gi.require_version("Gdk", "3.0")
gi.require_version("GdkPixbuf", "2.0")
gi.require_version("PangoCairo", "1.0")
from gi.repository import GdkPixbuf, GLib, Gdk, Gtk, Pango, PangoCairo  # noqa: E402

APP_NAME = "Seal Pomodoro"
APP_ID = "seal-pomodoro"
WM_CLASS = "Seal-pomodoro"
ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "icons")
CONFIG_DIR = os.path.join(
    os.environ.get("XDG_CONFIG_HOME", os.path.expanduser("~/.config")), "seal-pomodoro"
)
CONFIG_PATH = os.path.join(CONFIG_DIR, "config.json")

DEFAULTS = {
    "focus": 25,
    "short": 5,
    "long": 15,
    "cycles": 4,
    "always_on_top": True,
    "sound": True,
    "notify": True,
    "auto_start": False,
    "x": -1,
    "y": -1,
    "size": 480,
}

# ------------------------------------------------- palette (harbour seal) ---
COAT_TOP = (0.72, 0.69, 0.61)   # greyish, mottled back
COAT_HI = (0.96, 0.94, 0.87)    # sunlit flank
COAT = (0.89, 0.85, 0.76)
COAT_LO = (0.74, 0.69, 0.59)    # shaded underside
FLIPPER = (0.79, 0.74, 0.64)
MOTTLE = (0.58, 0.54, 0.47)
PAD = (0.95, 0.93, 0.88)
INK = (0.18, 0.15, 0.12)
WHITE = (1.0, 1.0, 1.0)

MODES = {
    "focus": {"label": "FOCUS", "accent": (0.96, 0.49, 0.27)},
    "short": {"label": "BREAK", "accent": (0.22, 0.73, 0.56)},
    "long": {"label": "LONG BREAK", "accent": (0.29, 0.58, 0.95)},
}

SOUND_DIR = "/usr/share/sounds/freedesktop/stereo"
SOUNDS = {
    "focus": os.path.join(SOUND_DIR, "alarm-clock-elapsed.oga"),
    "break": os.path.join(SOUND_DIR, "complete.oga"),
}

# --------------------------------------------------------------- geometry ---
# Local drawing units. The seal lies belly-down: head raised at the right,
# body tapering left, rear flippers lifted clear of the ground.
SEAL_OUTLINE = [
    (148, -74), (185, -60), (199, -24), (188, 8), (162, 26),
    (128, 44), (96, 60), (30, 70), (-46, 68), (-112, 56),
    (-152, 36), (-146, 6), (-100, -8), (-34, -20), (40, -32), (98, -58),
]
# Flippers are drawn as blades in their own frame — root at the origin,
# spreading out along +x — then rotated into place from a root hidden
# inside the body outline.
REAR_BLADE = [(0, -8), (40, -14), (72, -30), (86, -34), (88, -12), (80, 14),
              (52, 16), (20, 10)]
FRONT_BLADE = [(0, -13), (28, -11), (56, -9), (80, -6), (90, 1), (80, 8),
               (54, 11), (26, 12), (0, 13)]
#            root x,  root y, angle°, scale
REAR_POSE_BACK = (-118, 26, 190, 0.88)
REAR_POSE_FRONT = (-120, 20, 202, 1.0)
FRONT_POSE = (86, -6, 150, 1.0)

HEAD = (148, -24)      # centre of the face
FLANK = (-55, 22)      # where the read-out sits on the body
BBOX = (-215, -82, 232, 80)
CONTROL_PAD = 44       # strip under the seal reserved for the hover buttons
ASPECT = (BBOX[3] - BBOX[1] + CONTROL_PAD) / (BBOX[2] - BBOX[0])

# Fixed speckles along the back, so the mottling doesn't shimmer frame to frame.
SPECKLES = [
    (-118, 6, 15, 6), (-88, -2, 20, 7), (-52, -8, 17, 6), (-16, -14, 22, 8),
    (24, -20, 19, 7), (60, -22, 15, 6), (-70, 14, 13, 5), (-30, 6, 16, 5),
    (10, 0, 14, 5), (96, -40, 16, 7), (128, -58, 18, 8), (-134, 18, 11, 4),
]


def load_config():
    cfg = dict(DEFAULTS)
    try:
        with open(CONFIG_PATH) as fh:
            cfg.update(json.load(fh))
    except (OSError, ValueError):
        pass
    return cfg


def save_config(cfg):
    try:
        os.makedirs(CONFIG_DIR, exist_ok=True)
        with open(CONFIG_PATH, "w") as fh:
            json.dump(cfg, fh, indent=2)
    except OSError:
        pass


def play_sound(kind):
    path = SOUNDS.get(kind)
    if not path or not os.path.exists(path):
        return
    for player, args in (("paplay", [path]), ("canberra-gtk-play", ["-f", path])):
        exe = shutil.which(player)
        if exe:
            try:
                subprocess.Popen([exe] + args,
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                return
            except OSError:
                continue


def notify(title, body):
    exe = shutil.which("notify-send")
    if not exe:
        return
    try:
        subprocess.Popen([exe, "-a", APP_NAME, "-i", "clock", title, body],
                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    except OSError:
        pass


# ------------------------------------------------------------ cairo helpers ---
def smooth_closed(cr, pts, tension=1.0):
    """Closed Catmull-Rom curve through pts, emitted as bezier segments."""
    n = len(pts)
    cr.move_to(*pts[0])
    for i in range(n):
        p0, p1 = pts[(i - 1) % n], pts[i]
        p2, p3 = pts[(i + 1) % n], pts[(i + 2) % n]
        c1 = (p1[0] + (p2[0] - p0[0]) / 6.0 * tension,
              p1[1] + (p2[1] - p0[1]) / 6.0 * tension)
        c2 = (p2[0] - (p3[0] - p1[0]) / 6.0 * tension,
              p2[1] - (p3[1] - p1[1]) / 6.0 * tension)
        cr.curve_to(c1[0], c1[1], c2[0], c2[1], p2[0], p2[1])
    cr.close_path()


def ellipse(cr, cx, cy, rx, ry, rot=0.0):
    cr.save()
    cr.translate(cx, cy)
    if rot:
        cr.rotate(rot)
    cr.scale(rx, ry)
    cr.new_sub_path()
    cr.arc(0, 0, 1, 0, 2 * math.pi)
    cr.restore()


def rgba(cr, colour, alpha=1.0):
    cr.set_source_rgba(colour[0], colour[1], colour[2], alpha)


def text(cr, x, y, txt, size, colour, alpha=1.0, bold=True, spacing=0):
    layout = PangoCairo.create_layout(cr)
    layout.set_font_description(
        Pango.FontDescription("DejaVu Sans %s %d" % ("Bold" if bold else "", size))
    )
    if spacing:
        attrs = Pango.AttrList()
        attrs.insert(Pango.attr_letter_spacing_new(int(spacing * Pango.SCALE)))
        layout.set_attributes(attrs)
    layout.set_text(txt, -1)
    tw, th = layout.get_pixel_size()
    cr.save()
    rgba(cr, colour, alpha)
    cr.move_to(x - tw / 2.0, y - th / 2.0)
    PangoCairo.show_layout(cr, layout)
    cr.restore()


def draw_face(cr, hx, hy, eyes_open=False, celebrating=False, whiskers=True):
    """The seal's face, centred on (hx, hy). Shared by the app and the icon."""
    # dark mask around the eyes, as on a real harbour seal
    for sgn in (-1, 1):
        ellipse(cr, hx + sgn * 23, hy - 9, 16, 13)
        rgba(cr, MOTTLE, 0.22)
        cr.fill()

    # whisker pads / muzzle
    for sgn in (-1, 1):
        ellipse(cr, hx + sgn * 13, hy + 20, 19, 13)
        rgba(cr, PAD)
        cr.fill()

    # eyes: wide open while the clock runs, a contented squint at rest
    for sgn in (-1, 1):
        ex, ey = hx + sgn * 23, hy - 10
        if eyes_open:
            ellipse(cr, ex, ey, 7.5, 8.5)
            rgba(cr, INK)
            cr.fill()
            cr.new_sub_path()
            cr.arc(ex + 2.5, ey - 3, 2.4, 0, 2 * math.pi)
            rgba(cr, WHITE, 0.9)
            cr.fill()
        else:
            cr.set_line_width(2.4)
            cr.set_line_cap(cairo.LINE_CAP_ROUND)
            rgba(cr, INK, 0.9)
            cr.save()
            cr.translate(ex, ey + 2)
            cr.scale(7.5, 5.0)
            cr.new_sub_path()
            cr.arc(0, 0, 1, math.pi, 2 * math.pi)      # ⌒ — happy, closed
            cr.restore()
            cr.stroke()

    # nose
    ellipse(cr, hx, hy + 9, 8.5, 6)
    rgba(cr, INK)
    cr.fill()
    cr.set_line_width(1.6)
    rgba(cr, INK, 0.9)
    cr.move_to(hx, hy + 14)
    cr.line_to(hx, hy + 19)
    cr.stroke()

    # mouth
    cr.set_line_width(1.8)
    cr.set_line_cap(cairo.LINE_CAP_ROUND)
    rgba(cr, INK, 0.8)
    if celebrating:
        ellipse(cr, hx, hy + 24, 8, 6)
        cr.fill()
    else:
        for sgn in (-1, 1):
            cr.save()
            cr.translate(hx + sgn * 6, hy + 19)
            cr.scale(6, 5)
            cr.new_sub_path()
            cr.arc(0, 0, 1, 0, math.pi)
            cr.restore()
            cr.stroke()

    if whiskers:
        cr.set_line_width(1.2)
        rgba(cr, COAT_LO, 0.95)
        for sgn in (-1, 1):
            for dy1, dx2, dy2 in ((-5, 40, -13), (0, 44, -1), (5, 40, 11)):
                cr.move_to(hx + sgn * 15, hy + 18 + dy1)
                cr.line_to(hx + sgn * dx2, hy + 18 + dy2)
            cr.stroke()


class SealPomodoro:
    def __init__(self):
        self.cfg = load_config()

        self.mode = "focus"
        self.running = False
        self.completed = 0
        self.total = self.duration()
        self.remaining = float(self.total)
        self.deadline = None
        self.celebrate_until = 0.0

        self.t0 = time.monotonic()
        self.blink_at = self.t0 + random.uniform(2.0, 5.0)
        self.blink_end = 0.0
        self.hover = 0.0
        self.pointer_in = False
        self.buttons = []
        self.press = None
        self.dragging = False
        self._shape_for = None

        self._build_window()
        GLib.timeout_add(40, self._tick)

    # ------------------------------------------------------------- window ---
    def _build_window(self):
        self.win = Gtk.Window(type=Gtk.WindowType.TOPLEVEL)
        self.win.set_title(APP_NAME)
        self.win.set_decorated(False)
        self.win.set_app_paintable(True)
        self.win.set_resizable(False)
        self.win.set_keep_above(bool(self.cfg["always_on_top"]))

        width = max(280, int(self.cfg.get("size", 480)))
        self.win.set_default_size(width, int(round(width * ASPECT)))

        screen = self.win.get_screen()
        visual = screen.get_rgba_visual()
        self.transparent = visual is not None and screen.is_composited()
        if self.transparent:
            self.win.set_visual(visual)

        self.win.add_events(
            Gdk.EventMask.BUTTON_PRESS_MASK
            | Gdk.EventMask.BUTTON_RELEASE_MASK
            | Gdk.EventMask.POINTER_MOTION_MASK
            | Gdk.EventMask.ENTER_NOTIFY_MASK
            | Gdk.EventMask.LEAVE_NOTIFY_MASK
            | Gdk.EventMask.SCROLL_MASK
            | Gdk.EventMask.KEY_PRESS_MASK
        )
        self.win.connect("draw", self.on_draw)
        self.win.connect("button-press-event", self.on_press)
        self.win.connect("button-release-event", self.on_release)
        self.win.connect("motion-notify-event", self.on_motion)
        self.win.connect("enter-notify-event", self.on_enter)
        self.win.connect("leave-notify-event", self.on_leave)
        self.win.connect("scroll-event", self.on_scroll)
        self.win.connect("key-press-event", self.on_key)
        self.win.connect("destroy", lambda *_: self.quit())

        self.win.show_all()
        x, y = self.cfg.get("x", -1), self.cfg.get("y", -1)
        if x >= 0 and y >= 0:
            self.win.move(x, y)

    def _transform(self, cr, w, h):
        """Map local seal units onto the window; returns the scale factor."""
        x0, y0, x1, y1 = BBOX
        s = min((w - 10.0) / (x1 - x0), (h - 10.0 - CONTROL_PAD) / (y1 - y0))
        cr.translate(w / 2.0 - (x0 + x1) / 2.0 * s,
                     (h - CONTROL_PAD) / 2.0 - (y0 + y1) / 2.0 * s)
        cr.scale(s, s)
        return s

    def _update_input_shape(self, w, h):
        """Clicks land on the seal itself; everything else falls through."""
        if not self.transparent or self._shape_for == (w, h):
            return
        self._shape_for = (w, h)
        surface = cairo.ImageSurface(cairo.FORMAT_ARGB32, w, h)
        cr = cairo.Context(surface)
        cr.save()
        self._transform(cr, w, h)
        cr.set_source_rgba(0, 0, 0, 1)
        for blade, pose in ((REAR_BLADE, REAR_POSE_BACK),
                            (REAR_BLADE, REAR_POSE_FRONT),
                            (FRONT_BLADE, FRONT_POSE)):
            self._blade_path(cr, blade, pose)
            cr.fill()
        smooth_closed(cr, SEAL_OUTLINE)
        cr.fill()
        cr.restore()
        # Keep the hover-button strip clickable. It overlaps the belly slightly
        # so moving the pointer down onto the buttons never leaves the window.
        cr.rectangle(w / 2.0 - 110, h - CONTROL_PAD - 18, 220, CONTROL_PAD + 18)
        cr.fill()
        surface.flush()
        region = Gdk.cairo_region_create_from_surface(surface)
        gdk_win = self.win.get_window()
        if gdk_win is not None:
            gdk_win.input_shape_combine_region(region, 0, 0)

    # -------------------------------------------------------------- state ---
    def duration(self, mode=None):
        m = mode or self.mode
        return max(60, int(float(self.cfg.get(m, DEFAULTS[m])) * 60))

    @property
    def accent(self):
        return MODES[self.mode]["accent"]

    def toggle_run(self):
        if self.running:
            self.remaining = max(0.0, self.deadline - time.monotonic())
            self.running = False
            self.deadline = None
        else:
            if self.remaining <= 0:
                self.remaining = float(self.total)
            self.deadline = time.monotonic() + self.remaining
            self.running = True

    def reset(self):
        self.running = False
        self.deadline = None
        self.total = self.duration()
        self.remaining = float(self.total)
        self.celebrate_until = 0.0

    def skip(self):
        self._advance(completed=False)

    def _advance(self, completed=True):
        if self.mode == "focus":
            if completed:
                self.completed += 1
            cycles = max(1, int(self.cfg.get("cycles", 4)))
            nxt = "long" if self.completed and self.completed % cycles == 0 else "short"
        else:
            nxt = "focus"
        self.mode = nxt
        self.total = self.duration()
        self.remaining = float(self.total)
        self.deadline = None
        self.running = False
        if completed and self.cfg.get("auto_start"):
            self.toggle_run()

    def _finish(self):
        finished = self.mode
        self.running = False
        self.deadline = None
        self.remaining = 0.0
        self.celebrate_until = time.monotonic() + 4.0
        if self.cfg.get("sound", True):
            play_sound("focus" if finished == "focus" else "break")
        if self.cfg.get("notify", True):
            if finished == "focus":
                notify("Focus session done", "Break time — go flop on a rock.")
            else:
                notify("Break over", "Back to it.")
        self._advance(completed=True)

    def toggle_topmost(self):
        new = not bool(self.cfg.get("always_on_top"))
        self.cfg["always_on_top"] = new
        self.win.set_keep_above(new)

    def adjust(self, minutes):
        if self.running:
            return
        key = self.mode
        cur = int(float(self.cfg.get(key, DEFAULTS[key])))
        self.cfg[key] = max(1, min(180, cur + minutes))
        self.total = self.duration()
        self.remaining = float(self.total)

    def fmt_time(self):
        secs = int(math.ceil(max(0.0, self.remaining) - 1e-6))
        return "%02d:%02d" % (secs // 60, secs % 60)

    # ---------------------------------------------------------------- loop ---
    def _tick(self):
        now = time.monotonic()
        if self.running:
            self.remaining = max(0.0, self.deadline - now)
            if self.remaining <= 0:
                self._finish()

        if now >= self.blink_at and not self.blink_end:
            self.blink_end = now + 0.14
        if self.blink_end and now >= self.blink_end:
            self.blink_end = 0.0
            self.blink_at = now + random.uniform(2.5, 6.5)

        target = 1.0 if self.pointer_in else 0.0
        self.hover += (target - self.hover) * 0.25
        if abs(self.hover - target) < 0.01:
            self.hover = target

        self.win.queue_draw()
        return True

    # ---------------------------------------------------------------- draw ---
    def on_draw(self, _widget, cr):
        w = self.win.get_allocated_width()
        h = self.win.get_allocated_height()
        self._update_input_shape(w, h)

        cr.set_operator(cairo.Operator.SOURCE)
        if self.transparent:
            cr.set_source_rgba(0, 0, 0, 0)
        else:
            cr.set_source_rgba(0.07, 0.10, 0.14, 1)
        cr.paint()
        cr.set_operator(cairo.Operator.OVER)

        now = time.monotonic()
        t = now - self.t0
        celebrating = now < self.celebrate_until

        if celebrating:
            bob = -abs(math.sin(t * 6.5)) * 11.0
            breath = 0.05 * math.sin(t * 6.5)
        elif self.running:
            bob = math.sin(t * 2.2) * 1.4
            breath = 0.024 * math.sin(t * 2.2)
        else:
            bob = math.sin(t * 1.4) * 0.9
            breath = 0.017 * math.sin(t * 1.4)

        cr.save()
        self._transform(cr, w, h)
        self._draw_ground(cr)
        cr.translate(0, bob)
        cr.translate(0, 70)                        # pivot on the sand
        cr.scale(1.0 - breath * 0.35, 1.0 + breath)
        cr.translate(0, -70)
        self._draw_seal(cr, t, celebrating)
        cr.restore()

        self._draw_controls(cr, w, h)
        return False

    def _blade_path(self, cr, blade, pose):
        """Emit a flipper outline, rooted inside the body and swung into pose."""
        x, y, angle, sc = pose
        cr.save()
        cr.translate(x, y)
        cr.rotate(math.radians(angle))
        cr.scale(sc, sc)
        smooth_closed(cr, blade, 0.85)
        cr.restore()

    def _draw_ground(self, cr):
        cr.save()
        ellipse(cr, 0, 74, 168, 12)
        cr.set_source_rgba(0.16, 0.13, 0.09, 0.20)
        cr.fill()
        cr.restore()

    def _draw_seal(self, cr, t, celebrating):
        accent = self.accent

        # ---- rear flippers, lifted clear of the sand
        lift = math.sin(t * 1.1) * 2.5 if not celebrating else math.sin(t * 9) * 9
        for pose, shade in ((REAR_POSE_BACK, 0.80), (REAR_POSE_FRONT, 1.0)):
            x, y, ang, sc = pose
            self._blade_path(cr, REAR_BLADE, (x, y, ang - lift, sc))
            cr.set_source_rgb(FLIPPER[0] * shade, FLIPPER[1] * shade,
                              FLIPPER[2] * shade)
            cr.fill_preserve()
            cr.set_line_width(1.6)
            rgba(cr, INK, 0.32)
            cr.stroke()

        # ---- body
        smooth_closed(cr, SEAL_OUTLINE)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        for width, alpha in ((10, 0.07), (5, 0.11)):   # soft halo for contrast
            cr.set_line_width(width)
            cr.set_source_rgba(0.10, 0.08, 0.06, alpha)
            cr.stroke_preserve()

        lg = cairo.LinearGradient(0, -78, 0, 72)
        lg.add_color_stop_rgb(0.00, *COAT_TOP)
        lg.add_color_stop_rgb(0.30, *COAT_HI)
        lg.add_color_stop_rgb(0.68, *COAT)
        lg.add_color_stop_rgb(1.00, *COAT_LO)
        cr.set_source(lg)
        cr.fill_preserve()

        cr.save()
        cr.clip_preserve()
        for sx, sy, rx, ry in SPECKLES:            # mottled back
            ellipse(cr, sx, sy, rx, ry, -0.15)
            rgba(cr, MOTTLE, 0.16)
            cr.fill()
        # time remaining, as a level draining down the body
        frac = 0.0 if self.total <= 0 else max(0.0, min(1.0, self.remaining / self.total))
        top, bottom = -78.0, 72.0
        level = bottom - (bottom - top) * frac
        wob = math.sin(t * 1.6) * 1.2
        rgba(cr, accent, 0.10)
        cr.rectangle(-230, level + wob, 480, bottom - level + 20)
        cr.fill()
        rgba(cr, accent, 0.75)
        cr.rectangle(-230, level + wob, 480, 2.4)
        cr.fill()
        cr.restore()

        cr.set_line_width(1.8)
        rgba(cr, INK, 0.42)
        cr.stroke()

        # ---- read-out on the flank
        m = MODES[self.mode]
        text(cr, FLANK[0], FLANK[1] - 24, m["label"], 7, INK, 0.55, spacing=2.4)
        text(cr, FLANK[0], FLANK[1] + 1, self.fmt_time(), 26, INK, 0.90)
        self._draw_dots(cr, FLANK[0], FLANK[1] + 26)

        # ---- front flipper laid down across the chest
        wig = math.sin(t * 2.8) * 3 if self.running else math.sin(t * 1.2) * 1.5
        if celebrating:
            wig = math.sin(t * 12.0) * 16
        fx, fy, fang, fsc = FRONT_POSE
        self._blade_path(cr, FRONT_BLADE, (fx + 3, fy + 4, fang + wig, fsc))
        cr.set_source_rgba(0.20, 0.16, 0.11, 0.18)      # shadow on the belly
        cr.fill()
        self._blade_path(cr, FRONT_BLADE, (fx, fy, fang + wig, fsc))
        rgba(cr, FLIPPER)
        cr.fill_preserve()
        cr.set_line_width(1.6)
        rgba(cr, INK, 0.32)
        cr.stroke()
        cr.save()                                       # claws at the tip
        cr.translate(fx, fy)
        cr.rotate(math.radians(fang + wig))
        cr.set_line_width(1.4)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        rgba(cr, INK, 0.45)
        for dy in (-4, 1, 6):
            cr.move_to(83, dy)
            cr.line_to(91, dy + 1)
        cr.stroke()
        cr.restore()

        self._draw_face(cr, t, celebrating)

        if celebrating:
            for i in range(7):
                a = t * 2.4 + i * (2 * math.pi / 7)
                r = 92 + math.sin(t * 6 + i) * 9
                self._sparkle(cr, HEAD[0] + math.cos(a) * r,
                              HEAD[1] + math.sin(a) * r * 0.75, 5, accent)

    def _draw_dots(self, cr, x, y):
        cycles = max(1, int(self.cfg.get("cycles", 4)))
        done = self.completed % cycles
        if self.completed and done == 0 and self.mode == "long":
            done = cycles
        gap = 10.0
        start = x - (cycles - 1) * gap / 2.0
        for i in range(cycles):
            cr.new_sub_path()
            cr.arc(start + i * gap, y, 2.7, 0, 2 * math.pi)
            if i < done:
                rgba(cr, INK, 0.7)
                cr.fill()
            else:
                cr.set_line_width(1.2)
                rgba(cr, INK, 0.32)
                cr.stroke()

    def _draw_face(self, cr, t, celebrating):
        blinking = bool(self.blink_end) or (celebrating and int(t * 7) % 2 == 0)
        eyes_open = self.running and not blinking and not celebrating
        draw_face(cr, HEAD[0], HEAD[1], eyes_open=eyes_open, celebrating=celebrating)

    def _sparkle(self, cr, x, y, r, colour):
        cr.save()
        cr.translate(x, y)
        cr.move_to(0, -r)
        for _ in range(4):
            cr.rotate(math.pi / 2)
            cr.curve_to(r * 0.18, -r * 0.18, r * 0.18, -r * 0.18, 0, -r)
        cr.close_path()
        rgba(cr, colour, 0.9)
        cr.fill()
        cr.restore()

    # ------------------------------------------------------------ controls ---
    def _draw_controls(self, cr, w, h):
        icons = [
            ("pause" if self.running else "play", "toggle"),
            ("reset", "reset"),
            ("skip", "skip"),
            ("pin", "pin"),
            ("gear", "settings"),
            ("close", "quit"),
        ]
        r, gap = 13.0, 32.0
        y = h - r - 8
        start = w / 2.0 - (len(icons) - 1) * gap / 2.0
        self.buttons = [(start + i * gap, y, r + 3, key)
                        for i, (_, key) in enumerate(icons)]

        a = self.hover
        if a <= 0.02:
            return
        for (bx, by, _hit, _key), (icon, _) in zip(self.buttons, icons):
            cr.new_sub_path()
            cr.arc(bx, by, r, 0, 2 * math.pi)
            cr.set_source_rgba(0.09, 0.11, 0.15, 0.86 * a)
            cr.fill_preserve()
            cr.set_line_width(1.0)          # rim, so the chips read on any wallpaper
            cr.set_source_rgba(1, 1, 1, 0.22 * a)
            cr.stroke()
            self._icon(cr, icon, bx, by, a)

    def _icon(self, cr, name, x, y, a):
        accent = self.accent
        cr.save()
        cr.translate(x, y)
        cr.set_line_width(1.8)
        cr.set_line_cap(cairo.LINE_CAP_ROUND)
        cr.set_line_join(cairo.LINE_JOIN_ROUND)
        if name == "play":
            rgba(cr, accent, a)
            cr.move_to(-3.5, -5.5)
            cr.line_to(5.5, 0)
            cr.line_to(-3.5, 5.5)
            cr.close_path()
            cr.fill()
        elif name == "pause":
            rgba(cr, accent, a)
            cr.rectangle(-4.5, -5.5, 3.2, 11)
            cr.rectangle(1.3, -5.5, 3.2, 11)
            cr.fill()
        elif name == "reset":
            rgba(cr, WHITE, a)
            cr.new_sub_path()
            cr.arc(0, 0, 5.2, math.radians(-40), math.radians(230))
            cr.stroke()
            cr.move_to(5.6, -4.8)
            cr.line_to(4.3, 0.6)
            cr.line_to(0.5, -2.6)
            cr.close_path()
            cr.fill()
        elif name == "skip":
            rgba(cr, WHITE, a)
            cr.move_to(-5, -5.5)
            cr.line_to(2, 0)
            cr.line_to(-5, 5.5)
            cr.close_path()
            cr.fill()
            cr.rectangle(3, -5.5, 2.2, 11)
            cr.fill()
        elif name == "pin":
            on = bool(self.cfg.get("always_on_top"))
            rgba(cr, accent if on else WHITE, a if on else a * 0.7)
            cr.new_sub_path()
            cr.arc(0, 0, 5.0, 0, 2 * math.pi)
            cr.fill() if on else cr.stroke()
        elif name == "gear":
            rgba(cr, WHITE, a)
            for i in range(6):
                cr.save()
                cr.rotate(i * math.pi / 3)
                cr.rectangle(-1.3, -6.4, 2.6, 3.0)
                cr.fill()
                cr.restore()
            cr.new_sub_path()
            cr.arc(0, 0, 3.6, 0, 2 * math.pi)
            cr.stroke()
        elif name == "close":
            rgba(cr, WHITE, a)
            cr.move_to(-4, -4)
            cr.line_to(4, 4)
            cr.move_to(4, -4)
            cr.line_to(-4, 4)
            cr.stroke()
        cr.restore()

    def _hit(self, x, y):
        for bx, by, r, key in self.buttons:
            if (x - bx) ** 2 + (y - by) ** 2 <= r * r:
                return key
        return None

    # -------------------------------------------------------------- events ---
    def on_enter(self, *_):
        self.pointer_in = True
        return False

    def on_leave(self, _w, event):
        if event.detail != Gdk.NotifyType.INFERIOR:
            self.pointer_in = False
        return False

    def on_motion(self, _w, event):
        self.pointer_in = True
        if self.press and not self.dragging:
            dx = event.x_root - self.press[0]
            dy = event.y_root - self.press[1]
            if dx * dx + dy * dy > 25:
                self.dragging = True
                self.win.begin_move_drag(1, int(event.x_root), int(event.y_root),
                                         event.time)
        return False

    def on_press(self, _w, event):
        if event.button == 3:
            self._menu(event)
            return True
        if event.button != 1:
            return False
        if self._hit(event.x, event.y):
            return True                     # acted on release
        self.press = (event.x_root, event.y_root)
        self.dragging = False
        return True

    def on_release(self, _w, event):
        if event.button != 1:
            return False
        key = self._hit(event.x, event.y)
        if key:
            self._action(key)
        elif self.press and not self.dragging:
            self.toggle_run()
        self.press = None
        self.dragging = False
        return True

    def on_scroll(self, _w, event):
        if event.direction == Gdk.ScrollDirection.UP:
            self.adjust(1)
        elif event.direction == Gdk.ScrollDirection.DOWN:
            self.adjust(-1)
        elif event.direction == Gdk.ScrollDirection.SMOOTH:
            ok, _dx, dy = event.get_scroll_deltas()
            if ok and abs(dy) > 0.4:
                self.adjust(-1 if dy > 0 else 1)
        return True

    def on_key(self, _w, event):
        name = Gdk.keyval_name(event.keyval or 0) or ""
        actions = {
            "space": self.toggle_run, "r": self.reset, "s": self.skip,
            "t": self.toggle_topmost, "q": self.quit, "comma": self.open_settings,
        }
        fn = actions.get(name.lower() if len(name) == 1 else name)
        if fn:
            fn()
            return True
        return False

    def _action(self, key):
        {
            "toggle": self.toggle_run,
            "reset": self.reset,
            "skip": self.skip,
            "pin": self.toggle_topmost,
            "settings": self.open_settings,
            "quit": self.quit,
        }[key]()

    def _menu(self, event):
        menu = Gtk.Menu()
        items = [
            ("Pause" if self.running else "Start", self.toggle_run),
            ("Reset", self.reset),
            ("Skip session", self.skip),
            (None, None),
            ("Always on top", None),
            ("Settings…", self.open_settings),
            (None, None),
            ("Quit", self.quit),
        ]
        for label, fn in items:
            if label is None:
                item = Gtk.SeparatorMenuItem()
            elif label == "Always on top":
                item = Gtk.CheckMenuItem(label=label)
                item.set_active(bool(self.cfg.get("always_on_top")))
                item.connect("toggled", lambda *_: self.toggle_topmost())
            else:
                item = Gtk.MenuItem(label=label)
                item.connect("activate", lambda _i, f=fn: f())
            item.show()
            menu.append(item)
        menu.popup_at_pointer(event)

    # ------------------------------------------------------------ settings ---
    def open_settings(self):
        dlg = Gtk.Dialog(title="Seal Pomodoro — Settings", transient_for=self.win,
                         modal=False)
        dlg.set_keep_above(bool(self.cfg.get("always_on_top")))
        dlg.add_button("Cancel", Gtk.ResponseType.CANCEL)
        dlg.add_button("Save", Gtk.ResponseType.OK)

        grid = Gtk.Grid(row_spacing=8, column_spacing=14, margin=16)
        rows = [("Focus (minutes)", "focus"), ("Short break", "short"),
                ("Long break", "long"), ("Sessions per long break", "cycles"),
                ("Seal width (px)", "size")]
        spins = {}
        for i, (label, key) in enumerate(rows):
            grid.attach(Gtk.Label(label=label, xalign=0), 0, i, 1, 1)
            is_size = key == "size"
            sp = Gtk.SpinButton.new_with_range(280 if is_size else 1,
                                               1600 if is_size else 180,
                                               20 if is_size else 1)
            sp.set_value(float(self.cfg.get(key, DEFAULTS[key])))
            spins[key] = sp
            grid.attach(sp, 1, i, 1, 1)

        checks = {}
        for j, (label, key) in enumerate([("Sound when a session ends", "sound"),
                                          ("Desktop notification", "notify"),
                                          ("Auto-start next session", "auto_start"),
                                          ("Always on top", "always_on_top")]):
            cb = Gtk.CheckButton(label=label)
            cb.set_active(bool(self.cfg.get(key, DEFAULTS[key])))
            checks[key] = cb
            grid.attach(cb, 0, len(rows) + j, 2, 1)

        dlg.get_content_area().add(grid)
        dlg.show_all()

        def responded(d, response):
            if response == Gtk.ResponseType.OK:
                for key, sp in spins.items():
                    self.cfg[key] = int(sp.get_value())
                for key, cb in checks.items():
                    self.cfg[key] = bool(cb.get_active())
                self.win.set_keep_above(bool(self.cfg["always_on_top"]))
                width = int(self.cfg["size"])
                self.win.resize(width, int(round(width * ASPECT)))
                self._shape_for = None
                if not self.running:
                    self.total = self.duration()
                    self.remaining = float(self.total)
                save_config(self.cfg)
            d.destroy()

        dlg.connect("response", responded)

    # ---------------------------------------------------------------- exit ---
    def quit(self):
        try:
            x, y = self.win.get_position()
            self.cfg["x"], self.cfg["y"] = int(x), int(y)
        except Exception:
            pass
        save_config(self.cfg)
        Gtk.main_quit()


def install_window_icon():
    """Give the window list a seal instead of the stock GTK cog.

    Prefers the icon theme (present once install.sh has run) and otherwise
    loads the PNGs sitting next to this script, so running straight from the
    source directory still looks right.
    """
    if Gtk.IconTheme.get_default().has_icon(APP_ID):
        Gtk.Window.set_default_icon_name(APP_ID)
        return
    pixbufs = []
    for px in (16, 22, 24, 32, 48, 64, 128, 256):
        path = os.path.join(ICON_DIR, "%s-%d.png" % (APP_ID, px))
        if os.path.exists(path):
            try:
                pixbufs.append(GdkPixbuf.Pixbuf.new_from_file(path))
            except GLib.Error:
                pass
    if pixbufs:
        Gtk.Window.set_default_icon_list(pixbufs)


def main():
    # WM_CLASS = (prgname, program class). The panel matches the window against
    # StartupWMClass in the .desktop file, so both halves need to be ours and
    # not "seal_pomodoro.py".
    GLib.set_prgname(APP_ID)
    Gdk.set_program_class(WM_CLASS)
    GLib.set_application_name(APP_NAME)
    install_window_icon()
    SealPomodoro()
    Gtk.main()


if __name__ == "__main__":
    main()
