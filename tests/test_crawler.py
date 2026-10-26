from app.ingest.crawler import PoliteCrawler

ROBOTS = "User-agent: *\nDisallow: /private/\nCrawl-delay: 10\n"


class FakeResponse:
    def __init__(self, status, text=""):
        self.status_code = status
        self.text = text
        self.content = text.encode()


class FakeSession:
    def __init__(self, pages):
        self.pages = pages  # url -> list of responses, served in order
        self.headers = {}
        self.requested = []

    def get(self, url, timeout):
        self.requested.append(url)
        if url.endswith("/robots.txt"):
            return FakeResponse(200, ROBOTS)
        return self.pages[url].pop(0)


class FakeTime:
    def __init__(self):
        self.now = 0.0
        self.sleeps = []

    def clock(self):
        return self.now

    def sleep(self, seconds):
        self.sleeps.append(seconds)
        self.now += seconds


def make_crawler(pages):
    session, fake_time = FakeSession(pages), FakeTime()
    crawler = PoliteCrawler("TestBot/1.0", min_delay=1, session=session,
                            sleep=fake_time.sleep, clock=fake_time.clock)
    return crawler, session, fake_time


def test_identifies_itself_with_user_agent():
    _, session, _ = make_crawler({})
    assert session.headers["User-Agent"] == "TestBot/1.0"


def test_disallowed_urls_are_never_requested():
    crawler, session, _ = make_crawler({})
    result = crawler.fetch("https://site.test/private/page")
    assert not result.ok and "robots" in result.error
    assert session.requested == ["https://site.test/robots.txt"]


def test_crawl_delay_from_robots_is_respected():
    crawler, _, fake_time = make_crawler({
        "https://site.test/a": [FakeResponse(200, "<html>a</html>")],
        "https://site.test/b": [FakeResponse(200, "<html>b</html>")],
    })
    crawler.fetch_all(["https://site.test/a", "https://site.test/b"])
    assert fake_time.sleeps.count(10) == 2  # robots.txt -> a -> b, each 10 s apart


def test_retries_server_errors_then_succeeds():
    crawler, _, _ = make_crawler({"https://site.test/a": [FakeResponse(503), FakeResponse(200, "ok")]})
    result = crawler.fetch("https://site.test/a")
    assert result.ok and result.html == "ok"


def test_does_not_retry_not_found():
    crawler, session, _ = make_crawler({"https://site.test/a": [FakeResponse(404)]})
    result = crawler.fetch("https://site.test/a")
    assert not result.ok and result.status == 404
    assert session.requested.count("https://site.test/a") == 1
