"""Spike 1a: does outbound HTTPS from a-shell's Python work at all?

Run: python3 spikes/spike1_network.py

A fake API key is fine here — we're only testing connectivity/TLS, not auth.
PASS: a real HTTP response with a status code and a JSON error body (e.g. 401
with {"error": {...}}). FAIL: a connection/SSL/timeout exception instead.
"""

import requests

r = requests.get(
    "https://api.anthropic.com/v1/models",
    headers={"x-api-key": "test", "anthropic-version": "2023-06-01"},
    timeout=15,
)
print("status:", r.status_code)
print("body:", r.text[:300])
