#!/usr/bin/env python3
"""Extract raw, sequential visible text from crawled HTML — no LLM involved.
Strips only script/style/nav/footer/header chrome (not the actual page
content) and skips low-value pages (blog/legal/cart/search/etc). Writes one
plain-text file per page to results_text/<domain>/<page>.txt, preserving the
page's natural reading order (BeautifulSoup's get_text() walks the DOM
top-to-bottom, so this is already "sequential" without extra work)."""
import os
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from clean_html import should_skip_page, NOISE_TAGS

HTML_DIR = os.environ.get("HTML_DIR", "test_html")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "results_text")


def reconstruct_url(filename: str) -> str:
    """Best-effort reversal of the crawler's sanitizeFilename() (in scrape.js):
    it replaced the scheme and every /:?&=# character with "_", so this is
    lossy — cannot tell an original "/" apart from a "?" or "&" etc. Good
    enough for simple paths (most pages here), not exact for query strings."""
    stem = filename[:-len(".html")] if filename.endswith(".html") else filename
    return f"https://{stem.replace('_', '/')}"


def extract_links(soup: BeautifulSoup, base_url: str) -> list[tuple[str, str]]:
    """Pulls every link from the WHOLE page — including nav/footer/header,
    which is exactly where "Book Appointment" / "Contact Us" buttons usually
    live and which raw_text() strips out as chrome. Order preserved as found
    in the document. Resolves relative hrefs (e.g. "/contact") to absolute
    URLs using this page's own URL as the base."""
    links = []
    seen = set()
    for a in soup.find_all("a", href=True):
        href = a["href"].strip()
        text = a.get_text(strip=True)
        if not href or href.startswith("javascript:") or href == "#":
            continue
        absolute = urljoin(base_url, href)
        key = (text, absolute)
        if key in seen:
            continue
        seen.add(key)
        links.append(key)
    return links


def raw_text(soup: BeautifulSoup) -> str:
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    # keep natural line breaks between block-level chunks instead of
    # flattening everything onto one line — "sequential", readable text
    text = soup.get_text(separator="\n", strip=True)
    lines = [line.strip() for line in text.splitlines() if line.strip()]
    return "\n".join(lines)


def main():
    businesses = sorted(
        d for d in os.listdir(HTML_DIR)
        if os.path.isdir(os.path.join(HTML_DIR, d))
    )
    print(f"Found {len(businesses)} businesses in {HTML_DIR}")

    total_pages = 0
    for domain in businesses:
        business_dir = os.path.join(HTML_DIR, domain)
        business_out_dir = os.path.join(OUTPUT_DIR, domain)
        os.makedirs(business_out_dir, exist_ok=True)

        filenames = sorted(
            f for f in os.listdir(business_dir) if f.endswith(".html") and not should_skip_page(f)
        )
        for filename in filenames:
            path = os.path.join(business_dir, filename)
            with open(path, encoding="utf-8", errors="ignore") as f:
                html = f.read()

            url = reconstruct_url(filename)
            soup = BeautifulSoup(html, "html.parser")
            links = extract_links(soup, url)  # must run BEFORE raw_text() strips nav/footer/header
            text = raw_text(soup)
            if not text and not links:
                continue

            links_block = "\n".join(f"{link_text or '(no text)'} -> {href}" for link_text, href in links)
            out_path = os.path.join(business_out_dir, filename.replace(".html", ".txt"))
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(f"URL: {url}\n\nLINKS:\n{links_block}\n\nTEXT:\n{text}")
            total_pages += 1

        print(f"  {domain}: {len(filenames)} pages")

    print(f"\nWrote {total_pages} text files to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
