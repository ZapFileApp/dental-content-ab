#!/usr/bin/env python3
"""Merge multiple per-page extraction dicts (same schema as prompt.txt) into
one consolidated record per business. Runs locally, no LLM call involved."""

SCALAR_FIELDS = ["clinic_name", "clinic_desc", "address", "city", "postcode", "phone", "State"]
LIST_OF_DICT_FIELDS = {
    "services": "name",
    "dentists": "name",
}
LIST_OF_STRING_FIELDS = ["insurance_plans"]


def _norm(s):
    return (s or "").strip().lower()


def merge_page_results(page_results: list[dict]) -> dict:
    """page_results: list of parsed JSON dicts, one per crawled page,
    already ordered by page priority (most-trustworthy page first)."""
    merged = {f: None for f in SCALAR_FIELDS}
    merged.update({f: [] for f in LIST_OF_DICT_FIELDS})
    merged.update({f: [] for f in LIST_OF_STRING_FIELDS})

    list_dict_seen = {f: {} for f in LIST_OF_DICT_FIELDS}  # key -> index in merged[f]
    string_seen = {f: set() for f in LIST_OF_STRING_FIELDS}

    for page in page_results:
        if not isinstance(page, dict):
            continue

        # scalars: first non-null wins (pages are pre-ordered by trust/priority)
        for field in SCALAR_FIELDS:
            value = page.get(field)
            if merged[field] is None and value:
                merged[field] = value

        # list-of-dict fields: dedup by key, merge non-null sub-fields across duplicates
        for field, key_name in LIST_OF_DICT_FIELDS.items():
            for item in page.get(field) or []:
                if not isinstance(item, dict):
                    continue
                key = _norm(item.get(key_name))
                if not key:
                    continue
                if key in list_dict_seen[field]:
                    idx = list_dict_seen[field][key]
                    existing = merged[field][idx]
                    for sub_field, sub_value in item.items():
                        if not existing.get(sub_field) and sub_value:
                            existing[sub_field] = sub_value
                else:
                    list_dict_seen[field][key] = len(merged[field])
                    merged[field].append(dict(item))

        # list-of-string fields: dedup case-insensitively, keep first-seen casing
        for field in LIST_OF_STRING_FIELDS:
            for value in page.get(field) or []:
                if not isinstance(value, str) or not value.strip():
                    continue
                key = _norm(value)
                if key not in string_seen[field]:
                    string_seen[field].add(key)
                    merged[field].append(value.strip())

    return merged
