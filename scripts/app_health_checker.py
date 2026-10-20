#!/usr/bin/env python3
"""Check whether web applications are UP or DOWN based on HTTP status codes."""
import argparse
import json
import socket
import sys
import time
import urllib.error
import urllib.request


def parse_expected(spec):
    """'200-399,404' -> set of ints."""
    codes = set()
    for part in spec.split(","):
        part = part.strip()
        if not part:
            continue
        if "-" in part:
            lo, hi = part.split("-", 1)
            codes.update(range(int(lo), int(hi) + 1))
        else:
            codes.add(int(part))
    return codes


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        return None


def check(url, expected, timeout=5.0, follow_redirects=False):
    """Return dict(url, status, code, response_ms, reason)."""
    opener = urllib.request.build_opener() if follow_redirects else urllib.request.build_opener(_NoRedirect)
    start = time.monotonic()
    code, reason = None, ""
    try:
        with opener.open(urllib.request.Request(url, headers={"User-Agent": "app-health-checker/1.0"}), timeout=timeout) as resp:
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    except TimeoutError:
        reason = "timeout"
    except urllib.error.URLError as exc:
        reason = "timeout" if isinstance(exc.reason, (socket.timeout, TimeoutError)) else f"connection error: {exc.reason}"
    except (ValueError, OSError) as exc:
        reason = f"error: {exc}"
    ms = round((time.monotonic() - start) * 1000, 1)
    if code is not None:
        up = code in expected
        reason = "" if up else f"unexpected status {code}"
    else:
        up = False
    return {"url": url, "status": "UP" if up else "DOWN", "code": code, "response_ms": ms, "reason": reason}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("urls", nargs="+")
    ap.add_argument("--expected", default="200-399", help="expected status codes, e.g. 200-399,404 (default 200-399)")
    ap.add_argument("--timeout", type=float, default=5.0)
    ap.add_argument("--follow-redirects", action="store_true")
    ap.add_argument("--interval", type=float, default=0, help="repeat every N seconds until Ctrl-C and print uptime %%")
    ap.add_argument("--count", type=int, default=0, help="with --interval, stop after N rounds (0 = forever)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    expected = parse_expected(args.expected)
    stats = {u: [0, 0] for u in args.urls}  # [up, total]
    all_up = True
    rounds = 0
    results_log = []
    try:
        while True:
            rounds += 1
            for url in args.urls:
                r = check(url, expected, args.timeout, args.follow_redirects)
                stats[url][1] += 1
                stats[url][0] += r["status"] == "UP"
                all_up = all_up and r["status"] == "UP"
                results_log.append(r)
                if not args.json:
                    extra = " ({})".format(r["reason"]) if r["reason"] else ""
                    print("{} {:<4} {} code={} time={}ms{}".format(time.strftime("%H:%M:%S"), r["status"], url, r["code"], r["response_ms"], extra), flush=True)
            if not args.interval or (args.count and rounds >= args.count):
                break
            time.sleep(args.interval)
    except KeyboardInterrupt:
        pass

    # In single-shot mode the exit code reflects the last round; in interval mode, any failure.
    last = results_log[-len(args.urls):]
    ok = all(r["status"] == "UP" for r in (results_log if args.interval else last))
    summary = {u: {"up": s[0], "checks": s[1], "uptime_percent": round(100.0 * s[0] / s[1], 2) if s[1] else 0.0} for u, s in stats.items()}
    if args.json:
        print(json.dumps({"results": last if not args.interval else results_log, "uptime": summary, "all_up": ok}, indent=2))
    elif args.interval:
        print("\nUptime summary:")
        for u, s in summary.items():
            print("  {}  {:.2f}% ({}/{})".format(u, s["uptime_percent"], s["up"], s["checks"]))
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
