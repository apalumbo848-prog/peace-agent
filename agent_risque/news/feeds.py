"""Lecture des flux RSS, rattachement d'un article à une action, texte intégral (stdlib seulement).

Le contenu d'un article est une DONNÉE : il n'est jamais exécuté ni suivi comme une consigne.
Réseau : seulement http(s), délai court, taille limitée. Toute panne d'une source est notée et ignorée.
"""

from __future__ import annotations

import email.utils
import re
import urllib.request
import xml.etree.ElementTree as ET
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from html import unescape
from html.parser import HTMLParser
from typing import Callable
from urllib.parse import urlsplit

from .. import config

MAX_BYTES = 3_000_000
Fetcher = Callable[[str], bytes]


@dataclass
class Article:
    id: str
    source_id: str
    source_name: str
    orientation: str
    title: str
    link: str
    published: str                       # AAAA-MM-JJ, ou "" si inconnue
    summary: str
    text: str = ""                       # texte intégral si disponible, sinon vide
    per_ticker: bool = False             # vient d'un flux propre à l'action (déjà pertinent)
    extra: dict = field(default_factory=dict)

    def body(self) -> str:
        return self.text or self.summary


def fetch_bytes(url: str) -> bytes:
    if urlsplit(url).scheme not in ("http", "https"):
        raise ValueError("schéma non autorisé")
    request = urllib.request.Request(url, headers={"User-Agent": config.NEWS_USER_AGENT, "Accept": "*/*"})
    with urllib.request.urlopen(request, timeout=config.NEWS_FETCH_TIMEOUT_S) as response:      # noqa: S310
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError("réponse trop volumineuse")
    return data


def _strip_tags(text: str) -> str:
    return re.sub(r"\s+", " ", unescape(re.sub(r"<[^>]+>", " ", text or ""))).strip()


def _date(raw: str) -> str:
    try:
        return email.utils.parsedate_to_datetime(raw).date().isoformat()
    except (TypeError, ValueError):
        m = re.match(r"(\d{4}-\d{2}-\d{2})", raw or "")
        return m.group(1) if m else ""


def parse_feed(data: bytes, source: dict, start_index: int = 0) -> list[Article]:
    """RSS 2.0 -> articles. Refuse un document qui déclare des entités (protection contre les bombes XML)."""
    head = data[:4000].upper()
    if b"<!DOCTYPE" in head and b"<!ENTITY" in data.upper():
        raise ValueError("document refusé : entités déclarées")
    root = ET.fromstring(data)
    articles = []
    for i, item in enumerate(root.iter("item")):
        def text_of(tag: str) -> str:
            node = item.find(tag)
            return "".join(node.itertext()) if node is not None else ""
        title = _strip_tags(text_of("title"))
        link = (item.findtext("link") or "").strip()
        if not title or urlsplit(link).scheme not in ("http", "https"):
            continue
        desc = text_of("description")
        content = ""
        for child in item:
            if child.tag.endswith("encoded") and child.text:
                content = child.text
        articles.append(Article(
            id=f"{source['id']}-{start_index + i}", source_id=source["id"], source_name=source["name"],
            orientation=source["orientation"], title=title, link=link,
            published=_date(item.findtext("pubDate") or item.findtext("{http://purl.org/dc/elements/1.1/}date") or ""),
            summary=_strip_tags(desc)[:1200], text=_strip_tags(content)[:config.NEWS_ARTICLE_MAX_CHARS],
            per_ticker=bool(source.get("per_ticker"))))
    return articles


def fetch_source(source: dict, ticker: str, fetcher: Fetcher | None = None) -> tuple[list[Article], str]:
    """(articles, statut) ; le statut est « ok » ou la raison de la panne."""
    fetcher = fetcher or fetch_bytes
    url = source["url"].format(symbol=ticker) if source.get("per_ticker") else source["url"]
    try:
        return parse_feed(fetcher(url), source), "ok"
    except Exception as exc:                                 # réseau, XML invalide, source disparue
        return [], f"indisponible ({type(exc).__name__})"


def fetch_all(ticker: str, fetcher: Fetcher | None = None) -> tuple[list[Article], dict[str, str]]:
    """Toutes les sources en parallèle. Retourne les articles et le statut de chaque source."""
    sources = config.NEWS_SOURCES
    with ThreadPoolExecutor(max_workers=len(sources)) as pool:
        results = list(pool.map(lambda s: fetch_source(s, ticker, fetcher), sources))
    articles: list[Article] = []
    status: dict[str, str] = {}
    for source, (items, state) in zip(sources, results):
        articles += items
        status[source["id"]] = state
    return articles, status


# ------------------------------------------------------------------ pertinence

_STOP = re.compile(r"\s*\(.*?\)|\b(?:inc|corp|corporation|etf|trust|class a|index|fund)\b\.?", flags=re.IGNORECASE)


def terms_for(ticker: str, name: str) -> tuple[list[str], list[str]]:
    """(termes insensibles à la casse, termes sensibles à la casse) qui rattachent un article à l'action."""
    loose = [t for t in config.NEWS_ALIASES.get(ticker, ())]
    cleaned = _STOP.sub("", name).strip(" ,.-")
    if len(cleaned) >= 4 and not any(w in name.lower() for w in ("etf", "index", "trust")):
        loose.append(cleaned)
    strict = []
    base = ticker.split(".")[0].split("-")[0]
    if len(base) >= 4:
        strict.append(base)
    return loose, strict


def is_relevant(article: Article, ticker: str, name: str) -> bool:
    if article.per_ticker:
        return True
    loose, strict = terms_for(ticker, name)
    haystack = f"{article.title} {article.summary} {article.text}"
    low = haystack.lower()
    for t in loose:
        if re.search(rf"(?<!\w){re.escape(t.lower())}(?!\w)", low):
            return True
    return any(re.search(rf"(?<!\w){re.escape(t)}(?!\w)", haystack) for t in strict)


def select(articles: list[Article], ticker: str, name: str) -> list[Article]:
    """Articles pertinents, les plus récents d'abord, au plus NEWS_MAX_ARTICLES_PER_TICKER (au moins 1 par source)."""
    relevant = [a for a in articles if is_relevant(a, ticker, name)]
    relevant.sort(key=lambda a: a.published, reverse=True)
    chosen: list[Article] = []
    seen_sources: set[str] = set()
    for a in relevant:                                       # d'abord un article par source (diversité)
        if a.source_id not in seen_sources:
            chosen.append(a)
            seen_sources.add(a.source_id)
    for a in relevant:
        if len(chosen) >= config.NEWS_MAX_ARTICLES_PER_TICKER:
            break
        if a not in chosen:
            chosen.append(a)
    return chosen[:config.NEWS_MAX_ARTICLES_PER_TICKER]


# ------------------------------------------------------------------ texte intégral

class _Paragraphs(HTMLParser):
    SKIP = {"script", "style", "nav", "footer", "aside", "header", "form", "noscript"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.depth_skip = 0
        self.in_p = False
        self.parts: list[str] = []
        self.buf: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in self.SKIP:
            self.depth_skip += 1
        elif tag == "p" and not self.depth_skip:
            self.in_p, self.buf = True, []

    def handle_endtag(self, tag):
        if tag in self.SKIP and self.depth_skip:
            self.depth_skip -= 1
        elif tag == "p" and self.in_p:
            text = re.sub(r"\s+", " ", "".join(self.buf)).strip()
            if len(text) >= 40:
                self.parts.append(text)
            self.in_p = False

    def handle_data(self, data):
        if self.in_p and not self.depth_skip:
            self.buf.append(data)


def extract_text(html_bytes: bytes) -> str:
    parser = _Paragraphs()
    parser.feed(html_bytes.decode("utf-8", errors="replace"))
    return " ".join(parser.parts)[:config.NEWS_ARTICLE_MAX_CHARS]


def load_full_text(articles: list[Article], fetcher: Fetcher | None = None) -> None:
    """Remplit `text` quand la page est lisible (meilleur effort : sinon on garde le résumé du flux)."""
    fetcher = fetcher or fetch_bytes

    def one(a: Article) -> None:
        if len(a.text) >= 500:
            return
        try:
            text = extract_text(fetcher(a.link))
        except Exception:
            return
        if len(text) > len(a.text) and len(text) >= 300:
            a.text = text

    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(one, articles))
