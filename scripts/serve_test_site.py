#!/usr/bin/env python3
"""Serve the test website from ``tests/local_site.py`` on a fixed port.

Handy for poking at the scraper by hand:

    python scripts/serve_test_site.py --port 9911
    curl -s localhost:8000/api/agent/quick -H 'Content-Type: application/json' \\
        -d '{"url":"http://127.0.0.1:9911/","crawl_depth":2}'
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from aiohttp import web  # noqa: E402

from tests.local_site import make_app  # noqa: E402


async def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=9911)
    args = parser.parse_args()

    runner = web.AppRunner(make_app())
    await runner.setup()
    site = web.TCPSite(runner, args.host, args.port)
    await site.start()

    print(f"Test site ready on http://{args.host}:{args.port}/")
    print("Includes /protected/ (cookie-gated), /hotlink/ (Referer-gated), "
          "/vid/stream/master.m3u8 (HLS), /flaky/ (retries) and /large/ (size cap).")
    try:
        await asyncio.Event().wait()
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        await runner.cleanup()


if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass
