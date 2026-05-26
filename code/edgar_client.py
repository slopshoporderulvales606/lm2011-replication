"""
Shared SEC EDGAR HTTP client with global rate limiter + retry policy.

- Single requests.Session (keep-alive).
- Token-bucket rate limiter: 8 req/s global, thread-safe (we don't use threads
  here, but the lock costs nothing and future-proofs it).
- tenacity retry on 429/503 and network errors, exponential backoff, max 5 tries.
- User-Agent enforced on every request.
"""

from __future__ import annotations

import os
import sys
import threading
import time
from pathlib import Path

import requests
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

# SEC EDGAR requires a contact User-Agent on every request. Provide your own via
# the SEC_EDGAR_USER_AGENT environment variable, e.g.:
#   export SEC_EDGAR_USER_AGENT="Your Name your.email@example.com"
# See https://www.sec.gov/os/accessing-edgar-data for the policy.
USER_AGENT = os.environ.get("SEC_EDGAR_USER_AGENT", "").strip()
if not USER_AGENT:
    sys.exit(
        "SEC_EDGAR_USER_AGENT env var is not set. "
        "Export it as 'Your Name your.email@example.com' before running."
    )

MAX_RPS = 8.0  # SEC fair-access cap
HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept-Encoding": "gzip, deflate",
    "Host": "www.sec.gov",
}


class RateLimiter:
    """Token bucket: refill at MAX_RPS, capacity = MAX_RPS."""

    def __init__(self, rps: float = MAX_RPS):
        self.rate = rps
        self.capacity = rps
        self.tokens = rps
        self.last = time.monotonic()
        self.lock = threading.Lock()

    def acquire(self) -> None:
        with self.lock:
            now = time.monotonic()
            elapsed = now - self.last
            self.tokens = min(self.capacity, self.tokens + elapsed * self.rate)
            self.last = now
            if self.tokens < 1.0:
                wait = (1.0 - self.tokens) / self.rate
                time.sleep(wait)
                self.tokens = 0.0
                self.last = time.monotonic()
            else:
                self.tokens -= 1.0


class RetryableHTTPError(Exception):
    """Marker for 429/503 so tenacity retries."""


def _make_session() -> requests.Session:
    s = requests.Session()
    s.headers.update(HEADERS)
    return s


SESSION = _make_session()
LIMITER = RateLimiter(MAX_RPS)


@retry(
    reraise=True,
    stop=stop_after_attempt(5),
    wait=wait_exponential(multiplier=1.0, min=1.0, max=30.0),
    retry=retry_if_exception_type((RetryableHTTPError, requests.RequestException)),
)
def get(url: str, *, stream: bool = False, timeout: int = 60) -> requests.Response:
    """Rate-limited GET with retries. Returns the Response (caller closes if streaming)."""
    LIMITER.acquire()
    r = SESSION.get(url, stream=stream, timeout=timeout)
    if r.status_code in (429, 503):
        # Honour Retry-After if present; tenacity backoff handles the rest.
        ra = r.headers.get("Retry-After")
        if ra:
            try:
                time.sleep(min(30.0, float(ra)))
            except ValueError:
                pass
        raise RetryableHTTPError(f"{r.status_code} for {url}")
    r.raise_for_status()
    return r


def download_to_gzip(url: str, dest: Path, *, chunk: int = 1 << 15) -> tuple[int, int, float]:
    """
    Stream a URL to `dest` (raw bytes — caller decides if dest is .gz).
    EDGAR serves master.gz pre-gzipped, and filing .txt as plain text;
    callers compress the latter themselves if needed.

    Returns (http_status, bytes_written, elapsed_seconds).
    """
    dest.parent.mkdir(parents=True, exist_ok=True)
    t0 = time.monotonic()
    r = get(url, stream=True)
    n = 0
    tmp = dest.with_suffix(dest.suffix + ".part")
    with open(tmp, "wb") as fh:
        for blk in r.iter_content(chunk_size=chunk):
            if blk:
                fh.write(blk)
                n += len(blk)
    tmp.replace(dest)
    return r.status_code, n, time.monotonic() - t0
