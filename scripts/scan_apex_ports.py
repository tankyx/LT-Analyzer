#!/usr/bin/env python3
"""Enumerate ALL live Apex Timing circuits by scanning their websocket feed ports.

Apex confirmed port iteration is acceptable (non-invasive). Each circuit's live
feed is `wss://<host>:(configPort+3)/`; config ports are multiples of 10, so
feed ports end in 3 (e.g. 8313, 9723). This scans that pattern, confirms each
open port actually speaks the Apex live-timing protocol via a short websocket
handshake (and grabs its session title), then names each port from the
config.js discovery (scripts/discover_apex_tracks.py --json) where available.

Polite by default: bounded concurrency, short timeouts, the XXX3 pattern only
(~300 ports, not 30k). Use --all-ports to scan every port in the range.

Usage:
    python scripts/scan_apex_ports.py --names-from /tmp/apex_all.json
    python scripts/scan_apex_ports.py --apply --names-from /tmp/apex_all.json
"""

import argparse
import asyncio
import json
import re
import ssl
import sys

DEFAULT_HOST = "www.apex-timing.com"
_SSL = ssl.create_default_context()
_SSL.check_hostname = False
_SSL.verify_mode = ssl.CERT_NONE
# The feed's `track` command carries the layout/length, which often (not always)
# names the venue, e.g. "CREMONA CIRCUIT - 3.768 km". title1 is the session name.
_TRACK_RE = re.compile(r"(?:^|\n)track\|\|([^\r\n]+)")
_TITLE_RE = re.compile(r"(?:^|\n)title1\|\|([^\r\n]+)")


async def tcp_open(host, port, timeout):
    try:
        fut = asyncio.open_connection(host, port)
        reader, writer = await asyncio.wait_for(fut, timeout)
        writer.close()
        try:
            await writer.wait_closed()
        except Exception:
            pass
        return True
    except Exception:
        return False


async def ws_probe(host, port, timeout):
    """Connect to the feed; return (is_apex, name_hint) within `timeout` seconds.

    name_hint prefers the `track` layout field (often the venue), else title1.
    """
    import websockets
    url = f"wss://{host}:{port}/"
    track = title = None
    try:
        async with websockets.connect(url, ssl=_SSL, open_timeout=timeout,
                                      close_timeout=2, max_size=2**22) as ws:
            deadline = asyncio.get_event_loop().time() + timeout
            saw_apex = False
            while asyncio.get_event_loop().time() < deadline:
                try:
                    msg = await asyncio.wait_for(ws.recv(), timeout=timeout)
                except (asyncio.TimeoutError, Exception):
                    break
                text = msg if isinstance(msg, str) else msg.decode("utf-8", "replace")
                if "|" in text and any(k in text for k in ("grid", "title", "init", "css", "track", "|r")):
                    saw_apex = True
                mt = _TRACK_RE.search(text)
                if mt and mt.group(1).strip():
                    track = mt.group(1).strip()
                mi = _TITLE_RE.search(text)
                if mi and mi.group(1).strip():
                    title = mi.group(1).strip()
                if saw_apex and track:
                    break
            return saw_apex, (track or title)
    except Exception:
        return False, None


async def scan(host, ports, tcp_to, ws_to, concurrency, verify):
    sem = asyncio.Semaphore(concurrency)
    found = []

    async def one(port):
        async with sem:
            if not await tcp_open(host, port, tcp_to):
                return
            if verify:
                is_apex, title = await ws_probe(host, port, ws_to)
                if not is_apex:
                    return
            else:
                title = None
            found.append({"port": port, "title": title,
                          "websocket_url": f"wss://{host}:{port}/"})
            print(f"  ✓ :{port}  {title or ''}", file=sys.stderr)

    await asyncio.gather(*(one(p) for p in ports))
    return sorted(found, key=lambda r: r["port"])


def _names_from(path):
    """port -> clean name, from a discover_apex_tracks.py --json file."""
    out = {}
    try:
        for t in json.load(open(path)):
            m = re.search(r":(\d+)/", t.get("websocket_url", ""))
            if m:
                out[int(m.group(1))] = t["track_name"]
    except Exception:
        pass
    return out


def main():
    ap = argparse.ArgumentParser(description="Scan Apex Timing feed ports")
    ap.add_argument("--host", default=DEFAULT_HOST)
    ap.add_argument("--start", type=int, default=7000)
    ap.add_argument("--end", type=int, default=9999)
    ap.add_argument("--all-ports", action="store_true",
                    help="scan every port (default: only XXX3 feed ports)")
    ap.add_argument("--concurrency", type=int, default=60)
    ap.add_argument("--tcp-timeout", type=float, default=3.0)
    ap.add_argument("--ws-timeout", type=float, default=5.0)
    ap.add_argument("--no-verify", action="store_true",
                    help="skip the websocket confirmation (TCP-open only)")
    ap.add_argument("--names-from", help="discover_apex_tracks.py --json for nice names")
    ap.add_argument("--json", help="write results JSON")
    ap.add_argument("--apply", action="store_true", help="insert NEW tracks into tracks.db")
    args = ap.parse_args()

    if args.all_ports:
        ports = range(args.start, args.end + 1)
    else:
        base = args.start - (args.start % 10) + 3
        ports = range(base, args.end + 1, 10)
    ports = [p for p in ports if 1 <= p <= 65535]
    print(f"Scanning {len(ports)} ports on {args.host} "
          f"({'verify' if not args.no_verify else 'tcp-only'})…", file=sys.stderr)

    found = asyncio.run(scan(args.host, ports, args.tcp_timeout, args.ws_timeout,
                             args.concurrency, not args.no_verify))
    names = _names_from(args.names_from) if args.names_from else {}
    for r in found:
        r["track_name"] = names.get(r["port"]) or r["title"] or f"Apex circuit :{r['port']}"

    print(f"\nFound {len(found)} live feeds.", file=sys.stderr)
    if args.json:
        json.dump(found, open(args.json, "w"), indent=2, ensure_ascii=False)
        print(f"Wrote {args.json}", file=sys.stderr)
    if args.apply:
        _apply(found, args.host)
    else:
        for r in found:
            print(f"{r['track_name']}\t{r['websocket_url']}")


def _apply(found, host):
    sys.path.insert(0, ".")
    from database_manager import TrackDatabase
    db = TrackDatabase()
    existing = {(t.get("websocket_url") or "").rstrip("/") for t in db.get_all_tracks()}
    added = skipped = 0
    for r in found:
        if r["websocket_url"].rstrip("/") in existing:
            skipped += 1
            continue
        res = db.add_track(track_name=r["track_name"], timing_url="",
                           websocket_url=r["websocket_url"],
                           description=f"Discovered via Apex port scan ({host}:{r['port']})")
        if isinstance(res, dict) and res.get("error"):
            print(f"  ! :{r['port']} {r['track_name']}: {res['error']}", file=sys.stderr)
        else:
            added += 1
    print(f"\nApplied: +{added} new, {skipped} already present. "
          f"Restart the backend to begin monitoring them.", file=sys.stderr)


if __name__ == "__main__":
    main()
