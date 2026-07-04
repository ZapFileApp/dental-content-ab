#!/usr/bin/env python3
"""Extract raw, sequential visible text from crawled HTML — no LLM involved.
Strips only script/style/nav/footer/header chrome (not the actual page
content) and skips low-value pages (blog/legal/cart/search/etc). Writes one
plain-text file per page to results_text/<domain>/<page>.txt, preserving the
page's natural reading order (BeautifulSoup's get_text() walks the DOM
top-to-bottom, so this is already "sequential" without extra work).

Token-optimizations applied (all lossless — nothing informational is
dropped, only genuine duplication/boilerplate):
1. Links that appear on EVERY page of a business (site-wide nav/footer/social)
   are written once to _navigation.txt instead of being repeated in every
   page's file. Page files only list links unique to that page.
2. Same-domain links are shortened to relative paths (e.g. "/contact")
   instead of repeating the full domain on every single link.
3. Known template/accessibility boilerplate lines ("top of page", "Skip to
   Main Content", etc.) are stripped from the body text.
"""
import os
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from clean_html import should_skip_page, NOISE_TAGS

HTML_DIR = os.environ.get("HTML_DIR", "test_html")
OUTPUT_DIR = os.environ.get("OUTPUT_DIR", "results_text")

BOILERPLATE_LINES = {
    "top of page", "bottom of page", "skip to main content", "skip to content",
    "back to top", "scroll to top",
}


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


def shorten_same_domain(href: str, domain: str) -> str:
    """https://www.example.com/contact -> /contact when it's the same site
    (we already know the domain from the file's own URL/folder), left
    untouched (still absolute) for anything external."""
    parsed = urlparse(href)
    netloc = parsed.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    if netloc == domain.lower():
        path = parsed.path or "/"
        if parsed.query:
            path += f"?{parsed.query}"
        if parsed.fragment:
            path += f"#{parsed.fragment}"
        return path
    return href


def raw_text(soup: BeautifulSoup) -> str:
    for tag in soup(NOISE_TAGS):
        tag.decompose()
    # keep natural line breaks between block-level chunks instead of
    # flattening everything onto one line — "sequential", readable text
    text = soup.get_text(separator="\n", strip=True)
    lines = [
        line.strip() for line in text.splitlines()
        if line.strip() and line.strip().lower() not in BOILERPLATE_LINES
    ]
    return "\n".join(lines)


def format_links(links: list[tuple[str, str]]) -> str:
    return "\n".join(f"{link_text or '(no text)'} -> {href}" for link_text, href in links)


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

        # pass 1: extract text + links for every page first, so we can find
        # which links are common to ALL pages (site-wide nav) before writing anything
        per_page = {}
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
            per_page[filename] = {"url": url, "links": links, "text": text}

        if not per_page:
            print(f"  {domain}: 0 pages")
            continue

        link_sets = [set(p["links"]) for p in per_page.values()]
        site_wide_links = set.intersection(*link_sets) if len(link_sets) > 1 else set()

        if site_wide_links:
            # keep them in first-seen order from whichever page had them
            ordered_site_links = [l for l in next(iter(per_page.values()))["links"] if l in site_wide_links]
            nav_path = os.path.join(business_out_dir, "_navigation.txt")
            shortened = [(t, shorten_same_domain(h, domain)) for t, h in ordered_site_links]
            with open(nav_path, "w", encoding="utf-8") as f:
                f.write(f"Site-wide links found on every crawled page of {domain}:\n\n{format_links(shortened)}")

        # pass 2: write each page with only its page-specific links
        for filename, data in per_page.items():
            page_specific_links = [l for l in data["links"] if l not in site_wide_links]
            shortened = [(t, shorten_same_domain(h, domain)) for t, h in page_specific_links]
            links_block = format_links(shortened)

            out_path = os.path.join(business_out_dir, filename.replace(".html", ".txt"))
            with open(out_path, "w", encoding="utf-8") as f:
                f.write(f"URL: {data['url']}\n\nLINKS:\n{links_block}\n\nTEXT:\n{data['text']}")
            total_pages += 1

        print(f"  {domain}: {len(per_page)} pages, {len(site_wide_links)} site-wide links deduped")

    print(f"\nWrote {total_pages} text files to {OUTPUT_DIR}/")


if __name__ == "__main__":
    main()
