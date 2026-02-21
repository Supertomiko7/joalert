#!/usr/bin/env python3
"""
Manual scanner for English call-center jobs in Casablanca.

- Searches multiple targeted queries on DuckDuckGo HTML results.
- Filters for likely relevant jobs (English + call center/support/sales + Casablanca/Morocco).
- Stores already-seen links in memory/job-alert-seen.json.
- Prints only new matches on each run.
- Tries to extract salary/pay info from snippet + job page.

Usage:
  python3 job_alert_casa_en.py
  python3 job_alert_casa_en.py --limit 25
"""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.parse
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from html import unescape
from typing import Dict, List, Optional

WORKSPACE = "/home/tomiko/.openclaw/workspace"
SEEN_PATH = os.path.join(WORKSPACE, "memory", "job-alert-seen.json")
REPORT_DIR = os.path.join(WORKSPACE, "job_alert_reports")

QUERIES = [
    "english call center casablanca",
    "english customer service casablanca",
    "english chat support casablanca",
    "english email support casablanca",
    "english sales call center casablanca",
    "english speaking call center morocco casablanca",
    "casablanca call center english job",
    "nearshore casablanca english customer service",
    "maarif casablanca english call center",
    "casa finance city english customer support",
    "site:emploi.ma english call center casablanca",
    "site:rekrute.com english call center casablanca",
    "site:moncallcenter.ma english casablanca",
    "site:anapec.org call center english casablanca",
    "site:linkedin.com/jobs english call center casablanca",
]

POSITIVE_KEYWORDS = [
    "english", "anglophone", "customer service", "support", "sales", "teleconseiller",
]

# Role terms: broad call-center agent scope
REQUIRED_ROLE_KEYWORDS = [
    "call center", "callcentre", "call centre", "centre d'appel", "center d'appel",
    "agent", "advisor", "adviser", "representative", "csr", "customer representative",
    "téléconseiller", "teleconseiller", "agent service client",
    "customer care", "customer service", "customer support",
    "chat support", "email support", "live chat",
    "sales", "inside sales", "outbound sales", "inbound sales",
]

LOCATION_KEYWORDS = [
    "casablanca", "morocco", "maroc",
    "nearshore", "maarif", "casa finance", "casablanca finance city", "cfc",
]

NEGATIVE_KEYWORDS = [
    "combo", "crack", "hacking", "proxy", "iptv", "adult", "casino",
    "airport", "aéroport", "security guard",
]

# Basic salary/pay patterns for MAD / USD / EUR style job pages
SALARY_PATTERNS = [
    re.compile(r"\b(?:salary|salaire|pay|compensation|remuneration|rémunération)\b[^\n\.]{0,120}", re.I),
    re.compile(r"\b\d{3,6}\s*(?:-|to|à|–)\s*\d{3,6}\s*(?:mad|dh|dhs|usd|eur|€|\$)\b", re.I),
    re.compile(r"\b(?:mad|dh|dhs|usd|eur|€|\$)\s*\d{3,6}\b", re.I),
    re.compile(r"\b\d{3,6}\s*(?:mad|dh|dhs|usd|eur)\b", re.I),
    re.compile(r"\b\d{3,6}\s*(?:€|\$)\b", re.I),
]

DATE_PATTERNS = [
    re.compile(r"\b(?:today|yesterday|just now|\d+\s*(?:minute|hour|day|week|month|year)s?\s*ago)\b", re.I),
    re.compile(r"\b\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\b", re.I),
    re.compile(r"\b\d{4}[/-]\d{1,2}[/-]\d{1,2}\b", re.I),
    re.compile(r"\b(?:jan|feb|mar|apr|may|jun|jul|aug|sep|sept|oct|nov|dec)[a-z]*\s+\d{1,2},?\s+\d{4}\b", re.I),
]


@dataclass
class Result:
    title: str
    url: str
    snippet: str
    salary: str = "Not specified"
    posted_date: str = "Not specified"


def fetch(url: str, timeout: int = 20, max_bytes: int = 300_000) -> str:
    req = urllib.request.Request(
        url,
        headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/124 Safari/537.36",
            "Accept": "text/html,application/xhtml+xml",
        },
    )
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read(max_bytes).decode("utf-8", errors="ignore")


def extract_ddg_results(html: str, limit: int) -> List[Result]:
    out: List[Result] = []

    anchor_re = re.compile(r'<a[^>]*class="result__a"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.I | re.S)
    snippet_re = re.compile(r'<a[^>]*class="result__snippet"[^>]*>(.*?)</a>|<div[^>]*class="result__snippet"[^>]*>(.*?)</div>', re.I | re.S)

    anchors = anchor_re.findall(html)
    snippets = snippet_re.findall(html)

    for i, (href, title_html) in enumerate(anchors):
        if len(out) >= limit:
            break

        title = clean_html(title_html)
        url = clean_ddg_href(href)
        snippet = ""
        if i < len(snippets):
            raw = snippets[i][0] or snippets[i][1]
            snippet = clean_html(raw)

        if not url.startswith("http"):
            continue

        out.append(Result(title=title, url=url, snippet=snippet))

    return out


def clean_html(s: str) -> str:
    s = re.sub(r"<[^>]+>", " ", s)
    return unescape(re.sub(r"\s+", " ", s)).strip()


def clean_ddg_href(href: str) -> str:
    href = unescape(href)
    if "uddg=" in href:
        try:
            parsed = urllib.parse.urlparse(href)
            q = urllib.parse.parse_qs(parsed.query)
            uddg = q.get("uddg", [""])[0]
            if uddg:
                return urllib.parse.unquote(uddg)
        except Exception:
            pass
    return href


def is_relevant(result: Result) -> bool:
    text = f"{result.title} {result.snippet} {result.url}".lower()

    if any(bad in text for bad in NEGATIVE_KEYWORDS):
        return False

    has_positive = any(k in text for k in POSITIVE_KEYWORDS)
    has_location = any(k in text for k in LOCATION_KEYWORDS)
    has_required_role = any(k in text for k in REQUIRED_ROLE_KEYWORDS)

    return has_positive and has_location and has_required_role


def find_salary(text: str) -> Optional[str]:
    t = text[:150_000]
    for pat in SALARY_PATTERNS:
        m = pat.search(t)
        if m:
            s = re.sub(r"\s+", " ", m.group(0)).strip(" -:;,.")
            return s
    return None


def infer_salary(result: Result, deep_fetch: bool = True) -> str:
    # 1) from title/snippet first
    quick = find_salary(f"{result.title}. {result.snippet}")
    if quick:
        return quick

    # 2) from job page html/text
    if not deep_fetch:
        return "Not specified"

    try:
        page = fetch(result.url, timeout=15, max_bytes=250_000)
        page_clean = clean_html(page)
        found = find_salary(page_clean)
        if found:
            return found
    except Exception:
        pass

    return "Not specified"


def find_posted_date(text: str) -> Optional[str]:
    t = text[:150_000]
    for pat in DATE_PATTERNS:
        m = pat.search(t)
        if m:
            return re.sub(r"\s+", " ", m.group(0)).strip(" -:;,. ")
    return None


def infer_posted_date(result: Result, deep_fetch: bool = True) -> str:
    quick = find_posted_date(f"{result.title}. {result.snippet}")
    if quick:
        return quick

    if not deep_fetch:
        return "Not specified"

    try:
        page = fetch(result.url, timeout=15, max_bytes=250_000)
        page_clean = clean_html(page)
        found = find_posted_date(page_clean)
        if found:
            return found
    except Exception:
        pass

    return "Not specified"


def load_seen() -> Dict[str, List[str]]:
    os.makedirs(os.path.dirname(SEEN_PATH), exist_ok=True)
    if not os.path.exists(SEEN_PATH):
        return {"seen": []}
    try:
        with open(SEEN_PATH, "r", encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict):
            return {"seen": []}
        if "seen" not in data or not isinstance(data["seen"], list):
            data["seen"] = []
        return data
    except Exception:
        return {"seen": []}


def save_seen(data: Dict[str, List[str]]) -> None:
    with open(SEEN_PATH, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)


def write_report(items: List[Result]) -> str:
    os.makedirs(REPORT_DIR, exist_ok=True)
    stamp = datetime.now().strftime("%Y-%m-%d_%H-%M-%S")
    path = os.path.join(REPORT_DIR, f"jobs_{stamp}.txt")

    with open(path, "w", encoding="utf-8") as f:
        if not items:
            f.write("No new matching jobs found.\n")
            return path

        for i, it in enumerate(items, 1):
            f.write(f"{i}) {it.title}\n")
            f.write(f"   Salary: {it.salary}\n")
            f.write(f"   Posted: {it.posted_date}\n")
            if it.snippet:
                f.write(f"   {it.snippet}\n")
            f.write(f"   {it.url}\n\n")

    return path


def main() -> int:
    ap = argparse.ArgumentParser(description="Scan for new English call-center jobs in Casablanca")
    ap.add_argument("--limit", type=int, default=20, help="Max results per query")
    ap.add_argument("--no-deep-salary", action="store_true", help="Skip opening each job link for salary extraction")
    args = ap.parse_args()

    seen_data = load_seen()
    seen = set(seen_data.get("seen", []))

    collected: Dict[str, Result] = {}

    for q in QUERIES:
        url = "https://duckduckgo.com/html/?q=" + urllib.parse.quote_plus(q)
        try:
            html = fetch(url)
            results = extract_ddg_results(html, limit=args.limit)
            for r in results:
                if is_relevant(r):
                    collected[r.url] = r
        except Exception as e:
            print(f"[WARN] Query failed: {q} -> {e}", file=sys.stderr)

    new_items: List[Result] = []
    for url, r in collected.items():
        if url not in seen:
            deep = not args.no_deep_salary
            r.salary = infer_salary(r, deep_fetch=deep)
            r.posted_date = infer_posted_date(r, deep_fetch=deep)
            new_items.append(r)

    new_items.sort(key=lambda x: (x.title.lower(), x.url.lower()))

    for r in new_items:
        seen.add(r.url)

    seen_data["seen"] = sorted(seen)
    save_seen(seen_data)

    report_path = write_report(new_items)

    if not new_items:
        print("No new matching jobs found.")
        print(f"Report: {report_path}")
        return 0

    print(f"New matching jobs: {len(new_items)}")
    for i, it in enumerate(new_items, 1):
        print(f"{i}) {it.title}")
        print(f"   Salary: {it.salary}")
        print(f"   Posted: {it.posted_date}")
        print(f"   {it.url}")
    print(f"\nReport: {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
