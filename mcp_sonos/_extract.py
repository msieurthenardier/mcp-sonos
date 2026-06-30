"""Extract playable audio URLs from a web page.

Single responsibility: given an HTML page URL, fetch it server-side and
return a compact list of direct audio-file URLs (default: ``.mp3``) found
in anchor ``href`` / media ``src`` attributes.

Why this lives in the MCP and not in the agent: a small local model has a
tiny context window (e.g. ministral-3:3b ≈ 12k tokens) and tool results
are budget-capped (~8 KB). A music blog homepage can be 300+ KB of HTML
with the audio links buried tens of KB deep — far past any per-result cap.
Doing the fetch+parse here means the model only ever sees a handful of
clean URLs, never the raw page. See ``controller.playlist_from_page``.

Only plain ``http``/``https`` direct-file links are returned; the same
``validate_http_url`` scheme allow-list used everywhere else applies. MP3
is the safe path on Sonos (see project docs); other extensions are opt-in
via ``extensions``.
"""

from __future__ import annotations

import os
import random
from html.parser import HTMLParser
from urllib.parse import unquote, urljoin, urlparse

import requests

from ._urls import validate_http_url

# A browser-ish UA — some hosts 403 the default ``python-requests`` agent.
_USER_AGENT = "Mozilla/5.0 (compatible; mcp-sonos/1.0; +https://github.com/msieurthenardier/mcp-sonos)"

_DEFAULT_EXTENSIONS = (".mp3",)
_FETCH_TIMEOUT_SECONDS = float(os.environ.get("EXTRACT_FETCH_TIMEOUT_SECONDS", "15"))
# Hard ceiling on how much HTML we will parse, regardless of caller limit —
# keeps a hostile/huge page from blowing memory. The page is fetched fully
# but we stop collecting once we have plenty of candidates.
_MAX_BYTES = 8 * 1024 * 1024


class _AudioLinkParser(HTMLParser):
    """Collect ``href``/``src`` attribute values from a stream of HTML."""

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.urls: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key in ("href", "src") and value:
                self.urls.append(value)


def _title_from_url(url: str) -> str:
    """Derive a human-ish title from an audio URL's filename."""
    path = urlparse(url).path
    base = unquote(path.rsplit("/", 1)[-1])
    for ext in _DEFAULT_EXTENSIONS + (".m4a", ".aac", ".ogg", ".wav"):
        if base.lower().endswith(ext):
            base = base[: -len(ext)]
            break
    return base.strip() or url


def _default_fetcher(url: str) -> str:
    resp = requests.get(
        url,
        timeout=_FETCH_TIMEOUT_SECONDS,
        headers={"User-Agent": _USER_AGENT},
        stream=True,
    )
    resp.raise_for_status()
    # Bound the read so a giant page can't exhaust memory.
    raw = resp.raw.read(_MAX_BYTES, decode_content=True)
    encoding = resp.encoding or "utf-8"
    return raw.decode(encoding, errors="replace")


def extract_audio_urls(
    page_url: str,
    limit: int = 5,
    *,
    offset: int = 0,
    shuffle: bool = False,
    extensions: tuple[str, ...] = _DEFAULT_EXTENSIONS,
    fetcher=_default_fetcher,
) -> list[dict]:
    """Return up to ``limit`` direct audio-file links found on ``page_url``.

    Each item is ``{"url": <absolute http(s) url>, "title": <derived>}``.
    Links are resolved against ``page_url`` (relative → absolute), filtered
    to the given ``extensions``, de-duplicated (order-preserving), and
    validated against the http/https scheme allow-list.

    Selection of which ``limit`` links to return:
    - default (``shuffle=False``): the page-order slice ``[offset:offset+limit]``
      — i.e. skip the first ``offset`` matches, then take ``limit``. This is the
      paging knob: ``offset=0`` is the top of the page, ``offset=limit`` is the
      "next page", etc.
    - ``shuffle=True``: a random sample of ``limit`` links drawn from ALL
      matches on the page (``offset`` is ignored). Use for "surprise me" /
      "random" requests.

    Returns ``[]`` if nothing matches (or ``offset`` is past the end).
    """
    validate_http_url(page_url)
    if limit < 1:
        return []

    html = fetcher(page_url)
    parser = _AudioLinkParser()
    parser.feed(html)

    exts = tuple(e.lower() for e in extensions)
    seen: set[str] = set()
    found: list[str] = []
    for raw in parser.urls:
        absolute = urljoin(page_url, raw.strip())
        # Compare against a query/fragment-stripped path for the extension test.
        path = urlparse(absolute).path.lower()
        if not path.endswith(exts):
            continue
        try:
            validate_http_url(absolute)
        except ValueError:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)
        found.append(absolute)

    if shuffle:
        selected = random.sample(found, min(limit, len(found)))
    else:
        start = max(offset, 0)
        selected = found[start : start + limit]
    return [{"url": u, "title": _title_from_url(u)} for u in selected]
