"""뉴스 수집(Google News RSS) 단위 테스트 — 네트워크 없이 RSS 응답을 흉내낸다.

실행: cd backend && python -m pytest test/test_nasdaq_news.py -v
"""
from urllib.parse import parse_qs, urlparse

import pytest

import services.nasdaq_news as nn

RSS = """<?xml version="1.0"?><rss><channel>{items}</channel></rss>"""
ITEM = "<item><title>{title}</title><guid>{guid}</guid><pubDate>Tue, 27 Oct 2026 09:00:00 GMT</pubDate></item>"


def _rss(titles):
    items = "".join(ITEM.format(title=t, guid=f"g{i}") for i, t in enumerate(titles))
    return RSS.format(items=items).encode()


class _Resp:
    def __init__(self, body):
        self.body = body

    def read(self):
        return self.body

    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


@pytest.fixture
def fake_rss(monkeypatch):
    """검색어(q)의 첫 단어 → 제목 목록. 호출된 q 를 기록한다."""
    feeds, calls = {}, []

    def urlopen(req, timeout=None):
        q = parse_qs(urlparse(req.full_url).query)["q"][0]
        calls.append(q)
        return _Resp(_rss(feeds.get(q.split()[0], [])))

    monkeypatch.setattr(nn.urllib.request, "urlopen", urlopen)
    monkeypatch.setattr(nn, "_RSS_SLEEP", 0)
    return feeds, calls


def test_search_rss_window_and_title_split(fake_rss):
    feeds, calls = fake_rss
    feeds["엔비디아"] = ["엔비디아, 신고가 경신 - 연합뉴스", "제목에 하이픈-없음"]
    out = nn._search_rss("엔비디아 OR Nvidia", "2026-10-27")
    assert calls[0].endswith("after:2026-10-27 before:2026-10-28")
    assert (out[0]["title"], out[0]["source"], out[0]["id"]) == ("엔비디아, 신고가 경신", "연합뉴스", "g0")
    assert out[1]["title"] == "제목에 하이픈-없음" and out[1]["source"] == ""


def test_collect_day_filters_caps_and_dedupes(fake_rss):
    feeds, _ = fake_rss
    feeds["엔비디아"] = [f"엔비디아 기사 {i} - 언론" for i in range(12)] + ["애플만 언급 - 언론"]
    feeds["애플"] = ["엔비디아 기사 0 - 언론", "애플 실적 호조 - 언론"]   # 중복·타 티커 제외
    feeds["연준"] = ["연준 금리 동결 시사 - 언론", "아이돌 연준, 파리 패션위크 - 언론",
                    "엔비디아 기사 99 - 언론"]                         # 인물명·티커 기사 제외
    feeds["관세"] = ["미국 관세 완화 협상 - 언론"]
    b = nn._collect_day("2026-10-27")

    nvda = [h for h in b["tickers"] if h["ticker"] == "NVDA"]
    assert len(nvda) == nn._TICKER_CAP_PER_DAY
    assert [h["title"] for h in b["tickers"] if h["ticker"] == "AAPL"] == ["애플 실적 호조"]
    assert {(h["category"], h["title"]) for h in b["macros"]} == {
        ("연준", "연준 금리 동결 시사"), ("관세", "미국 관세 완화 협상")}
    assert all(h["lead"] == "언론" for h in b["tickers"] + b["macros"])


def test_collect_by_date_range(fake_rss, monkeypatch):
    monkeypatch.setattr(nn, "_collect_day", lambda d: {"tickers": [], "macros": [], "d": d})
    out = nn.collect_by_date("2026-10-30", "2026-11-02")
    assert list(out) == ["2026-10-30", "2026-10-31", "2026-11-01", "2026-11-02"]


def test_search_rss_failure_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise OSError("network down")
    monkeypatch.setattr(nn.urllib.request, "urlopen", boom)
    assert nn._search_rss("엔비디아", "2026-10-27") == []


def test_fetch_rss_created_at_kst(fake_rss):
    feeds, _ = fake_rss
    feeds["미국"] = ["뉴욕증시 마감 - 연합뉴스"]
    out = nn._fetch_rss("미국 증시 when:2d")
    assert out[0]["created_at"] == "2026-10-27T18:00:00+09:00"


class TestNewsRoute:
    ITEMS = [{"id": f"g{i}", "title": f"t{i}", "source": "s", "link": "l",
              "created_at": "2026-10-27T18:00:00+09:00"} for i in range(45)]

    @pytest.fixture(autouse=True)
    def _reset_cache(self, monkeypatch):
        import api.routes as routes
        monkeypatch.setattr(routes, "_NEWS_CACHE", {})

    def test_paging(self, client, monkeypatch):
        monkeypatch.setattr(nn, "latest_news", lambda topic: self.ITEMS)
        r = client.get("/api/news?topic=fed&page=2&page_size=30").json()
        assert r["total_count"] == 45 and [n["id"] for n in r["news_list"]] == [f"g{i}" for i in range(30, 45)]

    def test_unknown_topic(self, client):
        assert client.get("/api/news?topic=nope").status_code == 400

    def test_failure_without_cache(self, client, monkeypatch):
        monkeypatch.setattr(nn, "latest_news", lambda topic: None)
        assert client.get("/api/news?topic=market").status_code == 502
