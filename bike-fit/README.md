# bike-fit

Bike fit analysis from a side-on video of you riding on a trainer. It tracks
your joints with a pose model, averages your knee, hip, ankle and upper-body
angles over every pedal stroke in the clip, and writes a report with a saddle
height recommendation in millimetres.

It measures; you decide. Only saddle height gets a numeric recommendation,
because knee extension is the one measure with an established dynamic range
and a direct geometric link to an adjustment. Everything else is reported
against rule-of-thumb ranges as context.

## Quick start

```bash
./run.sh demo                                # synthetic rider, no video needed
./run.sh analyze my_clip.mp4 --leg-mm 880    # your video
```

The first run creates `.venv`, installs dependencies, and downloads the pose
model (~30 MB) into `models/`. Needs Python 3.10+.

**Before filming, read [CAPTURE.md](CAPTURE.md).** Camera placement and
lighting matter more than anything in the code.

## What you get

Each run writes a folder under `output/`:

| File | What it is |
|---|---|
| `report.html` | The report: recommendations, measurements vs reference ranges, angle-through-the-stroke charts, annotated stills at full extension and peak bend, data-quality checks |
| `overlay.mp4` | Your video with raw (blue) and cleaned (amber) joints drawn on. **Watch this first.** If the skeleton isn't on your joints, the numbers are wrong |
| `summary.md` | The numbers as compact text, to paste into a chat with an AI assistant for a second opinion |
| `metrics.json` | Everything, machine-readable |
| `strokes.csv` | One row per pedal stroke |
| `curves.csv` | Mean and SD of each angle across 0–360° of crank angle |
| `keypoints.csv` | Raw per-frame joint positions. Re-analyse from this without re-running the pose model |

## Commands

```bash
./run.sh analyze VIDEO --leg-mm MM [options]
./run.sh analyze output/.../keypoints.csv --leg-mm MM     # re-analyse, skips the pose step
./run.sh compare output/before output/after               # after you change something
./run.sh demo
```

Useful options for `analyze`:

| Option | |
|---|---|
| `--leg-mm` | Greater trochanter to lateral malleolus, standing (see CAPTURE.md). Without it you get directions but not millimetres |
| `--start`, `--end` | Seconds to analyse (skip getting settled) |
| `--side` | `left` / `right` side facing the camera (default auto) |
| `--style` | `endurance` / `road` / `aggressive` / `tt`. Only changes the torso reference range |
| `--model` | `lite` / `full` / `heavy` (default heavy, the most accurate) |
| `--roi x,y,w,h`, `--no-auto-crop` | The tool crops to the rider automatically; override if it gets it wrong |
| `--cutoff` | Low-pass filter in Hz (default 8) |
| `--mm-per-px`, `--ref x1,y1,x2,y2,mm` | Other ways to set the scale |

## How it works

```
video ─► pose model ─► keypoints.csv ─► clean ─► angles ─► pedal strokes ─► metrics ─► report
         (MediaPipe)                     │                  │
                                         │                  └ each stroke resampled to 0–360°
                                         └ pick near side, fix left/right leg swaps,
                                           drop spikes, fill short gaps, low-pass filter
```

- **Pose:** MediaPipe Pose Landmarker (heavy). A quick first pass with the lite
  model finds the rider, then the main pass runs on a square crop around them.
  The model squashes each frame to a small input, so cropping noticeably
  improves joint placement.
- **Leg swaps:** the model sometimes labels your far leg as your near leg. The
  tool picks the labelling that makes the knee/ankle path smoothest, solved
  exactly over the whole clip by dynamic programming, so one bad frame can't
  derail it.
- **Spikes:** each point is predicted from its neighbours (a cubic, falling
  back to simpler predictors next to gaps); outliers are dropped.
- **Filter:** zero-lag 4th-order Butterworth at 8 Hz. The textbook 6 Hz
  flattened knee peaks by ~0.5° at 100 rpm in testing.
- **Strokes:** crank angle is estimated from the loop the ankle traces (no
  pedal tracking, so ±~15°). Headline numbers come from each stroke's own
  extreme, which doesn't depend on that estimate.
- **Saddle height:** from the tracked thigh and shank lengths, the change in
  hip-to-ankle distance needed to move knee flexion at full extension into
  33–43° (the dynamic range from Ferrer-Roca et al. 2012). Capped at 10 mm per
  change.

## Angle conventions

Fitters disagree on these, and a reference range means nothing without its
convention:

| Angle | Definition |
|---|---|
| Knee flexion | 180 − included hip–knee–ankle angle (0 = straight leg) |
| Hip | included shoulder–hip–knee angle (smaller = more closed) |
| Ankle | included knee–ankle–toe angle (larger = toe pointed down) |
| Torso | hip→shoulder line above horizontal |
| Shoulder | included hip–shoulder–elbow angle |
| Elbow | included shoulder–elbow–wrist angle (180 = locked) |

Note that dynamic (video) knee angles read 5–10° more flexed than static
goniometer methods such as Holmes (25–35°). Don't mix the two.

## How accurate is it?

**What's verified** (tests, synthetic rider with exactly known angles):

- Knee flexion at full extension recovered within 0.4° on clean data and
  within 1° with 3 px tracking noise, dropouts, spikes and leg swaps, from
  75–105 rpm.
- Closed loop: set the saddle 11 mm low, follow the recommendation, and the
  knee lands back in range.
- The pose model's coordinates map correctly to the frame, with and without
  cropping (checked on a real photo).

**What isn't verified yet:** accuracy on real footage of a real rider. Pose
models place joints within a centimetre or two, and a consistent offset at
the hip or knee doesn't average away. Expect a few degrees of error until
you've checked it against a hand measurement (CAPTURE.md, step 7). That
check is the most important thing to do before moving your saddle.

**What a side view can't see:** saddle fore/aft (needs the pedal spindle
tracked), cleat position, knee tracking and hip rock (need a front view),
saddle pressure, or anything about comfort. Pain, numbness or an injury
history beats any number here; see a professional fitter for those.

## Troubleshooting

- **`libEGL.so.1: cannot open shared object file`**: MediaPipe needs the
  system graphics libraries. On Debian/Ubuntu: `sudo apt install libegl1 libgles2`.
- **"found a person in only N% of frames"**: the rider is too small, backlit,
  or partly out of frame. See CAPTURE.md.
- **The skeleton in `overlay.mp4` is on the wrong leg for a stretch**: rare
  after correction, but if it happens, better light or a contrasting sock on
  the near leg helps the model tell your legs apart.

## Development

```bash
.venv/bin/pip install pytest
.venv/bin/python -m pytest
```

Code layout (`bikefit/`):

| Module | |
|---|---|
| `pose.py` | Video → keypoints (the only module that touches the model) |
| `landmarks.py` | Keypoint track data model and CSV I/O |
| `clean.py` | Side selection, leg-swap fixing, spike rejection, gap filling, filtering |
| `angles.py` | Angle definitions |
| `cycles.py` | Pedal-stroke segmentation and crank-angle resampling |
| `fitting.py` | Metrics, reference ranges, data-quality grading, recommendations |
| `analysis.py` | Ties the above together |
| `report.py`, `draw.py`, `export.py` | HTML report, overlays, JSON/CSV/markdown outputs |
| `synth.py` | Synthetic rider for tests and the demo |

Possible next steps: a coloured-sticker tracker as an alternative to the pose
model (more precise joint centres), pedal-spindle tracking for crank angle and
saddle fore/aft, and a front-view mode for knee tracking.
