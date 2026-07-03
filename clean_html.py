#!/usr/bin/env python3
"""Extract clean, LLM-ready text from a crawled HTML page — strips scripts,
styles, nav/footer/header chrome, and skips low-value pages entirely
(blog posts, legal/privacy/terms, cart/search/login, career listings)."""
from bs4 import BeautifulSoup

SKIP_PATH_KEYWORDS = [
    "blog", "privacy", "terms", "legal", "cart", "search", "login",
    "checkout", "career", "careers", "sitemap", "404",
]

NOISE_TAGS = ["script", "style", "nav", "footer", "header", "noscript", "svg", "form"]


def should_skip_page(filename: str) -> bool:
    lower = filename.lower()
    return any(kw in lower for kw in SKIP_PATH_KEYWORDS)


def clean_html(html: str, max_chars: int = 6000) -> str:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup(NOISE_TAGS):
        tag.decompose()

    text = soup.get_text(separator=" ", strip=True)
    # collapse repeated whitespace
    text = " ".join(text.split())
    return text[:max_chars]
