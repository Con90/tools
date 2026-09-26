# Stylist

A personal styling tool that runs on your own computer. Tell it your usual
sizes (or your body measurements), add the size charts of brands you buy from,
and it tells you which size to pick in each brand, with UK / EU / US
equivalents, how each measurement will feel (fits, snug, roomy, tight…), and
when you're between sizes. Covers clothing and shoes, women's and men's.

This is **phase 1** (sizing). Planned next:

1. **Colour palette:** upload a photo; skin, eye and hair colours are measured
   and mapped to a seasonal colour palette.
2. **Style suggestions:** body proportions plus a photo → style directions and
   cuts to look for (via the Claude API).
3. **Product search:** find clothes through a shopping search API, ranked by
   fit score and palette match.
4. **Virtual try-on:** see found items on your photo via a hosted try-on model.

## Run it

```bash
./run.sh
```

The first run creates a virtual environment and installs dependencies. The app
then opens at <http://127.0.0.1:8765>. It only listens on your own machine;
your profiles and charts are saved in `data/stylist.db`.

Needs Python 3.10+.

## Using it

1. **My profile:** choose women's or men's clothing (you can also include
   the other section), your preferred fit, and one of two ways to describe
   your size:
   - **Quick, my usual sizes:** pick what you normally buy for tops,
     trousers (with leg length), dresses and shoes, in UK, EU, US or S/M/L
     (waist W-sizes for men's trousers). Measurements are estimated from these
     and results are marked *est.*
   - **Detailed, my measurements:** enter what you've measured (cm or
     inches; toggle top right). Anything left blank is filled in from your
     usual sizes, but those estimates only nudge the choice; they never
     override a real measurement or turn a fit "poor" on their own. Expand
     *How to measure* for tips, including foot length.
2. **Size charts:** the app starts with *approximate, generic* charts
   (women's UK 4–24, men's XS–XXXL and W28–W40, shoes by foot length) so you
   can try it straight away. Add the real charts of the brands you buy from:
   open the brand's size guide and copy the **body measurements** into a new
   chart, and say which system its size labels use (UK, EU, US, letters,
   waist inches). Type ranges like `86-91` or single values. Trousers can have
   leg lengths (Short/Regular/Long, L30/L32…) matched on inside leg; shoe
   charts use foot length.
3. **Find my size:** pick a garment type and see the best size per brand,
   best-fitting brands first, with its equivalents in other systems
   (e.g. *UK 12 · EU 40 · US 8 · M*).

### How sizes are chosen

- Size charts list the *body* measurements each size is designed for. Every
  size is scored by how far your measurements fall outside its ranges, with
  the key measurements for that garment weighted most. For example, chest
  counts most for tops, and waist and hips for trousers.
- **Fit preference:** *slim* sizes down sooner (2 cm tolerance); *relaxed*
  sizes up sooner (3 cm extra room). It only applies to girths, not lengths.
- **Between sizes:** when the runner-up is nearly as good, it's shown too.
- **Shoes** are matched on foot length with millimetre tolerance. UK size
  = 3 × last length (in) − 25, EU = 1.5 × last length (cm), with the last
  ~1.5 cm longer than the foot; US = UK + 1 (men) or + 2 (women).
- **Conversions** follow common high-street conventions (women's EU = UK + 28,
  US = UK − 4; men's EU ≈ chest cm ÷ 2, trouser EU = waist inches + 16).
  Brands vary, which is why a real brand chart always beats a conversion.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```

| Path | What it is |
|------|------------|
| `app/sizing.py` | Matching logic (pure functions, no I/O) |
| `app/conversions.py` | UK / EU / US / letter / waist and shoe size conversions |
| `app/estimate.py` | Turns usual sizes into estimated measurements (quick mode) |
| `app/db.py` | SQLite storage and migrations; seeds `app/starter_charts.json` |
| `app/main.py` | FastAPI routes; serves the front end |
| `static/` | Single-page front end (plain HTML/CSS/JS, no build step) |
