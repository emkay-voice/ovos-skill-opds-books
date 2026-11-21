"""Reading catalogs: OPDS 1, Atom/RSS with enclosures, OPDS 2, politely."""
import pytest

from conftest import opds
from catalogs import FakeWeb, opds1, opds2, rss, standard_ebooks


def by_title(books):
    return {b.title: b for b in books}


def test_opds1_follows_shelves_and_pages_on_its_own_site():
    web = FakeWeb(opds1())
    start, books = opds.crawl("https://books.example.com/opds.xml", web)
    assert start.title == "Example Classics"
    found = by_title(books)
    assert sorted(found) == ["Den grimme ælling", "Dracula", "Pride and Prejudice", "Wuthering Heights"]
    w = found["Wuthering Heights"]
    assert (w.author, w.language, w.format) == ("Emily Brontë", "en-GB", "application/epub+zip")
    assert w.download == "https://books.example.com/d/wuthering.epub"   # EPUB, not the PDF
    assert w.image == "https://books.example.com/c/wuthering.jpg"       # the cover, not the thumbnail
    assert w.summary == "About Wuthering Heights."
    assert not any("other.example.org" in u for u in web.fetched)


def test_crawl_stops_at_max_pages():
    web = FakeWeb(opds1())
    opds.crawl("https://books.example.com/opds.xml", web, max_pages=2)
    assert len(web.fetched) == 2


def test_robots_txt_is_asked():
    web = FakeWeb(opds1())
    robots = opds.Robots(lambda url: "User-agent: *\nDisallow: /opds/da.xml\n", "test-agent")
    _, books = opds.crawl("https://books.example.com/opds.xml", web, robots)
    assert "Den grimme ælling" not in by_title(books)
    assert "https://books.example.com/opds/da.xml" not in web.fetched


def test_no_robots_txt_asks_nothing():
    def missing(url):
        raise OSError("404")
    assert opds.Robots(missing, "x").allowed("https://a.example/anything")


def test_standard_ebooks_atom_enclosures():
    web = FakeWeb(standard_ebooks())
    start, [book] = opds.crawl("https://se.example.com/feeds/atom/new-releases", web)
    assert (book.title, book.author, book.language) == ("Confessions of Zeno", "Italo Svevo", "")
    assert book.download.endswith("/zeno.epub?source=feed")  # the epub, not kepub or azw3
    assert book.image.endswith("cover-thumbnail.jpg")
    assert start.search == "https://se.example.com/opensearch" and start.search_is_description
    template = opds.opensearch_template(web(start.search)[0])
    assert template == "https://se.example.com/feeds/atom/all?query={searchTerms}"   # the Atom one
    assert opds.search_url(template, "the moonstone") == \
        "https://se.example.com/feeds/atom/all?query=the%20moonstone"


def test_rss_enclosures():
    _, books = opds.crawl("https://rss.example.com/feed.rss", FakeWeb(rss()))
    assert [(b.title, b.author, b.language) for b in books] == [("A Christmas Carol", "Charles Dickens", "en")]


def test_opds2():
    start, books = opds.crawl("https://o2.example.com/opds.json", FakeWeb(opds2()))
    found = by_title(books)
    assert start.title == "OPDS 2 Library"
    assert start.search == "https://o2.example.com/search?query={searchTerms}"
    assert sorted(found) == ["Emma", "Ivanhoe", "Moby Dick"]
    assert (found["Moby Dick"].author, found["Moby Dick"].image) == ("Herman Melville", "https://o2.example.com/moby.jpg")
    assert found["Emma"].language == "en" and found["Ivanhoe"].format == "text/html"


def test_ids_are_stable_and_per_catalog():
    _, a = opds.crawl("https://books.example.com/opds.xml", FakeWeb(opds1()))
    _, b = opds.crawl("https://books.example.com/opds.xml", FakeWeb(opds1()))
    assert [x.id for x in a] == [x.id for x in b]
    assert opds.book_id("cat-a", "urn:x") != opds.book_id("cat-b", "urn:x")


def test_books_round_trip_as_dicts():
    _, books = opds.crawl("https://books.example.com/opds.xml", FakeWeb(opds1()))
    assert opds.from_dicts(opds.as_dicts(books)) == books


def test_search_template_placeholders_are_filled_or_dropped():
    template = "https://x.example/s?q={searchTerms}&n={count?}&p={startPage}&lang={language?}"
    assert opds.search_url(template, "ælling") == "https://x.example/s?q=%C3%A6lling&n=20&p=1&lang="
