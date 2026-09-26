# Stylist

A personal styling tool that runs on your own computer. Enter your body
measurements once, add the size charts of brands you buy from, and it tells you
which size to pick in each brand, how each measurement will feel (fits, snug,
roomy, tight…), and when you're between sizes.

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

1. **My profile:** enter your measurements (cm or inches; toggle top right),
   your preferred fit, and whether to shop womenswear, menswear or both.
   Expand *How to measure* for tips. Only fill in what you have; each
   garment type uses the measurements that matter for it.
2. **Size charts:** the app starts with a few *approximate, generic* charts
   so you can try it straight away. Replace them with the real charts of the
   brands you buy from: open the brand's size guide and copy the **body
   measurements** into a new chart. Type ranges like `86-91` or single values.
   Trousers can have leg lengths (Short/Regular/Long, L30/L32…) matched on
   inside leg.
3. **Find my size:** pick a garment type and see the best size per brand,
   best-fitting brands first.

### How sizes are chosen

- Size charts list the *body* measurements each size is designed for. Every
  size is scored by how far your measurements fall outside its ranges, with
  the key measurements for that garment weighted most. For example, chest
  counts most for tops, and waist and hips for trousers.
- **Fit preference:** *slim* sizes down sooner (2 cm tolerance); *relaxed*
  sizes up sooner (3 cm extra room). It only applies to girths, not lengths.
- **Between sizes:** when the runner-up is nearly as good, it's shown too.

## Development

```bash
pip install -r requirements-dev.txt
python -m pytest
```

| Path | What it is |
|------|------------|
| `app/sizing.py` | Matching logic (pure functions, no I/O) |
| `app/db.py` | SQLite storage; seeds `app/starter_charts.json` on first run |
| `app/main.py` | FastAPI routes; serves the front end |
| `static/` | Single-page front end (plain HTML/CSS/JS, no build step) |
