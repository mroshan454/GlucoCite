#!/usr/bin/env python3
"""
build_corpus.py - one script to build the GlucoCite corpus.

Three sources, one corpus folder:
  corpus/abstracts/    PubMed abstracts          (text) -> PMID_*.txt
  corpus/fulltext/     PMC Open Access articles  (text) -> PMC_*.txt
  corpus/guidelines/   Guideline PDFs            (pdf)  -> *.pdf
  corpus/manifest.csv  provenance + licence for everything

Usage:
  python3 build_corpus.py            # run all three stages
  python3 build_corpus.py abstracts  # just one stage
  python3 build_corpus.py fulltext
  python3 build_corpus.py pdfs

Standard library only - no pip install.
"""

import sys
import csv
import json
import time
import urllib.parse
import urllib.request
import urllib.error
import xml.etree.ElementTree as ET
from datetime import date
from pathlib import Path

# ---- config -----------------------------------------------------------------
TOPIC = "type 2 diabetes management"
ABSTRACTS_MAX = 1000
FULLTEXT_MAX = 300
EMAIL = "your_email@example.com"
API_KEY = ""          # optional: paste an NCBI key for 10 req/sec (faster)
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"
USER_AGENT = "glucocite-corpus-builder (research; contact: your_email@example.com)"
MIN_FULLTEXT_CHARS = 500

CORPUS = Path("corpus")
DIR_ABSTRACTS = CORPUS / "abstracts"
DIR_FULLTEXT = CORPUS / "fulltext"
DIR_PDFS = CORPUS / "guidelines"
MANIFEST = CORPUS / "manifest.csv"

# Guideline PDFs (real PDFs). Replace the placeholders with links you copy.
# NOTE: ADA Standards of Care is CITE-ONLY (its terms forbid data mining), so
# it is deliberately excluded from ingestion - read and cite it, don't ingest.
PDF_SOURCES = [
    {
        "url": "https://www.nice.org.uk/guidance/ng28/resources/type-2-diabetes-in-adults-management-pdf-1837338615493",
        "filename": "nice_ng28_type2_diabetes.pdf",
        "source": "NICE (NG28)", "tier": "guideline",
        "license": "NICE Notice of rights - non-commercial; do not republish",
    },
    {
        "url": "https://REPLACE-from-iris.who.int/who-diabetes.pdf",
        "filename": "who_diabetes_guideline.pdf",
        "source": "WHO", "tier": "guideline",
        "license": "CC BY-NC-SA (verify on the IRIS page)",
    },
    {
        "url": "https://REPLACE-from-racgp.org.au/racgp-t2d.pdf",
        "filename": "racgp_management_type2_diabetes.pdf",
        "source": "RACGP", "tier": "guideline",
        "license": "check RACGP terms before ingesting",
    },
]


# ---- shared helpers ---------------------------------------------------------
def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=60) as r:
        return r.read()


def _params(extra):
    p = {"email": EMAIL}
    if API_KEY:
        p["api_key"] = API_KEY
    p.update(extra)
    return urllib.parse.urlencode(p)


def log(type_, source, tier, license_, path, status):
    new = not MANIFEST.exists()
    with MANIFEST.open("a", newline="", encoding="utf-8") as f:
        w = csv.writer(f)
        if new:
            w.writerow(["date", "type", "source", "tier", "license", "path", "status"])
        w.writerow([date.today().isoformat(), type_, source, tier, license_, path, status])


def _local(tag):
    return tag.rsplit("}", 1)[-1]


def first_text(elem, name):
    for e in elem.iter():
        if _local(e.tag) == name:
            return " ".join(t.strip() for t in e.itertext() if t.strip())
    return ""


def block_text(elem, name):
    for e in elem.iter():
        if _local(e.tag) == name:
            return "\n".join(t.strip() for t in e.itertext() if t.strip())
    return ""


# ---- 1) PubMed abstracts ----------------------------------------------------
def fetch_abstracts(topic, retmax):
    DIR_ABSTRACTS.mkdir(parents=True, exist_ok=True)
    print(f"\n[abstracts] searching PubMed: {topic!r} (up to {retmax})")
    qs = _params({"db": "pubmed", "term": topic, "retmax": retmax,
                  "retmode": "json", "sort": "relevance"})
    ids = json.loads(_get(f"{EUTILS}/esearch.fcgi?{qs}"))["esearchresult"]["idlist"]
    print(f"[abstracts] found {len(ids)}")
    saved = skipped = 0
    delay = 0.15 if API_KEY else 0.4
    batch_size = 100
    for i in range(0, len(ids), batch_size):
        batch = ids[i:i + batch_size]
        qs = _params({"db": "pubmed", "id": ",".join(batch),
                      "rettype": "abstract", "retmode": "xml"})
        try:
            root = ET.fromstring(_get(f"{EUTILS}/efetch.fcgi?{qs}"))
        except (urllib.error.URLError, ET.ParseError, TimeoutError) as e:
            print(f"  batch failed ({e})")
            time.sleep(delay)
            continue
        for art in root.findall(".//PubmedArticle"):
            pmid = art.findtext(".//PMID") or "unknown"
            dest = DIR_ABSTRACTS / f"PMID_{pmid}.txt"
            if dest.exists():
                skipped += 1
                continue
            parts = []
            for ab in art.findall(".//Abstract/AbstractText"):
                label = ab.get("Label")
                txt = "".join(ab.itertext()).strip()
                if txt:
                    parts.append(f"{label}: {txt}" if label else txt)
            abstract = "\n".join(parts)
            if not abstract:
                continue
            title = art.findtext(".//ArticleTitle") or "(no title)"
            journal = art.findtext(".//Journal/Title") or ""
            year = (art.findtext(".//PubDate/Year")
                    or art.findtext(".//PubDate/MedlineDate") or "")
            url = f"https://pubmed.ncbi.nlm.nih.gov/{pmid}/"
            header = (f"Title: {title}\nJournal: {journal} ({year})\n"
                      f"PMID: {pmid}\nSource: {url}\nTier: abstract\n"
                      f"License: PubMed abstract (NLM)\n{'-' * 60}\n")
            dest.write_text(header + abstract, encoding="utf-8")
            log("abstract", "PubMed", "abstract", "PubMed abstract (NLM)", str(dest), "downloaded")
            saved += 1
        print(f"  abstracts {min(i + batch_size, len(ids))}/{len(ids)} "
              f"(saved {saved}, skipped {skipped})")
        time.sleep(delay)
    print(f"[abstracts] done - saved {saved}, skipped {skipped}")


# ---- 2) PMC Open Access full text -------------------------------------------
def fetch_fulltext(topic, retmax):
    DIR_FULLTEXT.mkdir(parents=True, exist_ok=True)
    print(f"\n[fulltext] searching PMC Open Access: {topic!r} (up to {retmax})")
    qs = _params({"db": "pmc", "term": f"{topic} AND open access[filter]",
                  "retmax": retmax, "retmode": "json", "sort": "relevance"})
    ids = json.loads(_get(f"{EUTILS}/esearch.fcgi?{qs}"))["esearchresult"]["idlist"]
    print(f"[fulltext] found {len(ids)} open-access articles")
    saved = skipped = empty = 0
    delay = 0.15 if API_KEY else 0.4
    for n, pmcid in enumerate(ids, 1):
        # FIX: the id returned by the search IS the real PMC accession number.
        # Name the file with it instead of re-parsing it out of the messy XML
        # (which is what produced all those "PMC_unknown" collisions).
        dest = DIR_FULLTEXT / f"PMC_{pmcid}.txt"
        if dest.exists():
            skipped += 1
            continue
        qs = _params({"db": "pmc", "id": pmcid, "retmode": "xml"})
        try:
            art = ET.fromstring(_get(f"{EUTILS}/efetch.fcgi?{qs}"))
        except (urllib.error.URLError, ET.ParseError, TimeoutError) as e:
            print(f"  PMC{pmcid} failed ({e})")
            time.sleep(delay)
            continue
        body = block_text(art, "body")
        if len(body) < MIN_FULLTEXT_CHARS:
            empty += 1
            time.sleep(delay)
            continue
        title = first_text(art, "article-title") or "(no title)"
        journal = first_text(art, "journal-title")
        year = first_text(art, "year")
        lic = block_text(art, "license") or "PMC Open Access (verify)"
        url = f"https://www.ncbi.nlm.nih.gov/pmc/articles/PMC{pmcid}/"
        header = (f"Title: {title}\nJournal: {journal} ({year})\n"
                  f"PMCID: PMC{pmcid}\nSource: {url}\nTier: open_access_fulltext\n"
                  f"License: {lic[:200]}\n{'-' * 60}\n")
        dest.write_text(header + body, encoding="utf-8")
        log("fulltext", "PMC OA", "open_access_fulltext", lic[:120], str(dest), "downloaded")
        saved += 1
        if n % 20 == 0:
            print(f"  fulltext {n}/{len(ids)} "
                  f"(saved {saved}, skipped {skipped}, empty {empty})")
        time.sleep(delay)
    print(f"[fulltext] done - saved {saved}, skipped {skipped}, empty {empty}")


# ---- 3) Guideline PDFs ------------------------------------------------------
def download_pdfs():
    DIR_PDFS.mkdir(parents=True, exist_ok=True)
    print(f"\n[pdfs] downloading {len(PDF_SOURCES)} guideline PDFs")
    saved = skipped = failed = 0
    for item in PDF_SOURCES:
        dest = DIR_PDFS / item["filename"]
        if item["url"].startswith("https://REPLACE"):
            print(f"  skip (placeholder): {item['filename']}")
            skipped += 1
            continue
        if dest.exists():
            print(f"  skip (exists): {item['filename']}")
            skipped += 1
            continue
        try:
            req = urllib.request.Request(item["url"], headers={"User-Agent": USER_AGENT})
            with urllib.request.urlopen(req, timeout=60) as resp:
                ctype = resp.headers.get("Content-Type", "").lower()
                data = resp.read()
        except (urllib.error.URLError, TimeoutError) as e:
            print(f"  FAILED: {item['filename']} ({e})")
            failed += 1
            log("pdf", item["source"], item["tier"], item["license"], str(dest), "failed")
            continue
        if "html" in ctype or not data.startswith(b"%PDF"):
            print(f"  FAILED: {item['filename']} (not a PDF - check the URL)")
            failed += 1
            log("pdf", item["source"], item["tier"], item["license"], str(dest), "failed")
            continue
        dest.write_bytes(data)
        print(f"  downloaded: {item['filename']} ({len(data) // 1024} KB)")
        log("pdf", item["source"], item["tier"], item["license"], str(dest), "downloaded")
        saved += 1
        time.sleep(1.5)
    print(f"[pdfs] done - saved {saved}, skipped {skipped}, failed {failed}")


# ---- main -------------------------------------------------------------------
def main():
    CORPUS.mkdir(parents=True, exist_ok=True)
    stage = sys.argv[1] if len(sys.argv) > 1 else "all"
    if stage in ("all", "abstracts"):
        fetch_abstracts(TOPIC, ABSTRACTS_MAX)
    if stage in ("all", "fulltext"):
        fetch_fulltext(TOPIC, FULLTEXT_MAX)
    if stage in ("all", "pdfs"):
        download_pdfs()
    print(f"\nCorpus ready under ./{CORPUS}/  (provenance in {MANIFEST})")


if __name__ == "__main__":
    main()