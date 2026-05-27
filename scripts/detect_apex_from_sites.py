#!/usr/bin/env python3
"""Venue-first discovery: given karting-venue web pages, detect their live-timing
provider and, when it's Apex, extract the slug and resolve it to a clean track.

Rationale: searching apex-timing.com only finds pages indexed under that domain
and yields no venue names. Going venue-first (a track's own site / an aggregator
page) gives the real venue name, reveals the *current* provider (some venues
moved off Apex, e.g. to Alpha Timing), and surfaces Apex circuits that aren't
indexed under apex-timing.com.

For each input page it fetches the HTML (+ a few common live-timing subpaths if
needed), then:
  - extracts Apex slugs from `www.apex-timing.com/live-timing/<slug>` and
    `live.apex-timing.com/<slug>` links/iframes, and
  - flags other known providers (alphatiming, motorlap, mylaps/speedhive, …).

Apex slugs are resolved via discover_apex_tracks.probe() (clean name + feed).
`--apply` imports resolved Apex tracks into tracks.db (dedup; never edits).

Usage:
    python scripts/detect_apex_from_sites.py --url https://kartingdesfagnes.be/ --resolve
    python scripts/detect_apex_from_sites.py --urls-file venues.txt --apply
    grep -oE 'https?://[^ ]+' urls.txt | python scripts/detect_apex_from_sites.py --resolve
"""

import argparse
import os
import re
import sys
import urllib.request
import urllib.error

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from discover_apex_tracks import probe  # noqa: E402

UA = "Mozilla/5.0 (compatible; LT-Analyzer venue-timing-detector)"
TIMEOUT = 15
# Common places a venue puts its live-timing page if the homepage doesn't link it.
SUBPATHS = ["", "live-timing/", "live-timing", "livetiming/", "live/", "en/live-timing/",
            "en/live-timing-en/", "chrono/", "timing/", "live-timing-fr/"]

APEX_WWW = re.compile(r"www\.apex-timing\.com/live-timing/([a-z0-9][a-z0-9_-]+)", re.I)
APEX_LIVE = re.compile(r"live\.apex-timing\.com/([a-z0-9][a-z0-9_-]+)", re.I)
OTHER_PROVIDERS = {
    "alphatiming": "Alpha Timing", "motorlap.com": "Motorlap", "mylaps": "MYLAPS",
    "speedhive": "MYLAPS Speedhive", "tmtiming": "TM-Timing", "raceresult": "RACE RESULT",
    "kartchrono": "Kart Chrono", "tagheuer": "TAG Heuer",
}
_STRIP = re.compile(r"/?(index\.html?|index\.php)?$", re.I)


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        ctype = r.headers.get("Content-Type", "")
        if "html" not in ctype and "text" not in ctype:
            return ""
        return r.read(2_000_000).decode("utf-8", "replace")


def detect(base_url):
    """Return (apex_slugs:set, other_providers:set) for a venue page."""
    if not base_url.startswith("http"):
        base_url = "https://" + base_url
    slugs, others = set(), set()
    root = base_url.rstrip("/") + "/"
    for sp in SUBPATHS:
        try:
            html = _get(root + sp) if sp else _get(base_url)
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError, ValueError):
            continue
        if not html:
            continue
        for m in APEX_WWW.finditer(html):
            s = _STRIP.sub("", m.group(1))
            if s and s != "commonv2":
                slugs.add(s.lower())
        for m in APEX_LIVE.finditer(html):
            s = _STRIP.sub("", m.group(1))
            if s:
                slugs.add(s.lower())
        for key, name in OTHER_PROVIDERS.items():
            if key in html.lower():
                others.add(name)
        if slugs:
            break  # found Apex on this page; no need to probe more subpaths
    return slugs, others


def main():
    ap = argparse.ArgumentParser(description="Detect live-timing providers on venue sites")
    ap.add_argument("--url", action="append", default=[], help="venue URL (repeatable)")
    ap.add_argument("--urls-file", help="file of venue URLs, one per line")
    ap.add_argument("--resolve", action="store_true", help="resolve Apex slugs to name+feed")
    ap.add_argument("--apply", action="store_true", help="resolve + import into tracks.db")
    args = ap.parse_args()

    urls = list(args.url)
    if args.urls_file:
        urls += [l.strip() for l in open(args.urls_file) if l.strip() and not l.startswith("#")]
    if not sys.stdin.isatty():
        urls += [l.strip() for l in sys.stdin if l.strip().startswith("http")]
    urls = list(dict.fromkeys(urls))

    apex_slugs, provider_notes = set(), []
    for u in urls:
        slugs, others = detect(u)
        if slugs:
            apex_slugs |= slugs
            print(f"  apex: {u} -> {', '.join(sorted(slugs))}", file=sys.stderr)
        elif others:
            provider_notes.append((u, others))
            print(f"  other: {u} -> {', '.join(sorted(others))} (not Apex)", file=sys.stderr)
        else:
            print(f"  none: {u}", file=sys.stderr)

    print(f"\n{len(apex_slugs)} Apex slug(s) across {len(urls)} site(s); "
          f"{len(provider_notes)} on other providers.", file=sys.stderr)

    if args.resolve or args.apply:
        resolved = [r for r in (probe(s) for s in sorted(apex_slugs)) if r]
        for r in resolved:
            print(f"{r['track_name']}\t{r['websocket_url']}\t{r['slug']}")
        if args.apply:
            _apply(resolved)
    else:
        for s in sorted(apex_slugs):
            print(s)


def _apply(resolved):
    sys.path.insert(0, ".")
    from database_manager import TrackDatabase
    db = TrackDatabase()
    existing_ws = {(t.get("websocket_url") or "").rstrip("/") for t in db.get_all_tracks()}
    existing_url = {(t.get("timing_url") or "").rstrip("/") for t in db.get_all_tracks()}
    added = skipped = 0
    for r in resolved:
        if (r["websocket_url"].rstrip("/") in existing_ws
                or r["timing_url"].rstrip("/") in existing_url):
            skipped += 1
            continue
        res = db.add_track(track_name=r["track_name"], timing_url=r["timing_url"],
                           websocket_url=r["websocket_url"],
                           description=f"Venue-first discovery ({r['host']}, GMT{r['gmt']})")
        added += 0 if (isinstance(res, dict) and res.get("error")) else 1
        if isinstance(res, dict) and res.get("error"):
            print(f"  ! {r['track_name']}: {res['error']}", file=sys.stderr)
    print(f"\nApplied: +{added} new, {skipped} already present.", file=sys.stderr)


if __name__ == "__main__":
    main()
