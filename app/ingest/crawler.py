"""Polite, robots.txt-aware fetcher for the fixed list of source pages.

It fetches exactly the URLs it is given and never follows links.
"""

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from urllib.parse import urlsplit
from urllib.robotparser import RobotFileParser

import requests

log = logging.getLogger(__name__)

RETRYABLE_STATUS = {429, 500, 502, 503, 504}


@dataclass
class FetchResult:
    url: str
    html: str | None
    status: int | None = None
    error: str | None = None

    @property
    def ok(self) -> bool:
        return self.html is not None


class PoliteCrawler:
    def __init__(
        self,
        user_agent: str,
        min_delay: float = 1.0,
        timeout: float = 20.0,
        max_retries: int = 3,
        session: requests.Session | None = None,
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ):
        self.user_agent = user_agent
        self.min_delay = min_delay
        self.timeout = timeout
        self.max_retries = max_retries
        self.session = session or requests.Session()
        self.session.headers.update(
            {"User-Agent": user_agent, "Accept": "text/html", "Accept-Language": "en"}
        )
        self._sleep = sleep
        self._clock = clock
        self._robots: dict[str, RobotFileParser] = {}
        self._last_request: dict[str, float] = {}

    def fetch_all(self, urls: list[str]) -> list[FetchResult]:
        return [self.fetch(url) for url in urls]

    def fetch(self, url: str) -> FetchResult:
        robots = self._robots_for(url)
        if not robots.can_fetch(self.user_agent, url):
            log.warning("robots.txt disallows %s - skipping", url)
            return FetchResult(url, None, error="disallowed by robots.txt")

        status, error = None, None
        for attempt in range(1, self.max_retries + 1):
            self._wait_turn(url)
            try:
                response = self.session.get(url, timeout=self.timeout)
            except requests.RequestException as exc:
                error = f"{type(exc).__name__}: {exc}"
            else:
                status = response.status_code
                if status == 200:
                    log.info("Fetched %s (%d bytes)", url, len(response.content))
                    return FetchResult(url, response.text, status)
                error = f"HTTP {status}"
                if status not in RETRYABLE_STATUS:
                    break
            log.warning("Attempt %d/%d for %s failed: %s", attempt, self.max_retries, url, error)
            self._sleep(2**attempt)

        return FetchResult(url, None, status, error)

    def _robots_for(self, url: str) -> RobotFileParser:
        parts = urlsplit(url)
        root = f"{parts.scheme}://{parts.netloc}"
        if root in self._robots:
            return self._robots[root]

        parser = RobotFileParser(f"{root}/robots.txt")
        self._robots[root] = parser
        self._wait_turn(url)
        try:
            response = self.session.get(parser.url, timeout=self.timeout)
        except requests.RequestException as exc:
            log.error("Could not read %s (%s) - not crawling this host", parser.url, exc)
            parser.disallow_all = True
            return parser

        # Same rules as RobotFileParser.read(): 401/403 means keep out, other 4xx means no rules.
        if response.status_code in (401, 403):
            parser.disallow_all = True
        elif 400 <= response.status_code < 500:
            parser.allow_all = True
        elif response.status_code >= 500:
            parser.disallow_all = True
        else:
            parser.parse(response.text.splitlines())
        parser.modified()  # marks the rules as loaded so can_fetch() uses them
        return parser

    def _wait_turn(self, url: str) -> None:
        """Sleep so requests to one host are at least `delay` seconds apart."""
        host = urlsplit(url).netloc
        robots = self._robots.get(f"{urlsplit(url).scheme}://{host}")
        crawl_delay = robots.crawl_delay(self.user_agent) if robots else None
        delay = max(self.min_delay, float(crawl_delay or 0))

        last = self._last_request.get(host)
        if last is not None:
            wait = last + delay - self._clock()
            if wait > 0:
                log.debug("Waiting %.1fs before next request to %s", wait, host)
                self._sleep(wait)
        self._last_request[host] = self._clock()
