#!/usr/bin/env python3
"""Discover karting circuits that publish on Apex Timing live-timing.

Apex does NOT expose a public directory of its circuits — each one lives at
`https://<host>/live-timing/<slug>/` (host is either `www.apex-timing.com`
under `/live-timing/`, or the newer `live.apex-timing.com/<slug>/`) with no
autoindex and no sitemap entry. So discovery = a list of candidate slugs
(seeded below; extend with --slug / --slugs-file, harvested e.g. from a
`site:apex-timing.com/live-timing` web search) + validation of each by reading
its `javascript/config.js`, which carries the clean title, websocket port and
GMT.

Usage:
    python scripts/discover_apex_tracks.py                 # validate seed list, print table
    python scripts/discover_apex_tracks.py --json out.json # also dump JSON
    python scripts/discover_apex_tracks.py --slugs-file more.txt
    python scripts/discover_apex_tracks.py --apply         # insert NEW tracks into tracks.db

`--apply` only ADDS tracks whose timing_url isn't already in tracks.db; it never
edits or deletes existing rows. Verify the derived websocket_url with the live
parser before relying on it (config.js gives the port; the host matches the
page host).
"""

import argparse
import html
import json
import re
import sys
import time
import urllib.request
import urllib.error

HOSTS = [
    ("https://www.apex-timing.com/live-timing/{slug}/", "www.apex-timing.com"),
    ("https://live.apex-timing.com/{slug}/", "live.apex-timing.com"),
]
UA = "Mozilla/5.0 (compatible; LT-Analyzer track-discovery)"
TIMEOUT = 15

# Seed slugs harvested from search engines (Apex publishes no master list).
# Extend freely — invalid/dead slugs are skipped silently.
SEED_SLUGS = [
    # already configured locally
    "karting-mariembourg", "spa-francorchamps-karting", "rkc", "kartland",
    "kll-loisirs-douvrin", "eupen", "metz-kart-indoor", "ostricourt", "solokart",
    # harvested from site:apex-timing.com/live-timing web searches
    "karting-genk", "korridas", "worldkarts", "mkracing", "shenington",
    "circuit-de-lenclos", "dunois-kart", "passionkarting16", "rgmmc", "rgmmc2",
    "whiltonmill", "dutchracingseries", "fiakarting", "rushhour-karting",
    "circuit-europe", "capkarting", "sportkarting", "fastlane-indoor-racing",
    "wsk", "ligue-karting-idf", "grand-circuit-du-roussillon",
    "kartbaanoldenzaal", "kartodromodeviana", "cabodomundokarting",
    "sportstimingsystems2", "raktrack", "mk-circuit", "circuitpaulricardkarting",
    "pks-loisirs", "karttiming", "sports-timing-uk", "cumbria", "cronosystem2",
    "kartodromo-lucas-guerrero", "elk-motorsport", "ligue-karting-op", "evokart",
    "lemans-karting", "lavalloisirskart", "kart-escale", "lemans-karting2",
    "cremona-circuit", "ask-puma-forez",
]

# Clean display names for circuits whose config.js title/logo is weak or missing.
NAME_OVERRIDES = {
    "ask-puma-forez": "ASK Puma Forez (Bicêtre)",
}

_CFG_RE = {
    "port": re.compile(r"var\s+configPort\s*=\s*(\d+)"),
    "gmt": re.compile(r"var\s+configGMT\s*=\s*(-?\d+)"),
    "title": re.compile(r"var\s+title\s*=\s*'([^']*)'"),
    "logo": re.compile(r"var\s+logo_title\s*=\s*'([^']*)'"),
}
_TITLE_SUFFIX = re.compile(r"\s*-\s*Live timing.*$|\s*\|\s*By Apex Timing.*$|\s*-\s*Live Timing.*$", re.I)


def _get(url):
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=TIMEOUT) as r:
        return r.status, r.read().decode("utf-8", "replace")


def _clean_name(slug, logo, title):
    if logo and logo.strip():
        return html.unescape(logo).strip()
    if title and title.strip() and title.strip().lower() != "live timing":
        return html.unescape(_TITLE_SUFFIX.sub("", title)).strip()
    return slug.replace("-", " ").title()


def probe(slug):
    """Return a track dict if the slug is a live Apex circuit, else None."""
    for tmpl, host in HOSTS:
        base = tmpl.format(slug=slug)
        try:
            status, body = _get(base + "javascript/config.js")
        except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, OSError):
            continue
        if status != 200:
            continue
        port = _CFG_RE["port"].search(body)
        if not port:
            continue  # not a live-timing config
        m_title = _CFG_RE["title"].search(body)
        m_logo = _CFG_RE["logo"].search(body)
        m_gmt = _CFG_RE["gmt"].search(body)
        return {
            "slug": slug,
            "track_name": NAME_OVERRIDES.get(slug) or _clean_name(
                slug, m_logo.group(1) if m_logo else "", m_title.group(1) if m_title else ""),
            "timing_url": base + "index.html",
            # Apex's client JS builds the feed URL as wss://<host>:(configPort+3)/
            # over https (see commonv2/javascript_live_timing.min.js). Matches the
            # existing tracks (e.g. config 9720 -> 9723).
            "websocket_url": f"wss://{host}:{int(port.group(1)) + 3}/",
            "gmt": int(m_gmt.group(1)) if m_gmt else None,
            "host": host,
        }
    return None


def main():
    ap = argparse.ArgumentParser(description="Discover Apex Timing karting circuits")
    ap.add_argument("--slug", action="append", default=[], help="extra slug (repeatable)")
    ap.add_argument("--slugs-file", help="file with one slug per line")
    ap.add_argument("--json", help="write results as JSON to this path")
    ap.add_argument("--apply", action="store_true", help="insert NEW tracks into tracks.db")
    ap.add_argument("--delay", type=float, default=0.3, help="seconds between requests")
    args = ap.parse_args()

    slugs = list(dict.fromkeys(SEED_SLUGS + args.slug))  # de-dupe, keep order
    if args.slugs_file:
        with open(args.slugs_file) as f:
            slugs += [ln.strip() for ln in f if ln.strip() and not ln.startswith("#")]
    slugs = list(dict.fromkeys(slugs))

    found, misses = [], []
    for slug in slugs:
        rec = probe(slug)
        (found if rec else misses).append(rec or slug)
        print(("  ✓ " + rec["track_name"] + f"  ({rec['host']}, {rec['websocket_url']})")
              if rec else f"  · {slug} — not found", file=sys.stderr)
        time.sleep(args.delay)

    print(f"\nDiscovered {len(found)}/{len(slugs)} live circuits.", file=sys.stderr)
    if args.json:
        with open(args.json, "w") as f:
            json.dump(found, f, indent=2, ensure_ascii=False)
        print(f"Wrote {args.json}", file=sys.stderr)

    if args.apply:
        _apply(found)
    else:
        # machine-readable table on stdout
        for t in found:
            print(f"{t['track_name']}\t{t['websocket_url']}\t{t['timing_url']}")


def _apply(found):
    """Insert tracks not already present (dedup by timing_url), never edit existing."""
    sys.path.insert(0, ".")
    from database_manager import TrackDatabase
    db = TrackDatabase()
    existing = {(t.get("timing_url") or "").rstrip("/") for t in db.get_all_tracks()}
    added = skipped = 0
    for t in found:
        if t["timing_url"].rstrip("/") in existing:
            skipped += 1
            continue
        res = db.add_track(
            track_name=t["track_name"], timing_url=t["timing_url"],
            websocket_url=t["websocket_url"],
            description=f"Auto-discovered from Apex Timing ({t['host']}, GMT{t['gmt']})")
        if isinstance(res, dict) and res.get("error"):
            print(f"  ! {t['track_name']}: {res['error']}", file=sys.stderr)
        else:
            added += 1
    print(f"\nApplied: +{added} new, {skipped} already present. "
          f"Restart the backend so MultiTrackManager picks them up.", file=sys.stderr)


if __name__ == "__main__":
    main()
