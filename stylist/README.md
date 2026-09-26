# Stylist

A personal styling tool that runs on your own computer. Tell it your usual
sizes (or your body measurements), add the size charts of brands you buy from,
and it tells you which size to pick in each brand, with UK / EU / US
equivalents, how each measurement will feel (fits, snug, roomy, tight…), and
when you're between sizes. Covers clothing and shoes, women's and men's.

It also finds your **colour palette**: upload photos of your face and it
measures your skin, hair and eye colours, works out your seasonal colour type
(one of 12) and shows the colours, neutrals and metals that suit you.

And it gives **style advice**: your body shape and proportions with what to
look for and what's harder to wear, tips from your colouring (contrast,
fabrics, prints), and optionally a personal style brief written by Claude,
with style directions, outfit formulas in your palette and a shopping list.

Planned next:

1. **Product search:** find clothes through a shopping search API, ranked by
   fit score and palette match.
2. **Virtual try-on:** see found items on your photo via a hosted try-on model.

## Run it

```bash
./run.sh
```

The first run creates a virtual environment and installs dependencies. The app
then opens at <http://127.0.0.1:8765>. It only listens on your own machine;
your profiles and charts are saved in `data/stylist.db`.

Needs Python 3.10+. The first run downloads about 250 MB of packages (mostly
MediaPipe and OpenCV, used for colour analysis). The first photo you analyse
downloads two small face models (~20 MB) into `data/models`. After that,
everything runs offline.

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

4. **Colours:** add 3–5 photos of your face (daylight by a window is best;
   see *Tips for good photos*). For each photo the app:
   - finds the face and places sample points on the cheeks, forehead,
     irises and hair (shown as dots when you click *Adjust*);
   - checks the whites of the eyes for coloured light and warns if the
     lighting is too warm or too blue.

   In *Adjust* you can re-pick any colour by clicking on the photo, or mark
   something truly white (paper, a white shirt) to correct the lighting.
   The result shows your season, how you measured on three scales (cool ↔
   warm, light ↔ deep, soft ↔ bright), the closest other seasons, and your
   palette (click a swatch to copy its hex code). *Compare side by side*
   puts your face on colours from your top two seasons, which is the best way
   to settle a close call. If your hair is dyed, set your natural hair colour
   under *Adjust*; if you already know your season, you can set it there too.

   Photos never leave your computer; they're stored in `data/photos`.

5. **Style:** shows your body shape (from your measurements, or estimated
   from your usual sizes; you can override it), what to look for and what's
   harder to wear, proportion tips (petite, tall, leg length) and tips from
   your colour analysis. Fill in *About you* (lifestyle, style words, budget,
   likes and dislikes), then press *Write my brief* for a personal style brief
   from Claude. Each shopping-list item links to a shopping search.

   The brief needs an [Anthropic API key](https://console.anthropic.com/settings/keys):
   paste it into the app (saved only in `data/settings.json`) or set
   `ANTHROPIC_API_KEY` before starting. Each brief costs roughly $0.10–0.20.
   Claude is sent your shape, proportions, colour season, palette and what you
   wrote in *About you*. Your raw measurements are not sent, and a photo is
   sent only if you tick *Include a photo*. Everything else in the app works
   without a key.

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

### How colours are analysed

- **Sampling:** MediaPipe's Face Landmarker (478 points, including the
  irises) places the sample areas. Its multiclass segmenter labels hair and
  face skin, so the skin samples stay on skin. Within each area, the darkest
  and brightest pixels (shadows, shine, catch-lights) are dropped, and the
  rest are averaged in linear RGB.
- **White reference:** marking something white applies a von Kries
  correction, which scales each colour channel so that point becomes neutral.
- **Combining photos:** colours are converted to CIELAB, and each feature
  takes the median across your included photos.
- **Three scores** from −1 to +1:
  - *Warmth:* skin hue angle (pink ↔ golden), how golden the hair is, and
    eye colour.
  - *Depth:* hair, skin and eye lightness.
  - *Clarity:* how vivid the eyes are, hair/skin contrast, and how
    saturated the hair is.
- **Choosing the season:** each of the 12 seasons sits at a point in that
  3D space, and the nearest ones are shown with a match percentage.

This is a heuristic. Its thresholds are set from typical skin and hair
colour ranges, not trained on labelled data. Lighting, make-up and dyed hair
all move the numbers, which is why several photos, the white reference and
the side-by-side comparison help.

### How body shape is worked out

- **Women's shapes** follow the FFIT method (Simmons, Istook & Devarajan,
  2004), which compares bust, waist and hips. FFIT's "bottom hourglass" is
  shown as a pear with a defined waist. An *apple* shape is added for when
  the waist is at least 90% of both bust and hips.
- **Men's shapes** use the chest-to-waist drop: inverted triangle (≥ 20 cm),
  trapezoid, rectangle, triangle (hips wider than chest) and oval (waist ≥
  chest).
- **The brief** uses Claude Opus 5 with a JSON schema, so the response always
  has the same structure. A server-side refusal fallback is on, so if the
  model declines a request, it's re-run on a backup model rather than failing.

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
| `app/colour.py` | sRGB ↔ CIELAB, white balance |
| `app/face.py` | Face landmarks, hair/skin segmentation and colour sampling (MediaPipe) |
| `app/seasons.py` | Warmth/depth/clarity scores, 12-season ranking, palettes |
| `app/colour_api.py` | Photo upload, sample picking and colour summary endpoints |
| `app/body.py` | Body shape, proportions and style guidance |
| `app/brief.py` | Claude style brief: prompt, schema, API key storage |
| `app/style_api.py` | Style guide, preferences and brief endpoints |
| `app/main.py` | FastAPI routes; serves the front end |
| `static/` | Single-page front end (plain HTML/CSS/JS, no build step) |
