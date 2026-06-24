#!/usr/bin/env python3
"""
pubmed_fetch.py - pull PubMed abstracts into a ./corpus folder for RAG ingestion.

No API key needed. Standard library only (no pip install).

Usage:
    python3 pubmed_fetch.py
    python3 pubmed_fetch.py "type 2 diabetes management" 30
"""

import sys
import json
import time
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path

# ---- config (edit these or pass as args) ----
TOPIC = "type 2 diabetes management"
MAX_RESULTS = 30
OUTPUT_DIR = Path("corpus")
EMAIL = "your_email@example.com"   # NCBI etiquette - put your real email
EUTILS = "https://eutils.ncbi.nlm.nih.gov/entrez/eutils"


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": "documind-pubmed-fetch"})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read()


def search(topic, retmax):
    params = urllib.parse.urlencode({
        "db": "pubmed", "term": topic, "retmax": retmax,
        "retmode": "json", "sort": "relevance", "email": EMAIL,
    })
    data = _get(f"{EUTILS}/esearch.fcgi?{params}")
    return json.loads(data)["esearchresult"]["idlist"]


def fetch(pmids):
    params = urllib.parse.urlencode({
        "db": "pubmed", "id": ",".join(pmids),
        "rettype": "abstract", "retmode": "xml", "email": EMAIL,
    })
    return _get(f"{EUTILS}/efetch.fcgi?{params}")


def parse_articles(xml_bytes):
    root = ET.fromstring(xml_bytes)
    articles = []
    for art in root.findall(".//PubmedArticle"):
        pmid = art.findtext(".//PMID") or "unknown"
        title = art.findtext(".//ArticleTitle") or "(no title)"
        journal = art.findtext(".//Journal/Title") or ""
        year = (art.findtext(".//PubDate/Year")
                or art.findtext(".//PubDate/MedlineDate") or "")
        parts = []
        for ab in art.findall(".//Abstract/AbstractText"):
            label = ab.get("Label")
            text = "".join(ab.itertext()).strip()
            if not text:
                continue
            parts.append(f"{label}: {text}" if label else text)
        articles.append({
            "pmid": pmid, "title": title, "journal": journal,
            "year": year, "abstract": "\n".join(parts),
        })
    return articles


def save(articles):
    OUTPUT_DIR.mkdir(exist_ok=True)
    saved = 0
    for a in articles:
        if not a["abstract"]:
            continue  # skip entries with no abstract
        url = f"https://pubmed.ncbi.nlm.nih.gov/{a['pmid']}/"
        header = (
            f"Title: {a['title']}\n"
            f"Journal: {a['journal']} ({a['year']})\n"
            f"PMID: {a['pmid']}\n"
            f"Source: {url}\n"
            f"{'-' * 60}\n"
        )
        (OUTPUT_DIR / f"PMID_{a['pmid']}.txt").write_text(
            header + a["abstract"], encoding="utf-8")
        saved += 1
    return saved


def main():
    topic = sys.argv[1] if len(sys.argv) > 1 else TOPIC
    retmax = int(sys.argv[2]) if len(sys.argv) > 2 else MAX_RESULTS
    print(f"Searching PubMed for: {topic!r} (up to {retmax} results)")
    pmids = search(topic, retmax)
    if not pmids:
        print("No results. Try a different topic.")
        return
    print(f"Found {len(pmids)} articles. Fetching abstracts...")
    time.sleep(0.4)  # be polite to NCBI's servers
    articles = parse_articles(fetch(pmids))
    saved = save(articles)
    print(f"Saved {saved} abstracts to ./{OUTPUT_DIR}/ "
          f"(skipped {len(articles) - saved} with no abstract)")
    print("Next: point DocuMind's ingestion at ./corpus and ask a question.")


if __name__ == "__main__":
    main()
