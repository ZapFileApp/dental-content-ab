#!/usr/bin/env python3
"""Test-scale content generator: read crawled HTML for a small set of
businesses, clean it, and ask a local ollama model for a short directory
description. Run against HTML_DIR (default test_html/) for the initial
2-3-business validation pass before this gets wired into a batched
GH Actions matrix workflow like the crawler."""
import csv
import os
import sys
import time
import urllib.request
import json

from clean_html import clean_html, should_skip_page

HTML_DIR = os.environ.get("HTML_DIR", "test_html")
OUTPUT_CSV = os.environ.get("OUTPUT_CSV", "descriptions.csv")
FAILURES_TXT = os.environ.get("FAILURES_TXT", "failures.txt")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_URL = "http://localhost:11434/api/generate"
MAX_TOTAL_CHARS = 8000  # hard cap on combined cleaned text sent to the model

PROMPT_TEMPLATE = """You are writing a short, factual directory listing description for a dental practice, based only on the website content below. Do not invent details that aren't present in the content.

Write 2-3 sentences covering what the practice offers and anything notable (location, specialties, patient focus). Plain text only, no markdown.

WEBSITE CONTENT:
{content}

DESCRIPTION:"""


def gather_business_text(business_dir: str) -> str:
    parts = []
    total = 0
    for filename in sorted(os.listdir(business_dir)):
        if not filename.endswith(".html"):
            continue
        if should_skip_page(filename):
            continue
        path = os.path.join(business_dir, filename)
        with open(path, encoding="utf-8", errors="ignore") as f:
            html = f.read()
        cleaned = clean_html(html)
        if not cleaned:
            continue
        remaining = MAX_TOTAL_CHARS - total
        if remaining <= 0:
            break
        chunk = cleaned[:remaining]
        parts.append(chunk)
        total += len(chunk)
    return "\n\n---\n\n".join(parts)


def call_ollama(prompt: str) -> str:
    payload = json.dumps({
        "model": OLLAMA_MODEL,
        "prompt": prompt,
        "stream": False,
    }).encode("utf-8")
    req = urllib.request.Request(OLLAMA_URL, data=payload, headers={"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        result = json.loads(resp.read().decode("utf-8"))
    return result.get("response", "").strip()


def main():
    businesses = sorted(
        d for d in os.listdir(HTML_DIR)
        if os.path.isdir(os.path.join(HTML_DIR, d))
    )
    print(f"Found {len(businesses)} businesses in {HTML_DIR}")

    rows = []
    for domain in businesses:
        business_dir = os.path.join(HTML_DIR, domain)
        print(f"\n=== {domain} ===")
        start = time.time()
        try:
            content = gather_business_text(business_dir)
            if not content:
                raise ValueError("no usable content after filtering/cleaning")

            prompt = PROMPT_TEMPLATE.format(content=content)
            print(f"  prompt length: {len(prompt)} chars")

            description = call_ollama(prompt)
            elapsed = time.time() - start
            print(f"  done in {elapsed:.1f}s: {description[:120]}...")

            rows.append({"domain": domain, "description": description, "seconds": round(elapsed, 1)})
        except Exception as err:
            elapsed = time.time() - start
            print(f"  FAILED after {elapsed:.1f}s: {err}")
            with open(FAILURES_TXT, "a", encoding="utf-8") as f:
                f.write(domain + "\n")

    with open(OUTPUT_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=["domain", "description", "seconds"])
        writer.writeheader()
        writer.writerows(rows)

    print(f"\nWrote {len(rows)} descriptions to {OUTPUT_CSV}")


if __name__ == "__main__":
    main()
