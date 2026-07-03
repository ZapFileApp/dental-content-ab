#!/usr/bin/env python3
"""Content generator: read crawled HTML for a set of businesses, extract
structured data page-by-page (so no page's content is ever truncated away).
Writes one JSON per page — raw extraction, results/<domain>/<page>.json —
and nothing else. This is the only part of the pipeline that needs ollama/the
GH Actions runner; merging pages into one record per business is pure local
logic with no LLM involved, so it deliberately does NOT happen here — run
merge_results.py separately afterward (locally or in a follow-up job) on the
downloaded results/ folder. Run against HTML_DIR (default test_html/) for
validation before this gets wired into a batched GH Actions matrix workflow
like the crawler."""
import json
import os
import re
import time
import urllib.request

from clean_html import clean_html, should_skip_page

HTML_DIR = os.environ.get("HTML_DIR", "test_html")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "results")
FAILURES_TXT = os.environ.get("FAILURES_TXT", "failures.txt")
OLLAMA_MODEL = os.environ.get("OLLAMA_MODEL", "llama3.2:3b")
OLLAMA_URL = "http://localhost:11434/api/generate"
MAX_PAGE_CHARS = 6000  # per-page cap (matches clean_html's own default)
PROMPT_FILE = os.environ.get("PROMPT_FILE", "prompt.txt")


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


def process_business(business_dir: str, business_out_dir: str, prompt_template: str) -> tuple[int, int, list]:
    """Writes one JSON file per page as soon as it's produced (survives a
    mid-business crash). Returns (pages_processed, pages_succeeded, page_errors)."""
    filenames = sorted(
        f for f in os.listdir(business_dir) if f.endswith(".html") and not should_skip_page(f)
    )
    os.makedirs(business_out_dir, exist_ok=True)

    succeeded = 0
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

            page_out_path = os.path.join(business_out_dir, filename.replace(".html", ".json"))
            with open(page_out_path, "w", encoding="utf-8") as f:
                json.dump(parsed, f, indent=2, ensure_ascii=False)
            succeeded += 1
        except Exception as err:
            page_errors.append(f"{filename}: {err}")

    return len(filenames), succeeded, page_errors


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
        business_out_dir = os.path.join(OUTPUT_DIR, domain)
        print(f"\n=== {domain} ===")
        start = time.time()
        try:
            processed, succeeded, page_errors = process_business(business_dir, business_out_dir, prompt_template)
            elapsed = time.time() - start
            if succeeded == 0:
                raise ValueError(f"no page succeeded ({len(page_errors)} page errors: {page_errors[:3]})")
            print(f"  done in {elapsed:.1f}s — {succeeded}/{processed} pages ok")
        except Exception as err:
            elapsed = time.time() - start
            print(f"  FAILED after {elapsed:.1f}s: {err}")
            with open(FAILURES_TXT, "a", encoding="utf-8") as f:
                f.write(domain + "\n")

    print(f"\nWrote per-page results to {OUTPUT_DIR}/ — run merge_results.py separately to consolidate.")


if __name__ == "__main__":
    main()
