#!/usr/bin/env python
"""
scripts/generate_secret_key.py
────────────────────────────────
Run this once to generate a secure SECRET_KEY for .env

Usage:
    python scripts/generate_secret_key.py
"""
import secrets
import string

alphabet = string.ascii_letters + string.digits + "!@#$%^&*(-_=+)"
key = "".join(secrets.choice(alphabet) for _ in range(64))

# Escape $ for Docker Compose
key = key.replace("$", "$$")

print(f'SECRET_KEY="{key}"')
