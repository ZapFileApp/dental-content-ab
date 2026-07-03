#!/usr/bin/env python3
"""Run locally (no ollama/GH Actions needed) against a results/ folder
produced by generate_content.py: reads each business's per-page JSON files
and writes a consolidated results/<domain>/_merged.json. Safe to re-run any
time the merge logic in merge_json.py changes — no LLM calls involved."""
import json
import os
import sys

from merge_json import merge_page_results

RESULTS_DIR = sys.argv[1] if len(sys.argv) > 1 else "results"


def page_priority(filename: str) -> int:
    # Keep in sync with generate_content.py's page ordering intent: pages
    # most likely to hold reliable contact/services info win scalar-field
    # ties in the merge (first non-null wins).
    keywords = ["contact", "about", "location", "service", "team", "insurance"]
    lower = filename.lower()
    for i, kw in enumerate(keywords):
        if kw in lower:
            return i
    return len(keywords)


def main():
    domains = sorted(
        d for d in os.listdir(RESULTS_DIR)
        if os.path.isdir(os.path.join(RESULTS_DIR, d))
    )
    print(f"Found {len(domains)} businesses in {RESULTS_DIR}")

    merged_count = 0
    for domain in domains:
        business_dir = os.path.join(RESULTS_DIR, domain)
        page_files = sorted(
            (f for f in os.listdir(business_dir) if f.endswith(".json") and f != "_merged.json"),
            key=page_priority,
        )
        if not page_files:
            print(f"  {domain}: no page JSON files, skipping")
            continue

        page_results = []
        for filename in page_files:
            with open(os.path.join(business_dir, filename), encoding="utf-8") as f:
                page_results.append(json.load(f))

        merged = merge_page_results(page_results)
        merged["_pages_merged"] = len(page_results)

        out_path = os.path.join(business_dir, "_merged.json")
        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(merged, f, indent=2, ensure_ascii=False)
        merged_count += 1
        print(
            f"  {domain}: merged {len(page_results)} pages — "
            f"{len(merged['services'])} services, {len(merged['dentists'])} dentists, "
            f"{len(merged['insurance_plans'])} insurance plans"
        )

    print(f"\nMerged {merged_count}/{len(domains)} businesses.")


if __name__ == "__main__":
    main()
