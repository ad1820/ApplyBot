"""Duplicate detection.

The same logical job can appear from multiple sources with different URLs,
casing, or whitespace. We compute a canonical key from normalized
company + title + location (+ external_id when available) rather than
relying on URL equality alone.
"""
from __future__ import annotations

import hashlib
import re


def _normalize_text(value: str | None) -> str:
    if not value:
        return ""
    value = value.lower().strip()
    value = re.sub(r"[^a-z0-9]+", " ", value)
    value = re.sub(r"\s+", " ", value)
    return value.strip()


_TITLE_NOISE_WORDS = {
    "senior", "sr", "junior", "jr", "ii", "iii", "iv", "i",
    "remote", "hybrid", "onsite", "new", "urgent", "hiring",
}


def _normalize_title(title: str | None) -> str:
    normalized = _normalize_text(title)
    words = [w for w in normalized.split(" ") if w not in _TITLE_NOISE_WORDS]
    return " ".join(words)


def compute_canonical_key(
    company: str,
    title: str,
    location: str | None = None,
    external_id: str | None = None,
) -> str:
    parts = [
        _normalize_text(company),
        _normalize_title(title),
        _normalize_text(location),
    ]
    base = "|".join(parts)
    digest = hashlib.sha256(base.encode("utf-8")).hexdigest()[:32]
    return digest


def canonical_url(url: str | None) -> str:
    """Strip query params/fragments/trailing slashes so trivially different
    URLs pointing at the same posting compare equal."""
    if not url:
        return ""
    url = url.split("?")[0].split("#")[0]
    return url.rstrip("/").lower()


def is_duplicate(job_a: dict, job_b: dict) -> bool:
    """Best-effort duplicate check between two raw normalized job dicts.

    Two jobs are considered duplicates if they share a canonical key, OR if
    they share the same canonical URL, OR the same (source, external_id)
    pair. Company/title/location similarity is the primary signal; URL and
    external_id are secondary corroborating signals.
    """
    key_a = compute_canonical_key(
        job_a.get("company", ""), job_a.get("title", ""), job_a.get("location")
    )
    key_b = compute_canonical_key(
        job_b.get("company", ""), job_b.get("title", ""), job_b.get("location")
    )
    if key_a == key_b:
        return True

    url_a, url_b = canonical_url(job_a.get("url")), canonical_url(job_b.get("url"))
    if url_a and url_b and url_a == url_b:
        return True

    if (
        job_a.get("external_id")
        and job_b.get("external_id")
        and job_a.get("source") == job_b.get("source")
        and job_a["external_id"] == job_b["external_id"]
    ):
        return True

    return False
