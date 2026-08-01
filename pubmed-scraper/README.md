
# PubMed article scraper (pubmed_scraper.py)

An on-demand scraper that finds **new articles** on PubMed matching search terms
you define, and writes the results to **CSV and plain text** — each with the
**title**, **authors in APA style**, the **journal**, and a **link** to the
article.

It queries [NCBI's E-utilities](https://www.ncbi.nlm.nih.gov/books/NBK25501/) —
the official PubMed API, which indexes essentially every biomedical journal — so
it's more reliable and complete than scraping individual journal websites, and
it stays within NCBI's terms of use.

## Install

```bash
pip install -r requirements.txt
```

## Quick start

```bash
# Run every enabled search in searches.yaml, articles from the last 30 days.
python3 pubmed_scraper.py

# Just the single-cell search, last 2 weeks.
python3 pubmed_scraper.py --search scrnaseq --days 14

# A one-off query without editing the config.
python3 pubmed_scraper.py --query '"spatial transcriptomics"[Title/Abstract]' --days 7
```

Output is written to `output/pubmed_<timestamp>.csv` and `.txt`.

## Defining searches

Search terms live in **`searches.yaml`**, so you can add new topics later
without touching the code. Each entry's `query` is passed straight to PubMed and
supports the full [PubMed search syntax](https://pubmed.ncbi.nlm.nih.gov/help/)
(field tags like `[Title/Abstract]`, `[MeSH Terms]`, `[Journal]`; boolean
`AND`/`OR`/`NOT`; quoted phrases).

The file ships with ready-made examples, some disabled by default — flip
`enabled: true` to turn them on:

- **`scrnaseq`** — single-cell RNA sequencing (enabled).
- **`scrnaseq_immunology`** — scRNA-seq narrowed to immunology, via MeSH terms.
- **`proteomics`** — proteomics.
- a commented example that restricts a topic to specific journals.

To add your own, copy an entry and change the `name` and `query`. For example, a
proteomics-in-oncology watch:

```yaml
  - name: proteomics_oncology
    enabled: true
    query: >-
      proteomics[Title/Abstract]
      AND ("Neoplasms"[MeSH Terms] OR cancer[Title/Abstract])
```

## "New" articles and the seen-cache

By default the tool records which articles (PMIDs) it has already reported in a
small `.seen_pmids.json` file, so **repeat runs only surface genuinely new
papers**. Delete that file to reset, or use `--all` to report every match in the
date window regardless of history.

## Useful options

| Flag | Purpose |
|------|---------|
| `--search NAME` | Run only one named search (ignores its `enabled` flag). |
| `--query "..."` | Ad-hoc PubMed query instead of the config. |
| `--days N` | Look back N days (`0` = no date limit). |
| `--max N` | Cap results per search (default 200). |
| `--datetype` | `pdat` = publication date (default), `edat` = date added to PubMed. |
| `--format` | `csv`, `txt`, or `both` (default). |
| `--all` | Ignore the seen-cache; report everything in the window. |
| `--output-dir DIR` | Where to write output (default `output/`). |
| `--email` | Contact email for NCBI (or set `NCBI_EMAIL`). |
| `--api-key` | NCBI API key to raise the rate limit (or set `NCBI_API_KEY`). |

Run `python3 pubmed_scraper.py --help` for the full list.

## Notes on NCBI etiquette

- No API key is required. NCBI asks callers to identify themselves — set your
  `email` in `searches.yaml` or pass `--email`.
- The tool throttles itself to NCBI's limits (3 requests/second without a key,
  10 with one). If you have an [API key](https://www.ncbi.nlm.nih.gov/account/),
  pass `--api-key` or set `NCBI_API_KEY`.

## Automating it

It's a plain script, so you can schedule it — e.g. a weekly cron job:

```cron
0 8 * * 1  cd /path/to/tools && /usr/bin/python3 pubmed_scraper.py --days 7
```
