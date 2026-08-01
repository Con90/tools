#!/usr/bin/env python3
"""
pubmed_scraper.py — On-demand scraper for new PubMed/journal articles.

Queries NCBI's E-utilities (the official PubMed API, covering ~all biomedical
journals) for recent articles matching one or more configurable searches, and
writes results to CSV and/or plain text. Each result includes the title, the
author list formatted in APA style, the journal, and a link to the article.

Search terms live in a YAML config file (searches.yaml by default), so new
searches — e.g. proteomics, or scRNA-seq restricted to immunology — can be
added later without touching this script. You can also run a one-off query
straight from the command line with --query.

Examples
--------
    # Run every enabled search in searches.yaml, articles from the last 30 days
    python3 pubmed_scraper.py

    # Run just one named search from the config, last 14 days
    python3 pubmed_scraper.py --search scrnaseq --days 14

    # Ad-hoc query without editing the config
    python3 pubmed_scraper.py --query '"single cell RNA sequencing"[Title/Abstract]' --days 7

    # Report everything in the window, ignoring the "already seen" cache
    python3 pubmed_scraper.py --all

Notes
-----
* No API key is required, but NCBI asks that you identify yourself. Set the
  search's `email` in the config (or --email / NCBI_EMAIL env var). If you have
  an NCBI API key, set it via --api-key or the NCBI_API_KEY env var to raise
  the rate limit from 3 to 10 requests/second.
* By default the tool remembers which PMIDs it has already reported (in a small
  JSON cache) so repeat runs only surface genuinely new articles. Use --all to
  disable this and report every match in the date window.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import sys
import time
import xml.etree.ElementTree as ET
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

import requests

try:
    import yaml
except ImportError:  # pragma: no cover - yaml is expected to be installed
    yaml = None

EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
DEFAULT_CONFIG = "searches.yaml"
DEFAULT_OUTPUT_DIR = "output"
DEFAULT_CACHE_FILE = ".seen_pmids.json"
TOOL_NAME = "pubmed_scraper"


# --------------------------------------------------------------------------- #
# Data model
# --------------------------------------------------------------------------- #
@dataclass
class Article:
    pmid: str
    title: str
    authors: list[dict] = field(default_factory=list)  # {last, fore, initials}
    journal: str = ""
    year: str = ""
    volume: str = ""
    issue: str = ""
    pages: str = ""
    doi: str = ""
    pub_date: str = ""

    @property
    def pubmed_url(self) -> str:
        return f"https://pubmed.ncbi.nlm.nih.gov/{self.pmid}/"

    @property
    def url(self) -> str:
        """Best link to the article: DOI resolver if we have one, else PubMed."""
        if self.doi:
            return f"https://doi.org/{self.doi}"
        return self.pubmed_url

    @property
    def apa_authors(self) -> str:
        return format_authors_apa(self.authors)

    def apa_citation(self) -> str:
        """A compact APA-style reference for the plain-text report."""
        parts = []
        authors = self.apa_authors
        if authors:
            parts.append(authors)
        if self.year:
            parts.append(f"({self.year}).")
        if self.title:
            title = self.title if self.title.endswith(".") else self.title + "."
            parts.append(title)
        journal_bit = self.journal
        if journal_bit:
            if self.volume:
                journal_bit += f", {self.volume}"
                if self.issue:
                    journal_bit += f"({self.issue})"
            if self.pages:
                journal_bit += f", {self.pages}"
            parts.append(journal_bit + ".")
        if self.doi:
            parts.append(f"https://doi.org/{self.doi}")
        return " ".join(parts)


# --------------------------------------------------------------------------- #
# APA author formatting
# --------------------------------------------------------------------------- #
def _initials(fore: str, initials: str) -> str:
    """Return APA-style initials, e.g. 'Jane Q' -> 'J. Q.'."""
    source = initials or fore
    if not source:
        return ""
    # `initials` from PubMed is like "JQ"; `fore` is like "Jane Q".
    if initials:
        letters = [c for c in initials if c.isalpha()]
    else:
        letters = [chunk[0] for chunk in fore.split() if chunk]
    return " ".join(f"{c.upper()}." for c in letters)


def _one_author_apa(author: dict) -> str:
    last = (author.get("last") or "").strip()
    inits = _initials(author.get("fore", ""), author.get("initials", ""))
    collective = (author.get("collective") or "").strip()
    if not last and collective:
        return collective
    if not last:
        return inits
    if inits:
        return f"{last}, {inits}"
    return last


def format_authors_apa(authors: list[dict]) -> str:
    """
    Format an author list per APA 7th edition:
      * 1 author:            Smith, J. A.
      * 2-20 authors:        comma-separated, ampersand before the last
      * 21+ authors:         first 19, ellipsis, then the final author
    """
    names = [_one_author_apa(a) for a in authors]
    names = [n for n in names if n]
    if not names:
        return ""
    if len(names) == 1:
        return names[0]
    if len(names) <= 20:
        return ", ".join(names[:-1]) + ", & " + names[-1]
    # 21 or more: list first 19, ellipsis, final author.
    return ", ".join(names[:19]) + ", ... " + names[-1]


# --------------------------------------------------------------------------- #
# NCBI E-utilities client
# --------------------------------------------------------------------------- #
class PubMedClient:
    def __init__(self, email: str = "", api_key: str = "", tool: str = TOOL_NAME,
                 timeout: int = 30, max_retries: int = 4):
        self.email = email
        self.api_key = api_key
        self.tool = tool
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": f"{tool}/1.0"})
        # NCBI rate limit: 3 req/s without a key, 10 with one.
        self._min_interval = 0.11 if api_key else 0.34
        self._last_request = 0.0

    def _common_params(self) -> dict:
        params = {"tool": self.tool}
        if self.email:
            params["email"] = self.email
        if self.api_key:
            params["api_key"] = self.api_key
        return params

    def _throttle(self) -> None:
        elapsed = time.time() - self._last_request
        if elapsed < self._min_interval:
            time.sleep(self._min_interval - elapsed)

    def _get(self, endpoint: str, params: dict) -> requests.Response:
        url = f"{EUTILS}/{endpoint}"
        merged = {**self._common_params(), **params}
        backoff = 2.0
        last_exc: Exception | None = None
        for attempt in range(self.max_retries):
            self._throttle()
            try:
                resp = self.session.get(url, params=merged, timeout=self.timeout)
                self._last_request = time.time()
                # 429 (rate limit) and 5xx are worth retrying.
                if resp.status_code == 429 or resp.status_code >= 500:
                    raise requests.HTTPError(f"HTTP {resp.status_code}")
                resp.raise_for_status()
                return resp
            except (requests.RequestException, requests.HTTPError) as exc:
                last_exc = exc
                if attempt < self.max_retries - 1:
                    time.sleep(backoff)
                    backoff *= 2
        raise RuntimeError(f"NCBI request to {endpoint} failed after "
                           f"{self.max_retries} attempts: {last_exc}")

    def esearch(self, query: str, days: int | None, retmax: int,
                datetype: str = "pdat") -> list[str]:
        """Return PMIDs matching `query`, optionally limited to the last `days`."""
        params = {
            "db": "pubmed",
            "term": query,
            "retmax": str(retmax),
            "retmode": "json",
            "sort": "date",
        }
        if days and days > 0:
            params["reldate"] = str(days)
            params["datetype"] = datetype
        resp = self._get("esearch.fcgi", params)
        data = resp.json()
        return data.get("esearchresult", {}).get("idlist", [])

    def efetch(self, pmids: list[str]) -> list[Article]:
        """Fetch full records for the given PMIDs and parse them."""
        articles: list[Article] = []
        # efetch handles large batches, but keep them modest to stay polite.
        for batch in _chunks(pmids, 200):
            params = {
                "db": "pubmed",
                "id": ",".join(batch),
                "rettype": "abstract",
                "retmode": "xml",
            }
            resp = self._get("efetch.fcgi", params)
            articles.extend(parse_pubmed_xml(resp.content))
        return articles


def _chunks(seq: list, size: int) -> Iterable[list]:
    for i in range(0, len(seq), size):
        yield seq[i:i + size]


# --------------------------------------------------------------------------- #
# XML parsing
# --------------------------------------------------------------------------- #
def _text(el: ET.Element | None) -> str:
    if el is None:
        return ""
    return "".join(el.itertext()).strip()


def parse_pubmed_xml(xml_bytes: bytes) -> list[Article]:
    root = ET.fromstring(xml_bytes)
    articles: list[Article] = []
    for pa in root.findall(".//PubmedArticle"):
        medline = pa.find("MedlineCitation")
        if medline is None:
            continue
        pmid = _text(medline.find("PMID"))
        art = medline.find("Article")
        if art is None:
            continue

        title = _text(art.find("ArticleTitle"))

        # Authors
        authors: list[dict] = []
        for a in art.findall(".//AuthorList/Author"):
            collective = _text(a.find("CollectiveName"))
            if collective:
                authors.append({"collective": collective})
                continue
            authors.append({
                "last": _text(a.find("LastName")),
                "fore": _text(a.find("ForeName")),
                "initials": _text(a.find("Initials")),
            })

        # Journal
        journal_el = art.find("Journal")
        journal = ""
        year = ""
        volume = ""
        issue = ""
        if journal_el is not None:
            journal = (_text(journal_el.find("Title"))
                       or _text(journal_el.find("ISOAbbreviation")))
            ji = journal_el.find("JournalIssue")
            if ji is not None:
                volume = _text(ji.find("Volume"))
                issue = _text(ji.find("Issue"))
                year = _text(ji.find(".//PubDate/Year"))
                if not year:
                    medline_date = _text(ji.find(".//PubDate/MedlineDate"))
                    year = medline_date[:4] if medline_date else ""

        pages = _text(art.find(".//Pagination/MedlinePgn"))

        # DOI: prefer the ELocationID, fall back to the ArticleIdList.
        doi = ""
        for eid in art.findall("ELocationID"):
            if eid.get("EIdType") == "doi":
                doi = _text(eid)
                break
        if not doi:
            for aid in pa.findall(".//ArticleIdList/ArticleId"):
                if aid.get("IdType") == "doi":
                    doi = _text(aid)
                    break

        # A human-friendly publication date for sorting/reporting.
        pub_date = _extract_pub_date(pa)

        articles.append(Article(
            pmid=pmid, title=title, authors=authors, journal=journal,
            year=year, volume=volume, issue=issue, pages=pages,
            doi=doi.lower(), pub_date=pub_date,
        ))
    return articles


def _extract_pub_date(pa: ET.Element) -> str:
    """Best-effort ISO-ish date string, preferring the electronic pub date."""
    # PubMedPubDate entries carry the crawl/receipt dates PubMed sorts on.
    for status in ("pubmed", "entrez", "medline"):
        for pd in pa.findall(".//PubmedData/History/PubMedPubDate"):
            if pd.get("PubStatus") == status:
                y = _text(pd.find("Year"))
                m = _text(pd.find("Month")).zfill(2)
                d = _text(pd.find("Day")).zfill(2)
                if y:
                    return f"{y}-{m}-{d}"
    return ""


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
DEFAULT_SEARCHES = {
    "defaults": {
        "days": 30,
        "max_results": 200,
        "datetype": "pdat",  # publication date; use "edat" for Entrez date
        "email": "",
    },
    "searches": [
        {
            "name": "scrnaseq",
            "enabled": True,
            "query": (
                '("single cell RNA sequencing"[Title/Abstract] '
                'OR "single-cell RNA-seq"[Title/Abstract] '
                'OR "scRNA-seq"[Title/Abstract] '
                'OR "single cell transcriptomics"[Title/Abstract])'
            ),
        },
    ],
}


def load_config(path: str) -> dict:
    if yaml is None:
        raise RuntimeError("PyYAML is required to read the config file. "
                           "Install it with: pip install pyyaml")
    p = Path(path)
    if not p.exists():
        return DEFAULT_SEARCHES
    with p.open("r", encoding="utf-8") as fh:
        data = yaml.safe_load(fh) or {}
    data.setdefault("defaults", {})
    data.setdefault("searches", [])
    return data


# --------------------------------------------------------------------------- #
# Seen-cache (so repeat runs only report new articles)
# --------------------------------------------------------------------------- #
def load_seen(cache_path: Path) -> dict:
    if cache_path.exists():
        try:
            return json.loads(cache_path.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def save_seen(cache_path: Path, seen: dict) -> None:
    cache_path.write_text(json.dumps(seen, indent=2), encoding="utf-8")


# --------------------------------------------------------------------------- #
# Output
# --------------------------------------------------------------------------- #
CSV_FIELDS = ["search", "title", "authors_apa", "journal", "year",
              "doi", "url", "pubmed_url", "pmid", "pub_date"]


def write_csv(path: Path, rows: list[dict]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=CSV_FIELDS)
        writer.writeheader()
        for row in rows:
            writer.writerow({k: row.get(k, "") for k in CSV_FIELDS})


def write_txt(path: Path, grouped: dict[str, list[Article]]) -> None:
    lines: list[str] = []
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    lines.append(f"PubMed article report — generated {stamp}")
    lines.append("=" * 72)
    for name, articles in grouped.items():
        lines.append("")
        lines.append(f"## {name}  ({len(articles)} new)")
        lines.append("-" * 72)
        if not articles:
            lines.append("  (no new articles)")
            continue
        for i, art in enumerate(articles, 1):
            lines.append(f"{i}. {art.apa_citation()}")
            lines.append(f"   Link: {art.url}")
            lines.append("")
    path.write_text("\n".join(lines), encoding="utf-8")


def article_to_row(search_name: str, art: Article) -> dict:
    return {
        "search": search_name,
        "title": art.title,
        "authors_apa": art.apa_authors,
        "journal": art.journal,
        "year": art.year,
        "doi": art.doi,
        "url": art.url,
        "pubmed_url": art.pubmed_url,
        "pmid": art.pmid,
        "pub_date": art.pub_date,
    }


# --------------------------------------------------------------------------- #
# Core run logic
# --------------------------------------------------------------------------- #
def run_search(client: PubMedClient, name: str, query: str, days: int | None,
               retmax: int, datetype: str, seen: dict,
               use_cache: bool) -> list[Article]:
    pmids = client.esearch(query, days=days, retmax=retmax, datetype=datetype)
    if not pmids:
        return []

    if use_cache:
        already = set(seen.get(name, []))
        new_pmids = [p for p in pmids if p not in already]
    else:
        new_pmids = pmids

    if not new_pmids:
        return []

    articles = client.efetch(new_pmids)
    # Preserve PubMed's date-sorted order (efetch may reorder).
    order = {p: i for i, p in enumerate(new_pmids)}
    articles.sort(key=lambda a: order.get(a.pmid, 1e9))

    if use_cache:
        seen[name] = sorted(set(seen.get(name, [])) | set(pmids))
    return articles


def build_search_list(config: dict, args) -> list[dict]:
    defaults = config.get("defaults", {})

    if args.query:
        return [{
            "name": args.name or "adhoc",
            "query": args.query,
            "days": args.days if args.days is not None else defaults.get("days", 30),
            "max_results": args.max if args.max is not None else defaults.get("max_results", 200),
            "datetype": args.datetype or defaults.get("datetype", "pdat"),
        }]

    searches = []
    for s in config.get("searches", []):
        if args.search and s.get("name") != args.search:
            continue
        if not args.search and not s.get("enabled", True):
            continue
        searches.append({
            "name": s.get("name", "unnamed"),
            "query": s["query"],
            "days": args.days if args.days is not None else s.get("days", defaults.get("days", 30)),
            "max_results": args.max if args.max is not None else s.get("max_results", defaults.get("max_results", 200)),
            "datetype": args.datetype or s.get("datetype", defaults.get("datetype", "pdat")),
        })
    return searches


def parse_args(argv: list[str]) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Scrape PubMed for new articles matching configurable searches.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__.split("Examples")[1] if "Examples" in __doc__ else "",
    )
    p.add_argument("--config", default=DEFAULT_CONFIG,
                   help=f"Path to the YAML search config (default: {DEFAULT_CONFIG}).")
    p.add_argument("--search", metavar="NAME",
                   help="Run only the named search from the config (ignores 'enabled').")
    p.add_argument("--query", metavar="PUBMED_QUERY",
                   help="Run an ad-hoc PubMed query instead of the config searches.")
    p.add_argument("--name", metavar="NAME",
                   help="Label for the ad-hoc --query (default: 'adhoc').")
    p.add_argument("--days", type=int, default=None,
                   help="Only articles from the last N days (0 = no date limit).")
    p.add_argument("--max", type=int, default=None,
                   help="Max results per search (default from config, else 200).")
    p.add_argument("--datetype", choices=["pdat", "edat", "mdat"], default=None,
                   help="Date field for the window: pdat=publication, "
                        "edat=Entrez date, mdat=modified (default: pdat).")
    p.add_argument("--output-dir", default=DEFAULT_OUTPUT_DIR,
                   help=f"Directory for CSV/TXT output (default: {DEFAULT_OUTPUT_DIR}).")
    p.add_argument("--format", choices=["csv", "txt", "both"], default="both",
                   help="Output format(s) to write (default: both).")
    p.add_argument("--all", action="store_true",
                   help="Report every match in the window, ignoring the seen-cache.")
    p.add_argument("--cache-file", default=DEFAULT_CACHE_FILE,
                   help=f"Path to the seen-PMID cache (default: {DEFAULT_CACHE_FILE}).")
    p.add_argument("--email", default=os.environ.get("NCBI_EMAIL", ""),
                   help="Contact email for NCBI (or set NCBI_EMAIL).")
    p.add_argument("--api-key", default=os.environ.get("NCBI_API_KEY", ""),
                   help="NCBI API key to raise the rate limit (or set NCBI_API_KEY).")
    return p.parse_args(argv)


def main(argv: list[str]) -> int:
    args = parse_args(argv)

    try:
        config = load_config(args.config)
    except RuntimeError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 2

    defaults = config.get("defaults", {})
    email = args.email or defaults.get("email", "")
    searches = build_search_list(config, args)

    if not searches:
        print("No searches to run. Check --search/--query or your config's "
              "'enabled' flags.", file=sys.stderr)
        return 1

    client = PubMedClient(email=email, api_key=args.api_key)

    use_cache = not args.all
    cache_path = Path(args.cache_file)
    seen = load_seen(cache_path) if use_cache else {}

    grouped: dict[str, list[Article]] = {}
    all_rows: list[dict] = []
    total_new = 0

    for s in searches:
        name = s["name"]
        print(f"[{name}] searching (last {s['days']} days, "
              f"max {s['max_results']})...", file=sys.stderr)
        try:
            articles = run_search(
                client, name, s["query"], s["days"], s["max_results"],
                s["datetype"], seen, use_cache,
            )
        except RuntimeError as exc:
            print(f"[{name}] ERROR: {exc}", file=sys.stderr)
            grouped[name] = []
            continue
        grouped[name] = articles
        total_new += len(articles)
        print(f"[{name}] {len(articles)} new article(s).", file=sys.stderr)
        for art in articles:
            all_rows.append(article_to_row(name, art))

    # Write outputs.
    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    written: list[str] = []

    if args.format in ("csv", "both"):
        csv_path = out_dir / f"pubmed_{stamp}.csv"
        write_csv(csv_path, all_rows)
        written.append(str(csv_path))
    if args.format in ("txt", "both"):
        txt_path = out_dir / f"pubmed_{stamp}.txt"
        write_txt(txt_path, grouped)
        written.append(str(txt_path))

    if use_cache:
        save_seen(cache_path, seen)

    print(f"\nDone. {total_new} new article(s) across {len(searches)} search(es).",
          file=sys.stderr)
    for path in written:
        print(f"  wrote {path}", file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
