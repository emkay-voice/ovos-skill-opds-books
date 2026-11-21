"""Book catalogs: OPDS 1 (Atom), OPDS 2 (JSON), and plain Atom/RSS feeds whose
entries carry a book as an enclosure.

A catalog is read the way an e-reader app reads it, not the way a crawler
does: its own pages are followed (navigation, shelves, the next page), at most
MAX_PAGES of them and only on the catalog's own site, robots.txt is asked
before each page, and a catalog that answers "come back later" (429/503 with
Retry-After) is left alone until then. A book itself is downloaded only when
someone asks to have it read.

What a book is here: an id, a title, an author, a language when the catalog
says, a short summary, a cover, and where to download it (EPUB preferred,
then PDF, HTML, plain text).
"""
import hashlib
import re
import json
import time
import urllib.robotparser
from dataclasses import asdict, dataclass, field
from typing import Callable, Dict, List, Optional, Tuple
from urllib.parse import quote, urljoin, urlparse
from xml.etree import ElementTree as ET

ATOM = "http://www.w3.org/2005/Atom"
DC_TERMS = "http://purl.org/dc/terms/"
DC_ELEMENTS = "http://purl.org/dc/elements/1.1/"
MEDIA = "http://search.yahoo.com/mrss/"
OPENSEARCH = "http://a9.com/-/spec/opensearch/1.1/"

ACQUISITION = "http://opds-spec.org/acquisition"
IMAGE_RELS = ("http://opds-spec.org/image", "http://opds-spec.org/image/thumbnail",
              "http://opds-spec.org/cover", "http://opds-spec.org/thumbnail")
# what we can read, best first
FORMATS = ["application/epub+zip", "application/pdf", "application/xhtml+xml", "text/html", "text/plain"]
FORMAT_SUFFIX = {"application/epub+zip": ".epub", "application/pdf": ".pdf",
                 "application/xhtml+xml": ".html", "text/html": ".html", "text/plain": ".txt"}

MAX_PAGES = 60      # catalog pages read per catalog per refresh
MAX_BOOKS = 5000    # books kept per catalog


@dataclass
class Book:
    id: str
    title: str
    author: str = ""
    language: str = ""     # as the catalog says ("en-GB"), "" when it doesn't
    summary: str = ""
    image: str = ""
    download: str = ""
    format: str = ""       # one of FORMATS
    catalog: str = ""      # the catalog's url, where its login and name are


@dataclass
class Page:
    """One catalog page: its books, the pages it leads to, and how to search."""
    title: str = ""
    books: List[Book] = field(default_factory=list)
    links: List[str] = field(default_factory=list)  # navigation/shelves/next, in order
    search: str = ""  # a search url with {searchTerms}, or an OpenSearch description url
    search_is_description: bool = False


def book_id(catalog: str, key: str) -> str:
    return hashlib.sha1(f"{catalog}\n{key}".encode("utf-8")).hexdigest()[:12]


def _is_catalog_type(media_type: str) -> bool:
    t = (media_type or "").lower()
    return "profile=opds-catalog" in t or t.startswith("application/opds+json") or \
        t.startswith("application/atom+xml")


def _best(candidates: List[Tuple[str, str]]) -> Tuple[str, str]:
    """(url, format) of the most readable download among (url, media type)."""
    ranked = []
    for href, media_type in candidates:
        t = (media_type or "").split(";")[0].strip().lower()
        if t in FORMATS:
            ranked.append((FORMATS.index(t), href, t))
    if not ranked:
        return "", ""
    _, href, t = min(ranked, key=lambda r: r[0])
    return href, t


# --- OPDS 1 / Atom / RSS -----------------------------------------------------------------------

def _text(element, path) -> str:
    found = element.find(path) if element is not None else None
    return " ".join((found.text or "").split()) if found is not None else ""


def parse_xml(data: bytes, base: str, catalog: str) -> Page:
    root = ET.fromstring(data)
    if root.tag == "rss" or root.find("channel") is not None:
        return _parse_rss(root, base, catalog)
    page = Page(title=_text(root, f"{{{ATOM}}}title"))
    for link in root.findall(f"{{{ATOM}}}link"):
        rel, href, t = link.get("rel", ""), link.get("href"), link.get("type", "")
        if not href:
            continue
        if rel == "next":
            page.links.append(urljoin(base, href))
        elif rel == "search":
            page.search = urljoin(base, href)
            page.search_is_description = "opensearchdescription" in t
    for entry in root.findall(f"{{{ATOM}}}entry"):
        downloads, subsection, image = [], None, ""
        for link in entry.findall(f"{{{ATOM}}}link"):
            rel, href, t = link.get("rel", ""), link.get("href"), link.get("type", "")
            if not href:
                continue
            href = urljoin(base, href)
            if rel.startswith(ACQUISITION) or rel == "enclosure":
                downloads.append((href, t))
            elif rel in IMAGE_RELS and (not image or "thumbnail" not in rel):
                image = href
            elif (rel in ("subsection", "collection", "") or rel.startswith("http://opds-spec.org/sort")
                  or rel.startswith("http://opds-spec.org/featured")) and _is_catalog_type(t):
                subsection = href
        thumb = entry.find(f"{{{MEDIA}}}thumbnail")
        if not image and thumb is not None:
            image = thumb.get("url", "")
        download, fmt = _best(downloads)
        if download:
            key = _text(entry, f"{{{ATOM}}}id") or download
            authors = [_text(a, f"{{{ATOM}}}name") for a in entry.findall(f"{{{ATOM}}}author")]
            language = _text(entry, f"{{{DC_TERMS}}}language") or _text(entry, f"{{{DC_ELEMENTS}}}language")
            page.books.append(Book(
                id=book_id(catalog, key), title=_text(entry, f"{{{ATOM}}}title"),
                author=", ".join(a for a in authors if a), language=language,
                summary=_text(entry, f"{{{ATOM}}}summary"), image=image,
                download=download, format=fmt, catalog=catalog))
        elif subsection:
            page.links.append(subsection)
    return page


def _parse_rss(root, base, catalog) -> Page:
    channel = root.find("channel") if root.tag == "rss" else root
    page = Page(title=_text(channel, "title"))
    for item in channel.findall("item"):
        downloads = [(urljoin(base, e.get("url", "")), e.get("type", ""))
                     for e in item.findall("enclosure") if e.get("url")]
        download, fmt = _best(downloads)
        if not download:
            continue
        key = _text(item, "guid") or download
        thumb = item.find(f"{{{MEDIA}}}thumbnail")
        page.books.append(Book(
            id=book_id(catalog, key), title=_text(item, "title"),
            author=_text(item, f"{{{DC_ELEMENTS}}}creator"),
            language=_text(item, f"{{{DC_ELEMENTS}}}language"),
            summary="", image=thumb.get("url", "") if thumb is not None else "",
            download=download, format=fmt, catalog=catalog))
    return page


def opensearch_template(data: bytes) -> str:
    """The Atom (or else any) url template of an OpenSearch description."""
    root = ET.fromstring(data)
    urls = [(u.get("type", ""), u.get("template", "")) for u in root.iter(f"{{{OPENSEARCH}}}Url")]
    for t, template in urls:
        if "atom" in t and template:
            return template
    return next((template for _, template in urls if template), "")


# --- OPDS 2 ----------------------------------------------------------------------------------

def parse_json(data: bytes, base: str, catalog: str) -> Page:
    doc = json.loads(data.decode("utf-8"))
    page = Page(title=(doc.get("metadata") or {}).get("title", ""))
    for link in doc.get("links") or []:
        rels = link.get("rel") if isinstance(link.get("rel"), list) else [link.get("rel", "")]
        href = link.get("href")
        if not href:
            continue
        if "next" in rels:
            page.links.append(urljoin(base, href))
        elif "search" in rels:
            page.search = urljoin(base, href).replace("{?query}", "?query={searchTerms}")
    publications = list(doc.get("publications") or [])
    for group in doc.get("groups") or []:
        publications += group.get("publications") or []
        for nav in group.get("navigation") or []:
            if nav.get("href"):
                page.links.append(urljoin(base, nav["href"]))
    for nav in doc.get("navigation") or []:
        if nav.get("href"):
            page.links.append(urljoin(base, nav["href"]))
    for pub in publications:
        meta = pub.get("metadata") or {}
        downloads, image = [], ""
        for link in pub.get("links") or []:
            rels = link.get("rel") if isinstance(link.get("rel"), list) else [link.get("rel", "")]
            if any(str(r).startswith(ACQUISITION) for r in rels) and link.get("href"):
                downloads.append((urljoin(base, link["href"]), link.get("type", "")))
        for img in pub.get("images") or []:
            if img.get("href"):
                image = urljoin(base, img["href"])
                break
        download, fmt = _best(downloads)
        if not download:
            continue
        author = meta.get("author") or ""
        if isinstance(author, list):
            author = ", ".join(a.get("name", "") if isinstance(a, dict) else str(a) for a in author)
        elif isinstance(author, dict):
            author = author.get("name", "")
        language = meta.get("language") or ""
        if isinstance(language, list):
            language = language[0] if language else ""
        title = meta.get("title") or ""
        if isinstance(title, dict):  # a localized title
            title = next(iter(title.values()), "")
        page.books.append(Book(
            id=book_id(catalog, meta.get("identifier") or download), title=" ".join(str(title).split()),
            author=author, language=language, summary=" ".join(str(meta.get("description") or "").split())[:500],
            image=image, download=download, format=fmt, catalog=catalog))
    return page


def parse(data: bytes, content_type: str, base: str, catalog: str) -> Page:
    if "json" in (content_type or "") or data.lstrip()[:1] in (b"{", b"["):
        return parse_json(data, base, catalog)
    return parse_xml(data, base, catalog)


# --- reading a catalog, politely ----------------------------------------------------------------

class Unavailable(Exception):
    """The catalog asked to be left alone (until `until`)."""

    def __init__(self, message, until: float = 0.0):
        super().__init__(message)
        self.until = until


class Robots:
    """robots.txt, asked once per site and kept for a day."""

    def __init__(self, fetch_text: Callable[[str], str], agent: str):
        self.fetch_text = fetch_text
        self.agent = agent
        self.sites: Dict[str, Tuple[float, Optional[urllib.robotparser.RobotFileParser]]] = {}

    def allowed(self, url: str) -> bool:
        parts = urlparse(url)
        site = f"{parts.scheme}://{parts.netloc}"
        seen, parser = self.sites.get(site, (0.0, None))
        if time.time() - seen > 86400:
            parser = urllib.robotparser.RobotFileParser()
            try:
                parser.parse(self.fetch_text(f"{site}/robots.txt").splitlines())
            except Exception:
                parser = None  # no robots.txt: nothing is asked of us
            self.sites[site] = (time.time(), parser)
        return parser is None or parser.can_fetch(self.agent, url)


def crawl(catalog: str, fetch: Callable[[str], Tuple[bytes, str]], robots: Optional[Robots] = None,
          max_pages: int = MAX_PAGES, max_books: int = MAX_BOOKS) -> Tuple[Page, List[Book]]:
    """Read a catalog from its start page: (the start page, its books).
    Raises Unavailable when the catalog asks to be left alone."""
    site = urlparse(catalog).netloc
    todo, seen, books, by_download = [catalog], set(), [], set()
    start = None
    while todo and len(seen) < max_pages and len(books) < max_books:
        url = todo.pop(0)
        if url in seen or urlparse(url).netloc != site:
            continue
        seen.add(url)
        if robots is not None and not robots.allowed(url):
            continue
        data, content_type = fetch(url)
        page = parse(data, content_type, url, catalog)
        if start is None:
            start = page
        for book in page.books:
            if book.download not in by_download and book.title:
                by_download.add(book.download)
                books.append(book)
        todo += [link for link in page.links if link not in seen]
    return start or Page(), books[:max_books]


SEARCH_RESULTS = 20


def search_url(template: str, phrase: str) -> str:
    """An OpenSearch template filled in: the phrase, the first page of
    SEARCH_RESULTS, and nothing for any other parameter."""
    url = template.replace("{searchTerms}", quote(phrase))
    for name, value in (("count", str(SEARCH_RESULTS)), ("startPage", "1"), ("startIndex", "1")):
        url = url.replace(f"{{{name}}}", value).replace(f"{{{name}?}}", value)
    return re.sub(r"\{[^}]*\}", "", url)


def as_dicts(books: List[Book]) -> List[dict]:
    return [asdict(b) for b in books]


def from_dicts(items: List[dict]) -> List[Book]:
    fields = Book.__dataclass_fields__
    return [Book(**{k: v for k, v in item.items() if k in fields}) for item in items or []]
