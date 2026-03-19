#!/usr/bin/env python
"""
scripts/wait_for_services.py
─────────────────────────────
Polls Redis until it's ready (only if not in free tier mode).
Used as a Docker entrypoint pre-check before starting Django.

Usage:
    python scripts/wait_for_services.py
    python scripts/wait_for_services.py --timeout 60
"""

import argparse
import os
import sys
import time
from decouple import config

try:
    from redis import Redis
    import redis as redis_lib
except ImportError:
    redis_lib = None
    Redis = None


def wait_for_redis(url: str, timeout: int):
    """Checks Redis connectivity using the built-in ping() method."""
    if Redis is None:
        print("⚠️  Redis library not installed, skipping Redis check.", flush=True)
        return True

    print(f"⏳  Waiting for Redis...", flush=True)
    client = Redis.from_url(url)
    deadline = time.monotonic() + timeout

    while time.monotonic() < deadline:
        try:
            if client.ping():
                print("✅  Redis is ready.", flush=True)
                return True
        except redis_lib.exceptions.ConnectionError:
            time.sleep(1)
        except Exception:
            time.sleep(1)

    print(f"❌  Timed out waiting for Redis ({timeout}s).", file=sys.stderr)
    return False


def main():
    parser = argparse.ArgumentParser(description="Wait for dependent services")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    free_tier = config("FREE_TIER", default=False, cast=bool)
    results = []

    if not free_tier:
        redis_url = config("REDIS_URL", "redis://localhost:6379/0")
        results.append(wait_for_redis(redis_url, args.timeout))
    else:
        print("🏃  Free tier mode - skipping Redis wait.", flush=True)

    if results and not all(results):
        sys.exit(1)

    print("\n🚀  All services ready. Starting application.", flush=True)


if __name__ == "__main__":
    main()
