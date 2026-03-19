#!/usr/bin/env python
"""
scripts/wait_for_services.py
──────────────────────────────
Polls MongoDB and Redis until they're ready.
Used as a Docker entrypoint pre-check before starting Django.

Usage:
    python scripts/wait_for_services.py
    python scripts/wait_for_services.py --timeout 60
"""
import argparse
import sys
import time
from decouple import config
from pymongo import MongoClient
from redis import Redis

def wait_for_mongodb(uri: str, timeout: int):
    """Checks MongoDB connectivity using the official ping command."""
    print(f"⏳  Waiting for MongoDB Atlas...", flush=True)
    # serverSelectionTimeoutMS prevents the client from hanging forever on a bad URI
    client = MongoClient(uri, serverSelectionTimeoutMS=2000)
    deadline = time.monotonic() + timeout
    
    while time.monotonic() < deadline:
        try:
            # The 'ping' command is the standard way to verify the connection is authenticated
            client.admin.command('ping')
            print("✅  MongoDB is ready.", flush=True)
            return True
        except Exception:
            # Wait 1 second before retrying
            time.sleep(1)
            
    print(f"❌  Timed out waiting for MongoDB ({timeout}s).", file=sys.stderr)
    return False

def wait_for_redis(url: str, timeout: int):
    """Checks Redis connectivity using the built-in ping() method."""
    print(f"⏳  Waiting for Redis...", flush=True)
    client = Redis.from_url(url)
    deadline = time.monotonic() + timeout
    
    while time.monotonic() < deadline:
        try:
            if client.ping():
                print("✅  Redis is ready.", flush=True)
                return True
        except Exception:
            time.sleep(1)
            
    print(f"❌  Timed out waiting for Redis ({timeout}s).", file=sys.stderr)
    return False

def main():
    parser = argparse.ArgumentParser(description="Wait for dependent services")
    parser.add_argument("--timeout", type=int, default=30)
    args = parser.parse_args()

    # Fetch connection strings from .env or use defaults
    database_uri = config("DATABASE_URL", "mongodb://localhost:27017")
    redis_url = config("REDIS_URL", "redis://localhost:6379/0")

    results = [
        wait_for_mongodb(database_uri, args.timeout),
        wait_for_redis(redis_url, args.timeout),
    ]

    # Exit with error if any service failed to respond
    if not all(results):
        sys.exit(1)

    print("\n🚀  All services ready. Starting application.", flush=True)

if __name__ == "__main__":
    main()
