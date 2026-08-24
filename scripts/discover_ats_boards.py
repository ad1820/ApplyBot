"""One-time/occasional helper: probe Greenhouse, Lever and Ashby's public
APIs for each company listed in companies_hiring_in_india.txt to find which
ones actually have a live board on each platform, and cache the resulting
board tokens in config/ats_boards.json.

This is a *discovery* helper, not something that needs to run on every
scheduled job-search pass - re-run it occasionally (e.g. weekly) to pick up
newly-onboarded boards. app/agents/job_agent.py's default_sources() reads
the cached config/ats_boards.json (or ATS_BOARDS_JSON env var fallback, same
file-or-env pattern as the rest of this project's config) so a normal
discovery run never needs live network probing of ~700 companies.

Usage:
    python scripts/discover_ats_boards.py
"""
from __future__ import annotations

import json
import re
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

import httpx

_PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

_COMPANIES_FILE = _PROJECT_ROOT / "companies_hiring_in_india.txt"
_OUTPUT_FILE = _PROJECT_ROOT / "config" / "ats_boards.json"


def _slug_candidates(name: str) -> list[str]:
    """Generate plausible board-token slugs for a company display name.

    ATS board tokens are typically the company's lowercased name with
    spaces/punctuation removed or hyphenated. Deliberately does NOT fall
    back to just the first word of a multi-word name (e.g. "General" from
    "General Electric", "Public" from "Public Sapient") - short, generic
    first-word slugs are highly prone to matching a completely unrelated
    company that happens to have the same common-word board token, which
    would pollute discovery results with irrelevant jobs.
    """
    base = name.strip()
    lowered = base.lower()
    no_punct = re.sub(r"[^a-z0-9\s]", "", lowered)
    words = no_punct.split()
    candidates = {no_punct.replace(" ", ""), no_punct.replace(" ", "-")}
    if len(words) == 1 and words[0]:
        candidates.add(words[0])
    return [c for c in candidates if c and len(c) > 2]


def _names_plausibly_match(expected_name: str, actual_name: str) -> bool:
    """Loose check that a board's self-reported company name plausibly
    corresponds to the company we were probing for - guards against a short
    slug (e.g. "general", "public") coincidentally resolving to a totally
    unrelated company's board."""
    norm = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    expected, actual = norm(expected_name), norm(actual_name)
    if not expected or not actual:
        return True  # can't verify - don't discard on this basis alone
    return expected in actual or actual in expected


def _probe(client: httpx.Client, platform: str, url: str, expected_name: str) -> bool:
    try:
        response = client.get(url, timeout=8.0)
        if response.status_code != 200:
            return False
        data = response.json()
    except (httpx.HTTPError, ValueError):
        return False

    if platform == "greenhouse":
        jobs = data.get("jobs") if isinstance(data, dict) else None
        if not jobs:
            return False
        return _names_plausibly_match(expected_name, jobs[0].get("company_name", ""))
    if platform == "lever":
        return isinstance(data, list) and len(data) > 0
    if platform == "ashby":
        return isinstance(data, dict) and bool(data.get("jobs"))
    return False


def _check_company(name: str) -> dict[str, str]:
    found: dict[str, str] = {}
    with httpx.Client(headers={"User-Agent": "Mozilla/5.0"}) as client:
        for slug in _slug_candidates(name):
            if "greenhouse" not in found and _probe(
                client, "greenhouse", f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs", name
            ):
                found["greenhouse"] = slug
            if "lever" not in found and _probe(
                client, "lever", f"https://api.lever.co/v0/postings/{slug}?mode=json", name
            ):
                found["lever"] = slug
            if "ashby" not in found and _probe(
                client, "ashby", f"https://api.ashbyhq.com/posting-api/job-board/{slug}", name
            ):
                found["ashby"] = slug
    return found


def main() -> int:
    if not _COMPANIES_FILE.is_file():
        print(f"Companies file not found: {_COMPANIES_FILE}")
        return 1

    companies = [
        line.strip()
        for line in _COMPANIES_FILE.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    print(f"Probing {len(companies)} companies for Greenhouse/Lever/Ashby boards...")

    results: dict[str, dict[str, str]] = {"greenhouse": [], "lever": [], "ashby": []}
    with ThreadPoolExecutor(max_workers=20) as pool:
        futures = {pool.submit(_check_company, name): name for name in companies}
        done = 0
        for future in as_completed(futures):
            name = futures[future]
            done += 1
            try:
                found = future.result()
            except Exception as exc:  # noqa: BLE001 - one company failing must not abort the scan
                print(f"[{done}/{len(companies)}] {name}: error {exc}")
                continue
            for platform, slug in found.items():
                results[platform].append(slug)
                print(f"[{done}/{len(companies)}] {name}: {platform} -> {slug}")

    for platform in results:
        results[platform] = sorted(set(results[platform]))

    _OUTPUT_FILE.parent.mkdir(parents=True, exist_ok=True)
    _OUTPUT_FILE.write_text(json.dumps(results, indent=2), encoding="utf-8")

    total = sum(len(v) for v in results.values())
    print(f"\nFound {total} live boards: {len(results['greenhouse'])} Greenhouse, "
          f"{len(results['lever'])} Lever, {len(results['ashby'])} Ashby.")
    print(f"Saved to {_OUTPUT_FILE}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
