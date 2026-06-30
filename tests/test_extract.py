"""Unit tests for audio-link extraction (mcp_sonos._extract).

Pure, hardware-free: the ``fetcher`` parameter is injected so no HTTP
happens. Covers extension filtering, relative-URL resolution, dedup,
scheme validation, paging (offset), and random selection (shuffle).
"""

from mcp_sonos._extract import extract_audio_urls

_PAGE = """
<html><body>
  <a href="http://h/01 A - one.mp3">one</a>
  <a href="http://h/02 B - two.mp3">two</a>
  <a href="/rel/03 C - three.mp3">three</a>            <!-- relative -> absolute -->
  <a href="http://h/01 A - one.mp3">dup</a>            <!-- duplicate, dropped -->
  <a href="http://h/notes.pdf">not audio</a>          <!-- wrong extension -->
  <a href="ftp://h/04.mp3">bad scheme</a>             <!-- rejected by allow-list -->
  <source src="http://h/05 E - five.mp3">              <!-- src attr too -->
</body></html>
"""


def _fetch(_url: str) -> str:
    return _PAGE


def test_extracts_filters_resolves_and_dedupes() -> None:
    items = extract_audio_urls("http://h/page", limit=10, fetcher=_fetch)
    urls = [i["url"] for i in items]
    # 5 unique mp3s: 4 absolute http + 1 relative resolved; pdf + ftp excluded.
    assert urls == [
        "http://h/01 A - one.mp3",
        "http://h/02 B - two.mp3",
        "http://h/rel/03 C - three.mp3",
        "http://h/05 E - five.mp3",
    ]
    # Title is derived from the filename with the extension stripped.
    assert items[0]["title"] == "01 A - one"


def test_limit_takes_first_n_in_page_order() -> None:
    items = extract_audio_urls("http://h/page", limit=2, fetcher=_fetch)
    assert [i["title"] for i in items] == ["01 A - one", "02 B - two"]


def test_offset_pages_through() -> None:
    items = extract_audio_urls("http://h/page", limit=2, offset=2, fetcher=_fetch)
    assert [i["title"] for i in items] == ["03 C - three", "05 E - five"]


def test_offset_past_end_is_empty() -> None:
    assert extract_audio_urls("http://h/page", limit=5, offset=99, fetcher=_fetch) == []


def test_shuffle_returns_a_valid_subset() -> None:
    items = extract_audio_urls("http://h/page", limit=2, shuffle=True, fetcher=_fetch)
    all_items = extract_audio_urls("http://h/page", limit=10, fetcher=_fetch)
    all_urls = {i["url"] for i in all_items}
    assert len(items) == 2
    assert len({i["url"] for i in items}) == 2  # no dupes in the sample
    assert all(i["url"] in all_urls for i in items)


def test_limit_below_one_returns_empty() -> None:
    assert extract_audio_urls("http://h/page", limit=0, fetcher=_fetch) == []
