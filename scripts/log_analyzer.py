#!/usr/bin/env python3
"""Analyze Apache/Nginx combined-format access logs (plain, .gz, or stdin)."""
import argparse
import gzip
import json
import re
import sys
from collections import Counter

LINE_RE = re.compile(
    r'^(?P<ip>\S+) \S+ \S+ \[(?P<time>[^\]]+)\] '
    r'"(?P<method>[A-Z]+) (?P<path>\S+)(?: (?P<proto>[^"]*))?" '
    r'(?P<status>\d{3}) (?P<bytes>\d+|-)'
    r'(?: "(?P<referer>[^"]*)" "(?P<agent>[^"]*)")?\s*$'
)


def open_input(path):
    if path in (None, "-"):
        return sys.stdin
    if path.endswith(".gz"):
        return gzip.open(path, "rt", encoding="utf-8", errors="replace")
    return open(path, "r", encoding="utf-8", errors="replace")


def hour_bucket(timestamp):
    # 10/Oct/2023:13:55:36 +0000 -> 2023-10-10 13:00
    try:
        date, hh = timestamp.split(" ")[0].split(":")[0:2]
        day, mon, year = date.split("/")
        months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
        return "%s-%02d-%s %s:00" % (year, months.index(mon) + 1, day, hh)
    except (ValueError, IndexError):
        return "unknown"


def analyze(lines, top_n=5):
    total = malformed = bytes_served = 0
    ips, statuses, pages, not_found, hours = Counter(), Counter(), Counter(), Counter(), Counter()
    for raw in lines:
        raw = raw.strip()
        if not raw:
            continue
        m = LINE_RE.match(raw)
        if not m:
            malformed += 1
            continue
        total += 1
        path = m.group("path").split("?")[0]
        ips[m.group("ip")] += 1
        statuses[m.group("status")] += 1
        pages[path] += 1
        hours[hour_bucket(m.group("time"))] += 1
        if m.group("bytes") != "-":
            bytes_served += int(m.group("bytes"))
        if m.group("status") == "404":
            not_found[path] += 1
    return {
        "total_requests": total,
        "malformed_lines": malformed,
        "unique_ips": len(ips),
        "bytes_served": bytes_served,
        "status_codes": dict(sorted(statuses.items())),
        "not_found_count": sum(not_found.values()),
        "top_404_paths": _top(not_found, top_n),
        "top_pages": _top(pages, top_n),
        "top_ips": _top(ips, top_n),
        "requests_per_hour": dict(sorted(hours.items())),
    }


def _top(counter, n):
    # Sort by count desc, then key asc so output is deterministic.
    return [[k, v] for k, v in sorted(counter.items(), key=lambda kv: (-kv[1], kv[0]))[:n]]


def format_text(r):
    out = [
        "Total requests : %d" % r["total_requests"],
        "Malformed lines: %d" % r["malformed_lines"],
        "Unique IPs     : %d" % r["unique_ips"],
        "Bytes served   : %d" % r["bytes_served"],
        "",
        "Status codes:",
    ]
    out += ["  %s  %d" % kv for kv in r["status_codes"].items()]
    out += ["", "404 responses: %d" % r["not_found_count"], "Top 404 paths:"]
    out += ["  %6d  %s" % (c, p) for p, c in r["top_404_paths"]]
    out += ["", "Top pages:"] + ["  %6d  %s" % (c, p) for p, c in r["top_pages"]]
    out += ["", "Top IPs:"] + ["  %6d  %s" % (c, p) for p, c in r["top_ips"]]
    out += ["", "Requests per hour:"] + ["  %s  %d" % kv for kv in r["requests_per_hour"].items()]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("logfile", nargs="?", default="-", help="log file, .gz file, or - for stdin")
    ap.add_argument("--top", type=int, default=5, help="entries in top-N lists (default 5)")
    ap.add_argument("--json", action="store_true", help="output JSON")
    args = ap.parse_args(argv)
    try:
        with open_input(args.logfile) as fh:
            result = analyze(fh, args.top)
    except OSError as exc:
        print("error: %s" % exc, file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2) if args.json else format_text(result))
    return 0


if __name__ == "__main__":
    sys.exit(main())
