"""Spike 1b: does a streamed HTTP response actually arrive incrementally, or
does a-shell/iOS buffer the whole thing before handing it to Python?

Run: python3 spikes/spike1b_streaming.py

This hits an endpoint that deliberately drips 50 bytes over 5 seconds.
PASS: printed timestamps are spread out over ~5 seconds (streaming works —
we can render tokens as they arrive). FAIL: everything prints at once near
the 5s mark (streaming is buffered — the app should default to non-streaming
mode instead).
"""

import time

import requests

start = time.time()
r = requests.get("https://httpbin.org/drip?duration=5&numbytes=50", stream=True, timeout=15)
for chunk in r.iter_content(chunk_size=1):
    print(round(time.time() - start, 2), chunk)
