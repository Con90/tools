"""Self-contained HTML report."""

from __future__ import annotations

import base64
import datetime as dt
import json
from html import escape
from pathlib import Path

import numpy as np

from . import __version__
from .cycles import GRID
from .draw import still
from .export import status, summary_markdown
from .fitting import METRICS

CSS = """
:root{
  --page:#f4f3ef; --surface:#fcfcfb; --text:#0b0b0b; --text-2:#52514e; --muted:#7b7a75;
  --line:#e2e1dc; --grid:#ebeae5; --band:#e7e6e0; --series:#2a78d6; --series-band:rgba(42,120,214,.16);
  --good:#0ca30c; --warn:#b07800; --bad:#d03b3b; --chip:#efeee9;
}
@media (prefers-color-scheme: dark){
  :root:not([data-theme="light"]){
    --page:#121211; --surface:#1a1a19; --text:#f0efec; --text-2:#c3c2b7; --muted:#8f8e86;
    --line:#2e2e2b; --grid:#272724; --band:#383833; --series:#3987e5; --series-band:rgba(57,135,229,.22);
    --good:#3fbf3f; --warn:#fab219; --bad:#e66767; --chip:#262624;
  }
}
:root[data-theme="dark"]{
  --page:#121211; --surface:#1a1a19; --text:#f0efec; --text-2:#c3c2b7; --muted:#8f8e86;
  --line:#2e2e2b; --grid:#272724; --band:#383833; --series:#3987e5; --series-band:rgba(57,135,229,.22);
  --good:#3fbf3f; --warn:#fab219; --bad:#e66767; --chip:#262624;
}
*{box-sizing:border-box}
body{margin:0;background:var(--page);color:var(--text);font:15px/1.5 system-ui,-apple-system,"Segoe UI",sans-serif}
main{max-width:1000px;margin:0 auto;padding:28px 16px 64px}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:17px;margin:36px 0 12px}
.sub{color:var(--text-2);font-size:13px}
.card{background:var(--surface);border:1px solid var(--line);border-radius:10px;padding:16px 18px}
.grid2{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,420px),1fr));gap:14px}
.hero{display:grid;grid-template-columns:repeat(auto-fit,minmax(min(100%,180px),1fr));gap:12px;margin-top:20px}
.stat .k{color:var(--text-2);font-size:12px;text-transform:uppercase;letter-spacing:.04em}
.stat .v{font-size:26px;font-weight:650;font-variant-numeric:tabular-nums;margin-top:2px}
.stat .d{color:var(--muted);font-size:12px}
.rec{display:flex;gap:14px;align-items:flex-start;padding:12px 0;border-top:1px solid var(--line)}
.rec:first-child{border-top:0;padding-top:0}
.rec .area{min-width:110px;color:var(--text-2);font-size:13px;padding-top:2px}
.rec .act{font-weight:620}
.rec p{margin:2px 0 0;color:var(--text-2);font-size:14px}
.chip{display:inline-block;font-size:11px;padding:1px 8px;border-radius:99px;background:var(--chip);color:var(--text-2);margin-left:6px;vertical-align:2px;font-weight:500}
.tbl{overflow-x:auto}
table{border-collapse:collapse;width:100%;font-size:14px}
th{text-align:left;color:var(--text-2);font-weight:500;font-size:12px;padding:6px 8px;border-bottom:1px solid var(--line)}
td{padding:7px 8px;border-bottom:1px solid var(--line);vertical-align:middle}
td.num{font-variant-numeric:tabular-nums;white-space:nowrap}
.st{white-space:nowrap;font-size:13px}
.st.good{color:var(--good)} .st.fair,.st.warn{color:var(--warn)} .st.poor,.st.bad{color:var(--bad)}
.st.info{color:var(--text-2)}
.chart{position:relative}
.chart svg{width:100%;height:auto;display:block}
.chart .tip{position:absolute;pointer-events:none;background:var(--text);color:var(--surface);font-size:12px;padding:4px 8px;border-radius:6px;white-space:nowrap;transform:translate(-50%,-120%);opacity:0;transition:opacity .1s}
.chart h3{font-size:14px;margin:0 0 2px}
.chart .cap{color:var(--muted);font-size:12px;margin:0 0 6px}
svg text{fill:var(--muted);font-size:11px;font-family:inherit}
.ax{stroke:var(--line)} .gl{stroke:var(--grid)}
.mean{fill:none;stroke:var(--series);stroke-width:2;stroke-linejoin:round}
.sdb{fill:var(--series-band)} .refb{fill:var(--band)}
.refl{fill:var(--text-2)!important;font-size:10.5px!important}
.cross{stroke:var(--text-2);stroke-width:1;opacity:0}
.dot{fill:var(--series);stroke:var(--surface);stroke-width:2;opacity:0}
figure{margin:0}
figure img{width:100%;border-radius:8px;display:block;background:var(--band)}
figcaption{color:var(--text-2);font-size:13px;margin-top:6px}
video{width:100%;border-radius:8px;background:#000}
details summary{cursor:pointer;color:var(--text-2);font-size:13px;margin-top:8px}
pre{background:var(--chip);padding:12px;border-radius:8px;overflow-x:auto;font-size:12px;white-space:pre-wrap}
button{font:inherit;font-size:13px;padding:5px 12px;border-radius:7px;border:1px solid var(--line);background:var(--surface);color:var(--text);cursor:pointer}
ul.notes{margin:0;padding-left:18px;color:var(--text-2);font-size:14px}
.bar text{font-size:10px}
.metrics td:first-child{min-width:170px}
"""

JS = """
document.querySelectorAll('.chart').forEach(function(el){
  var svg=el.querySelector('svg'), d=JSON.parse(svg.dataset.curve), tip=el.querySelector('.tip');
  var cross=svg.querySelector('.cross'), dot=svg.querySelector('.dot'), hit=svg.querySelector('.hit');
  var vb=svg.viewBox.baseVal;
  function move(ev){
    var r=svg.getBoundingClientRect(), sx=(ev.clientX-r.left)*vb.width/r.width;
    var t=(sx-d.x0)/(d.x1-d.x0); if(t<0||t>1){hide();return;}
    var i=Math.round(t*(d.m.length-1)), m=d.m[i]; if(m===null){hide();return;}
    var x=d.x0+(d.x1-d.x0)*i/(d.m.length-1), y=d.y0+(d.y1-d.y0)*(m-d.lo)/(d.hi-d.lo);
    cross.setAttribute('x1',x);cross.setAttribute('x2',x);cross.style.opacity=1;
    dot.setAttribute('cx',x);dot.setAttribute('cy',y);dot.style.opacity=1;
    tip.textContent='Crank '+Math.round(d.g[i])+'\\u00b0 \\u2014 '+m.toFixed(1)+'\\u00b0 \\u00b1 '+(d.s[i]||0).toFixed(1);
    tip.style.left=(x*r.width/vb.width)+'px'; tip.style.top=(y*r.height/vb.height)+'px'; tip.style.opacity=1;
  }
  function hide(){cross.style.opacity=0;dot.style.opacity=0;tip.style.opacity=0;}
  hit.addEventListener('pointermove',move); hit.addEventListener('pointerleave',hide);
});
var cp=document.getElementById('copy');
if(cp){cp.addEventListener('click',function(){
  var t=document.getElementById('summary').textContent;
  (navigator.clipboard?navigator.clipboard.writeText(t):Promise.reject()).then(function(){cp.textContent='Copied';},function(){
    var r=document.createRange();r.selectNodeContents(document.getElementById('summary'));
    var s=getSelection();s.removeAllRanges();s.addRange(r);cp.textContent='Selected - press Ctrl+C';});
});}
"""

ICON = {"good": "✓", "fair": "▲", "poor": "✕", "in range": "✓",
        "below": "▼", "above": "▲", "n/a": "–"}


def _nice_step(span: float) -> float:
    for s in (2, 5, 10, 20, 25, 50):
        if span / s <= 6:
            return s
    return 100


def curve_svg(name: str, curve: dict, bands: list[tuple[float, float, str]]) -> str:
    W, H, L, R, T, B = 640, 230, 40, 12, 10, 38
    m, s = curve["mean"], curve["sd"]
    ok = np.isfinite(m)
    if not ok.any():
        return "<p class='sub'>No data.</p>"
    lo = float(np.nanmin(m - np.nan_to_num(s)))
    hi = float(np.nanmax(m + np.nan_to_num(s)))
    for b0, b1, _ in bands:
        if b1 >= lo - 15 and b0 <= hi + 15:
            lo, hi = min(lo, b0), max(hi, b1)
    pad = max(2.0, (hi - lo) * 0.08)
    lo, hi = lo - pad, hi + pad
    step = _nice_step(hi - lo)
    lo, hi = np.floor(lo / step) * step, np.ceil(hi / step) * step
    x0, x1, y0, y1 = L, W - R, H - B, T                    # y0 = bottom (value lo)
    X = lambda g: x0 + (x1 - x0) * g / 360
    Y = lambda v: y0 + (y1 - y0) * (v - lo) / (hi - lo)
    parts = [f'<svg viewBox="0 0 {W} {H}" role="img" aria-label="{escape(name)} by crank angle" ']
    data = {"g": GRID.tolist(), "m": [None if not np.isfinite(v) else round(float(v), 2) for v in m],
            "s": [None if not np.isfinite(v) else round(float(v), 2) for v in s],
            "x0": x0, "x1": x1, "y0": y0, "y1": y1, "lo": lo, "hi": hi}
    parts.append(f"data-curve='{json.dumps(data)}'>")
    for b0, b1, label in bands:
        if b1 < lo or b0 > hi:
            continue
        ya, yb = Y(min(b1, hi)), Y(max(b0, lo))
        parts.append(f'<rect class="refb" x="{x0}" y="{ya:.1f}" width="{x1 - x0}" height="{yb - ya:.1f}"/>')
        parts.append(f'<text class="refl" x="{x1 - 4}" y="{ya + 12:.1f}" text-anchor="end">{escape(label)}</text>')
    v = lo
    while v <= hi + 1e-9:
        parts.append(f'<line class="gl" x1="{x0}" x2="{x1}" y1="{Y(v):.1f}" y2="{Y(v):.1f}"/>'
                     f'<text x="{x0 - 6}" y="{Y(v) + 4:.1f}" text-anchor="end">{v:g}°</text>')
        v += step
    for g, lab in ((0, "0° top"), (90, "90° front"), (180, "180° bottom"),
                   (270, "270° back"), (360, "360°")):
        anchor = "start" if g == 0 else "end" if g == 360 else "middle"
        parts.append(f'<line class="ax" x1="{X(g):.1f}" x2="{X(g):.1f}" y1="{y0}" y2="{y0 + 4}"/>'
                     f'<text x="{X(g):.1f}" y="{y0 + 18}" text-anchor="{anchor}">{lab}</text>')
    parts.append(f'<line class="ax" x1="{x0}" x2="{x1}" y1="{y0}" y2="{y0}"/>')
    up = [(X(g), Y(mv + sv)) for g, mv, sv in zip(GRID, m, s) if np.isfinite(mv)]
    dn = [(X(g), Y(mv - sv)) for g, mv, sv in zip(GRID, m, s) if np.isfinite(mv)]
    pts = " ".join(f"{a:.1f},{b:.1f}" for a, b in up + dn[::-1])
    parts.append(f'<polygon class="sdb" points="{pts}"/>')
    line = " ".join(f"{X(g):.1f},{Y(mv):.1f}" for g, mv in zip(GRID, m) if np.isfinite(mv))
    parts.append(f'<polyline class="mean" points="{line}"/>')
    parts.append(f'<line class="cross" x1="0" x2="0" y1="{y1}" y2="{y0}"/><circle class="dot" r="4.5" cx="0" cy="0"/>')
    parts.append(f'<rect class="hit" x="{x0}" y="{y1}" width="{x1 - x0}" height="{y0 - y1}" fill="transparent"/>')
    parts.append("</svg>")
    return "".join(parts)


def curve_table(curve: dict) -> str:
    rows = "".join(
        f"<tr><td class='num'>{g:g}°</td><td class='num'>{curve['mean'][i]:.1f}</td>"
        f"<td class='num'>{curve['sd'][i]:.1f}</td></tr>"
        for i, g in enumerate(GRID) if g % 30 == 0 and np.isfinite(curve["mean"][i]))
    return (f"<details><summary>Table view</summary><div class='tbl'><table><tr><th>Crank</th>"
            f"<th>Mean</th><th>SD</th></tr>{rows}</table></div></details>")


def range_bar(value, p25, p75, rng) -> str:
    if value is None or rng is None:
        return ""
    lo = min(rng.lo, p25 if p25 is not None else value, value)
    hi = max(rng.hi, p75 if p75 is not None else value, value)
    pad = max(3.0, (hi - lo) * 0.15)
    lo, hi = lo - pad, hi + pad
    W, H = 150, 18
    X = lambda v: 4 + (W - 8) * (v - lo) / (hi - lo)
    out = [f'<svg class="bar" width="{W}" height="{H}" viewBox="0 0 {W} {H}" aria-hidden="true">',
           f'<rect class="refb" x="{X(rng.lo):.1f}" y="3" width="{X(rng.hi) - X(rng.lo):.1f}" height="12" rx="2"/>']
    if p25 is not None and p75 is not None:
        out.append(f'<line x1="{X(p25):.1f}" x2="{X(p75):.1f}" y1="9" y2="9" stroke="var(--series)" stroke-width="2"/>')
    out.append(f'<circle cx="{X(value):.1f}" cy="9" r="4.5" fill="var(--series)" stroke="var(--surface)" stroke-width="2"/></svg>')
    return "".join(out)


def _img(data: bytes) -> str:
    return "data:image/jpeg;base64," + base64.b64encode(data).decode()


def build(an, out: Path, overlay: Path | None) -> Path:
    s, sm = an.settings, an.summary
    knee = sm["knee_ext"]["median"]
    saddle = next((r for r in an.recommendations if r.area == "Saddle height"), None)
    when = dt.datetime.now().strftime("%Y-%m-%d %H:%M")
    src = Path(s["source"]).name if s["source"] else "keypoints"

    def fmt(v, d=1):
        return "–" if v is None or (isinstance(v, float) and not np.isfinite(v)) else f"{v:.{d}f}"

    hero = f"""
<div class="hero">
  <div class="card stat"><div class="k">Knee at full extension</div><div class="v">{fmt(knee)}°</div>
    <div class="d">flexion; target {an.ranges['knee_ext'].lo:g}–{an.ranges['knee_ext'].hi:g}°</div></div>
  <div class="card stat"><div class="k">Saddle height</div><div class="v" style="font-size:20px">{escape(saddle.action if saddle else '–')}</div>
    <div class="d">{escape(saddle.confidence + ' confidence' if saddle else '')}</div></div>
  <div class="card stat"><div class="k">Data quality</div><div class="v st {an.quality}">{ICON[an.quality]} {an.quality}</div>
    <div class="d">{len(an.rows)} strokes · {fmt(s['cadence_rpm'], 0)} rpm</div></div>
</div>"""

    recs = "".join(
        f"<div class='rec'><div class='area'>{escape(r.area)}</div><div><div class='act'>{escape(r.action)}"
        f"<span class='chip'>{escape(r.confidence)}</span></div><p>{escape(r.detail)}</p></div></div>"
        for r in an.recommendations)

    mrows = []
    for key, (label, unit, desc) in METRICS.items():
        m = sm[key]
        rng = an.ranges.get(key)
        st = status(m["median"], rng)
        cls = "good" if st == "in range" else "info" if st == "n/a" else "warn"
        ref = "–" if rng is None else f"{rng.lo:g}–{rng.hi:g}°"
        strength = "" if rng is None else f"<span class='chip'>{escape(rng.strength)}</span>"
        mrows.append(
            f"<tr><td>{escape(label)}<div class='sub'>{escape(desc)}</div></td>"
            f"<td class='num'>{fmt(m['median'])}°</td><td class='num'>±{fmt(m['sd'])}</td>"
            f"<td>{range_bar(m['median'], m['p25'], m['p75'], rng)}</td>"
            f"<td class='num'>{ref}{strength}</td>"
            f"<td class='st {cls}'>{ICON[st]} {st}</td></tr>")
    metrics = ("<div class='card tbl'><table class='metrics'><tr><th>Metric</th><th>Median</th><th>SD</th>"
               "<th>Strokes (dot = median, line = middle 50%) vs range</th><th>Reference</th><th>Status</th></tr>"
               + "".join(mrows) + "</table></div>")

    rk, rt, rh = an.ranges["knee_ext"], an.ranges["knee_top"], an.ranges["hip_closed"]
    charts = [
        ("Knee flexion", "knee", "0° = straight leg. Shaded: reference ranges for full extension and peak bend.",
         [(rk.lo, rk.hi, "full-extension range"), (rt.lo, rt.hi, "peak-bend range")]),
        ("Hip angle", "hip", "Shoulder–hip–knee. Smaller = more closed.",
         [(rh.lo, rh.hi, "most-closed range")]),
        ("Ankle angle", "ankle", "Knee–ankle–toe. Larger = toe pointed down.", []),
    ]
    chart_html = "".join(
        f"<div class='card chart'><h3>{t}</h3><p class='cap'>{escape(cap)} Line = mean of "
        f"{len(an.rows)} strokes, band = ±1 SD. Crank angle is estimated from the ankle path (±~15°). "
        f"Averaging rounds the peaks off slightly; the table uses each stroke's own peak.</p>"
        f"{curve_svg(t, an.curves[k], b)}<div class='tip'></div>{curve_table(an.curves[k])}</div>"
        for t, k, cap, b in charts)

    figs = ""
    if an.rows:
        med = np.median([r["knee_ext"] for r in an.rows])
        rep = min(range(len(an.rows)), key=lambda i: abs(an.rows[i]["knee_ext"] - med))
        r = an.rows[rep]
        ext_img, top_img = still(an, r["ext_index"]), still(an, r["top_index"])
        figs = f"""<div class="grid2">
<figure><img src="{_img(ext_img)}" alt="Rider at full knee extension with joint angles drawn"><figcaption>Full extension — stroke {rep + 1}
 (the most typical one), frame {int(an.track.frames[r['ext_index']])}. Knee flexion {r['knee_ext']:.1f}°.</figcaption></figure>
<figure><img src="{_img(top_img)}" alt="Rider at peak knee bend with joint angles drawn"><figcaption>Peak bend — same stroke,
 frame {int(an.track.frames[r['top_index']])}. Knee flexion {r['knee_top']:.1f}°.</figcaption></figure></div>"""

    video = ""
    if overlay and overlay.exists():
        video = (f"<h2>Tracking check</h2><div class='card'><video controls preload='metadata' src='{escape(overlay.name)}'></video>"
                 "<p class='sub'>Blue dots: raw model points. Amber: the cleaned skeleton used for every number in this "
                 "report. If the amber skeleton doesn't sit on your joints, don't trust the numbers.</p></div>")

    checks = "".join(
        f"<tr><td>{escape(c.name)}</td><td class='num'>{escape(c.value)}</td>"
        f"<td class='st {c.grade}'>{ICON[c.grade]} {c.grade}</td><td class='sub'>{escape(c.advice)}</td></tr>"
        for c in an.checks)
    notes = "".join(f"<li>{escape(n)}</li>" for n in an.notes)

    html = f"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>Bike fit — {escape(src)}</title><style>{CSS}</style></head><body><main>
<h1>Bike fit report</h1>
<div class="sub">{escape(src)} · {when} · {escape(s['side'])} side, rider facing {escape(s['facing'])} ·
 {s['fps']:.0f} fps · scale: {escape(an.scale.method)}</div>
{hero}
<h2>Recommendations</h2><div class="card">{recs}</div>
<h2>Measurements</h2>{metrics}
<h2>Through the pedal stroke</h2><div class="grid2">{chart_html}</div>
<h2>Key positions</h2>{figs}
{video}
<h2>Data quality</h2><div class="card tbl"><table><tr><th>Check</th><th>Value</th><th>Grade</th><th></th></tr>{checks}</table>
{('<h3 style="font-size:14px;margin:16px 0 6px">Notes</h3><ul class="notes">' + notes + '</ul>') if notes else ''}</div>
<h2>Ask an assistant</h2><div class="card"><p class="sub" style="margin-top:0">Paste this into a chat for a second opinion
on the numbers (also saved as summary.md). <button id="copy">Copy</button></p><pre id="summary">{escape(summary_markdown(an))}</pre></div>
<h2>How to read this</h2><div class="card"><ul class="notes">
<li>Only saddle height gets a millimetre recommendation; it is the one measure with an established dynamic range and a direct geometric link to an adjustment. Everything else is context.</li>
<li>Angles are 2D, from one side-on camera. Camera tilt or a camera not square to the bike distorts them. Level the phone and line it up with the crank axle.</li>
<li>Pose models place joints within a centimetre or two. Averaging across many strokes removes jitter but not a consistent offset; joint stickers and good light reduce it.</li>
<li>Change one thing at a time, ride it for a few days, re-film, and compare with <code>bike_fit.py compare</code>.</li>
<li>Pain, numbness, or an injury history beats any number here. See a professional fitter for those.</li>
</ul></div>
<p class="sub" style="margin-top:28px">bike-fit {__version__}</p>
</main><script>{JS}</script></body></html>"""
    path = out / "report.html"
    path.write_text(html)
    return path
