#!/usr/bin/env python3
"""Content generator: read crawled HTML for a set of businesses, extract
structured data page-by-page (so no page's content is ever truncated away),
then merge the per-page results locally into one consolidated record per
business. Run against HTML_DIR (default test_html/) for validation before
this gets wired into a batched GH Actions matrix workflow like the crawler."""
import json
import os
import re
import time
import urllib.request

from clean_html import clean_html, should_skip_page
from merge_json import merge_page_results

HTML_DIR = os.environ.get("HTML_DIR", "test_html")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "results")
FAILURES_TXT = os.environ.get("FAILURES_TXT", "failures.txt")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_URL = "http://localhost:11434/api/generate"
MAX_PAGE_CHARS = 6000  # per-page cap (matches clean_html's own default)
PROMPT_FILE = os.environ.get("PROMPT_FILE", "prompt.txt")

# Pages most likely to hold reliable contact/services info are processed
# first — doesn't affect correctness (every page is processed regardless)
# but the merge step's "first non-null wins" logic means priority pages
# should win ties for scalar fields like address/phone.
PAGE_PRIORITY_KEYWORDS = ["contact", "about", "location", "service", "team", "insurance"]


def page_priority(filename: str) -> int:
    lower = filename.lower()
    for i, kw in enumerate(PAGE_PRIORITY_KEYWORDS):
        if kw in lower:
            return i
    return len(PAGE_PRIORITY_KEYWORDS)  # everything else (incl. homepage) goes last


def load_prompt_template() -> str:
    with open(PROMPT_FILE, encoding="utf-8") as f:
        return f.read()


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


def parse_json_response(raw: str) -> dict:
    """Model is instructed to return bare JSON, but tolerate markdown fences
    or stray text around it."""
    match = re.search(r"\{.*\}", raw, re.DOTALL)
    if not match:
        raise ValueError(f"no JSON object found in response: {raw[:200]!r}")
    return json.loads(match.group(0))


def process_business(domain: str, business_dir: str, prompt_template: str) -> dict:
    filenames = sorted(
        (f for f in os.listdir(business_dir) if f.endswith(".html") and not should_skip_page(f)),
        key=page_priority,
    )

    page_results = []
    page_errors = []
    for filename in filenames:
        path = os.path.join(business_dir, filename)
        with open(path, encoding="utf-8", errors="ignore") as f:
            html = f.read()
        cleaned = clean_html(html, max_chars=MAX_PAGE_CHARS)
        if not cleaned:
            continue

        prompt = prompt_template.format(content=cleaned)
        try:
            raw = call_ollama(prompt)
            parsed = parse_json_response(raw)
            page_results.append(parsed)
        except Exception as err:
            page_errors.append(f"{filename}: {err}")

    if not page_results:
        raise ValueError(f"no page succeeded ({len(page_errors)} page errors: {page_errors[:3]})")

    merged = merge_page_results(page_results)
    merged["_pages_processed"] = len(filenames)
    merged["_pages_succeeded"] = len(page_results)
    merged["_page_errors"] = page_errors
    return merged


def main():
    businesses = sorted(
        d for d in os.listdir(HTML_DIR)
        if os.path.isdir(os.path.join(HTML_DIR, d))
    )
    print(f"Found {len(businesses)} businesses in {HTML_DIR}")

    prompt_template = load_prompt_template()
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    for domain in businesses:
        business_dir = os.path.join(HTML_DIR, domain)
        print(f"\n=== {domain} ===")
        start = time.time()
        try:
            merged = process_business(domain, business_dir, prompt_template)
            elapsed = time.time() - start
            print(
                f"  done in {elapsed:.1f}s — "
                f"{merged['_pages_succeeded']}/{merged['_pages_processed']} pages ok, "
                f"{len(merged['services'])} services, {len(merged['dentists'])} dentists, "
                f"{len(merged['insurance_plans'])} insurance plans"
            )
            merged["_seconds"] = round(elapsed, 1)

            out_path = os.path.join(OUTPUT_DIR, f"{domain}.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(merged, f, indent=2, ensure_ascii=False)
        except Exception as err:
            elapsed = time.time() - start
            print(f"  FAILED after {elapsed:.1f}s: {err}")
            with open(FAILURES_TXT, "a", encoding="utf-8") as f:
                f.write(domain + "\n")

    print(f"\nWrote results to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
