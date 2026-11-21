"""Small catalogs of every kind the skill reads, shaped like the real ones
(Margin's OPDS 1, Standard Ebooks' Atom feed, an RSS feed, OPDS 2), served by
a fake web: {url: (body, content type)}."""
import json

NAV = "application/atom+xml;profile=opds-catalog;kind=navigation"
ACQ = "application/atom+xml;profile=opds-catalog;kind=acquisition"


def _entry(title, author, lang, slug, extra_links=""):
    return (f'<entry><title>{title}</title><id>urn:{slug}</id><author><name>{author}</name></author>'
            + (f"<dc:language>{lang}</dc:language>" if lang else "")
            + f'<summary type="text">About {title}.</summary>'
            f'<link rel="http://opds-spec.org/acquisition/open-access" type="application/pdf" href="/d/{slug}.pdf"/>'
            f'<link rel="http://opds-spec.org/acquisition/open-access" type="application/epub+zip" href="/d/{slug}.epub"/>'
            f'<link rel="http://opds-spec.org/image" type="image/jpeg" href="/c/{slug}.jpg"/>'
            f'<link rel="http://opds-spec.org/image/thumbnail" type="image/jpeg" href="/c/{slug}-small.jpg"/>'
            f'{extra_links}</entry>')


def _feed(title, body, links=""):
    return (f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
            f'xmlns:dc="http://purl.org/dc/terms/"><title>{title}</title>{links}{body}</feed>').encode()


def opds1(base="https://books.example.com"):
    """A navigation root with two shelves; the first shelf has a next page;
    one book is on two shelves; a shelf on another site is not followed."""
    root = _feed("Example Classics", "".join([
        f'<entry><title>All books</title><id>all</id><link rel="subsection" type="{ACQ}" href="/opds/all.xml"/></entry>',
        f'<entry><title>Danish</title><id>da</id><link rel="subsection" type="{ACQ}" href="/opds/da.xml"/></entry>',
        f'<entry><title>Elsewhere</title><id>x</id><link rel="subsection" type="{ACQ}" '
        f'href="https://other.example.org/opds.xml"/></entry>',
    ]))
    all1 = _feed("All books (1 of 2)", _entry("Wuthering Heights", "Emily Brontë", "en-GB", "wuthering")
                 + _entry("Pride and Prejudice", "Jane Austen", "en", "pride"),
                 f'<link rel="next" type="{ACQ}" href="/opds/all-2.xml"/>')
    all2 = _feed("All books (2 of 2)", _entry("Dracula", "Bram Stoker", "en", "dracula"))
    da = _feed("Danish", _entry("Den grimme ælling", "H.C. Andersen", "da", "aelling")
               + _entry("Pride and Prejudice", "Jane Austen", "en", "pride"))
    return {f"{base}/opds.xml": (root, NAV), f"{base}/opds/all.xml": (all1, ACQ),
            f"{base}/opds/all-2.xml": (all2, ACQ), f"{base}/opds/da.xml": (da, ACQ)}


def standard_ebooks(base="https://se.example.com"):
    """An Atom feed with the book as enclosures (no language), a media
    thumbnail, and an OpenSearch description."""
    entry = ('<entry><id>{base}/ebooks/{slug}</id><title>{title}</title><author><name>{author}</name></author>'
             '<link href="{base}/ebooks/{slug}" rel="alternate" type="application/xhtml+xml"/>'
             '<link href="{base}/ebooks/{slug}/downloads/{slug}.epub?source=feed" rel="enclosure" '
             'title="Recommended compatible epub" type="application/epub+zip"/>'
             '<link href="{base}/ebooks/{slug}/downloads/{slug}.kepub.epub" rel="enclosure" type="application/kepub+zip"/>'
             '<link href="{base}/ebooks/{slug}/downloads/{slug}.azw3" rel="enclosure" type="application/x-mobipocket-ebook"/>'
             '<media:thumbnail url="{base}/ebooks/{slug}/cover-thumbnail.jpg"/></entry>')
    body = entry.format(base=base, slug="zeno", title="Confessions of Zeno", author="Italo Svevo")
    feed = (f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
            f'xmlns:media="http://search.yahoo.com/mrss/"><title>Standard Ebooks - Newest Ebooks</title>'
            f'<link href="{base}/opensearch" rel="search" type="application/opensearchdescription+xml"/>'
            f'{body}</feed>').encode()
    description = (f'<?xml version="1.0"?><OpenSearchDescription xmlns="http://a9.com/-/spec/opensearch/1.1/">'
                   f'<Url type="text/html" template="{base}/ebooks?query={{searchTerms}}"/>'
                   f'<Url type="application/atom+xml" template="{base}/feeds/atom/all?query={{searchTerms}}"/>'
                   f'</OpenSearchDescription>').encode()
    found = (f'<?xml version="1.0" encoding="utf-8"?><feed xmlns="http://www.w3.org/2005/Atom" '
             f'xmlns:media="http://search.yahoo.com/mrss/"><title>Search</title>'
             + entry.format(base=base, slug="moonstone", title="The Moonstone", author="Wilkie Collins")
             + '</feed>').encode()
    return {f"{base}/feeds/atom/new-releases": (feed, "application/atom+xml"),
            f"{base}/opensearch": (description, "application/opensearchdescription+xml"),
            f"{base}/feeds/atom/all?query=the%20moonstone": (found, "application/atom+xml")}


def rss(base="https://rss.example.com"):
    body = (f'<?xml version="1.0"?><rss version="2.0" xmlns:dc="http://purl.org/dc/elements/1.1/"><channel>'
            f'<title>Book Feed</title><item><title>A Christmas Carol</title><guid>carol</guid>'
            f'<dc:creator>Charles Dickens</dc:creator><dc:language>en</dc:language>'
            f'<enclosure url="{base}/carol.epub" type="application/epub+zip" length="1"/></item>'
            f'<item><title>Only Audio</title><enclosure url="{base}/x.mp3" type="audio/mpeg"/></item>'
            f'</channel></rss>').encode()
    return {f"{base}/feed.rss": (body, "application/rss+xml")}


def opds2(base="https://o2.example.com"):
    root = {"metadata": {"title": "OPDS 2 Library"},
            "links": [{"rel": "next", "href": "/page2.json"},
                      {"rel": "search", "href": "/search{?query}", "templated": True}],
            "navigation": [{"href": "/shelf.json", "title": "A shelf"}],
            "publications": [{"metadata": {"title": "Moby Dick", "author": [{"name": "Herman Melville"}],
                                           "language": "en", "identifier": "urn:moby"},
                              "links": [{"rel": "http://opds-spec.org/acquisition/open-access",
                                         "type": "application/epub+zip", "href": "/moby.epub"}],
                              "images": [{"href": "/moby.jpg"}]}]}
    page2 = {"metadata": {"title": "page 2"},
             "publications": [{"metadata": {"title": "Emma", "author": "Jane Austen", "language": ["en"]},
                               "links": [{"rel": "http://opds-spec.org/acquisition",
                                          "type": "application/epub+zip", "href": "/emma.epub"}]}]}
    shelf = {"metadata": {"title": "shelf"}, "groups": [{"publications": [
        {"metadata": {"title": {"en": "Ivanhoe"}, "author": {"name": "Walter Scott"}},
         "links": [{"rel": "http://opds-spec.org/acquisition", "type": "text/html", "href": "/ivanhoe.html"}]}]}]}
    as_json = lambda d: (json.dumps(d).encode(), "application/opds+json")
    return {f"{base}/opds.json": as_json(root), f"{base}/page2.json": as_json(page2),
            f"{base}/shelf.json": as_json(shelf)}


class FakeWeb:
    """fetch(url) from a dict; records what was fetched."""

    def __init__(self, *sites):
        self.pages = {}
        for site in sites:
            self.pages.update(site)
        self.fetched = []

    def __call__(self, url):
        self.fetched.append(url)
        if url not in self.pages:
            raise OSError(f"404 {url}")
        return self.pages[url]
