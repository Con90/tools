#!/usr/bin/env python3
"""bike_fit.py - bike fit analysis from a side-on video of you on a trainer.

  analyze VIDEO_OR_KEYPOINTS   measure joint angles over many pedal strokes and
                               write an HTML report with recommendations
  compare BEFORE AFTER         compare two runs (metrics.json files or output folders)
  demo                         run the whole pipeline on a synthetic rider

Examples:
  ./run.sh analyze ride.mp4 --leg-mm 880
  ./run.sh analyze output/ride_2026-10-19_1200/keypoints.csv --leg-mm 880   # re-analyse, no pose step
  ./run.sh compare output/before output/after
"""

from __future__ import annotations

import argparse
import datetime as dt
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def _floats(text: str, n: int) -> tuple[float, ...]:
    vals = tuple(float(v) for v in text.split(","))
    if len(vals) != n:
        raise argparse.ArgumentTypeError(f"expected {n} comma-separated numbers")
    return vals


def cmd_analyze(args) -> int:
    from bikefit.analysis import analyse
    from bikefit.draw import overlay_video
    from bikefit.export import write_all
    from bikefit.landmarks import load_csv, save_csv
    from bikefit.report import build

    src = Path(args.input)
    if not src.exists():
        print(f"Not found: {src}", file=sys.stderr)
        return 2
    stamp = dt.datetime.now().strftime("%Y-%m-%d_%H%M")
    out = Path(args.out) if args.out else HERE / "output" / f"{src.stem}_{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    if src.suffix.lower() == ".csv":
        track = load_csv(src)
        if args.video:
            track.source = str(Path(args.video).resolve())
        print(f"Loaded {track.n} frames of keypoints from {src}")
    else:
        from bikefit.pose import extract_keypoints
        roi = (tuple(int(v) for v in _floats(args.roi, 4)) if args.roi
               else None if args.no_auto_crop else "auto")
        print(f"Running pose model ({args.model}) on {src} ...")
        track = extract_keypoints(src.resolve(), variant=args.model, start=args.start,
                                  end=args.end, roi=roi)
        save_csv(track, out / "keypoints.csv")
        print(f"  {track.n} frames, saved keypoints.csv")

    ref = _floats(args.ref, 5) if args.ref else None
    an = analyse(track, side=args.side, cutoff=args.cutoff, leg_mm=args.leg_mm,
                 mm_per_px=args.mm_per_px, ref=ref, style=args.style)
    write_all(an, out)
    overlay = None
    if not args.no_overlay and track.source and Path(track.source).exists():
        print("Writing tracking-check overlay video ...")
        overlay = overlay_video(an, out / "overlay.mp4")
    report = build(an, out, overlay)

    s = an.summary
    print()
    print(f"Data quality: {an.quality.upper()}   ({len(an.rows)} strokes, "
          f"{an.settings['cadence_rpm']:.0f} rpm, {an.settings['side']} side)")
    for c in an.checks:
        if c.grade != "good":
            print(f"  ! {c.name}: {c.value} - {c.advice}")
    k = s["knee_ext"]
    if k["median"] is not None:
        print(f"Knee flexion at full extension: {k['median']:.1f} deg (SD {k['sd']:.1f}), "
              f"target {an.ranges['knee_ext'].lo:g}-{an.ranges['knee_ext'].hi:g}")
    print()
    for r in an.recommendations:
        if r.confidence != "info" or r.area == "Data quality":
            print(f"- {r.area}: {r.action} [{r.confidence}]")
    for n in an.notes:
        print(f"  note: {n}")
    print()
    print(f"Report:  {report}")
    print(f"Folder:  {out}")
    if overlay:
        print("Watch overlay.mp4 first: if the skeleton doesn't sit on your joints, the numbers are wrong.")
    return 0


def cmd_compare(args) -> int:
    from bikefit.export import compare

    def find(p: str) -> Path:
        path = Path(p)
        return path / "metrics.json" if path.is_dir() else path

    print(compare(find(args.before), find(args.after)))
    return 0


def cmd_demo(args) -> int:
    from bikefit.landmarks import save_csv
    from bikefit.synth import Rider, make_track, render_video, truth

    out = Path(args.out) if args.out else HERE / "output" / "demo"
    out.mkdir(parents=True, exist_ok=True)
    rider = Rider(saddle=714, seconds=20)
    video = out / "synthetic_rider.mp4"
    print("Rendering a synthetic rider (saddle deliberately ~8 mm low) ...")
    render_video(rider, str(video))
    track = make_track(rider, noise_px=2.5, dropout=0.02, swaps=0.005, swap_runs=1, spikes=0.005)
    track.source = str(video)
    save_csv(track, out / "keypoints.csv")
    t = truth(rider)
    print(f"True knee flexion at full extension: {t['knee_ext']:.1f} deg. Leg length {rider.leg:g} mm.")
    ns = argparse.Namespace(input=str(out / "keypoints.csv"), out=str(out), video=None, side="auto",
                            cutoff=8.0, leg_mm=rider.leg, mm_per_px=None, ref=None, style="road",
                            no_overlay=args.no_overlay, model=None, roi=None, no_auto_crop=False,
                            start=None, end=None)
    return cmd_analyze(ns)


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="cmd", required=True)

    a = sub.add_parser("analyze", aliases=["analyse"], help="analyse a video or keypoints.csv")
    a.add_argument("input", help="video file (.mp4/.mov/...) or a keypoints.csv from an earlier run")
    a.add_argument("--leg-mm", type=float, help="your leg length in mm: bony bump on the side of the "
                   "hip (greater trochanter) to the ankle bone (lateral malleolus), standing. "
                   "Needed for millimetre recommendations")
    a.add_argument("--side", choices=["auto", "left", "right"], default="auto",
                   help="body side facing the camera (default: auto)")
    a.add_argument("--style", choices=["endurance", "road", "aggressive", "tt"], default="road",
                   help="riding position goal; only changes the torso reference range")
    a.add_argument("--model", choices=["lite", "full", "heavy"], default="heavy",
                   help="pose model size; heavy is most accurate (default)")
    a.add_argument("--start", type=float, help="start time in seconds (skip the warm-up)")
    a.add_argument("--end", type=float, help="end time in seconds")
    a.add_argument("--roi", help="x,y,w,h crop in pixels (default: found automatically)")
    a.add_argument("--no-auto-crop", action="store_true",
                   help="run the pose model on the full frame instead of a crop around the rider")
    a.add_argument("--cutoff", type=float, default=8.0, help="low-pass filter cutoff, Hz (default 8)")
    a.add_argument("--mm-per-px", type=float, help="known image scale, instead of --leg-mm")
    a.add_argument("--ref", help="x1,y1,x2,y2,mm: two image points a known distance apart in the "
                   "bike's plane, instead of --leg-mm")
    a.add_argument("--video", help="with a keypoints.csv input: the video to draw stills/overlay on")
    a.add_argument("--out", help="output folder (default: output/<name>_<date>)")
    a.add_argument("--no-overlay", action="store_true", help="skip the tracking-check overlay video")
    a.set_defaults(func=cmd_analyze)

    c = sub.add_parser("compare", help="compare two runs")
    c.add_argument("before")
    c.add_argument("after")
    c.set_defaults(func=cmd_compare)

    d = sub.add_parser("demo", help="run on a synthetic rider")
    d.add_argument("--out")
    d.add_argument("--no-overlay", action="store_true")
    d.set_defaults(func=cmd_demo)

    args = p.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.path.insert(0, str(HERE))
    sys.exit(main())
