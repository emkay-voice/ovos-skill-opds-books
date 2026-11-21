"""Plays and edition pages: a table row is a line, the edition's own pages are not read."""
from conftest import extract


def html(body):
    return (f'<html xmlns:epub="http://www.idpf.org/2007/ops"><body>{body}</body></html>').encode()


def test_a_table_row_reads_as_speaker_and_line():
    doc = extract.read_document(html(
        "<h2>Act I</h2><table><tr><td><b>Ivanov</b></td><td>I am reading.</td></tr>"
        "<tr><td>Borkin</td><td><p>Laughs.</p><p>There, there.</p></td></tr></table>"), "play.html")
    assert doc.paragraphs == ["Act I", "Ivanov: I am reading.", "Borkin: Laughs. There, there."]


def test_the_edition_pages_and_notes_are_left_out():
    doc = extract.read_document(html(
        '<section epub:type="titlepage"><h1>Ivanov</h1></section>'
        '<section epub:type="imprint"><p>This ebook is the product of many hours.</p></section>'
        '<p>The garden.<a epub:type="noteref" href="#n1">1</a></p>'
        '<section epub:type="endnotes"><p>1. A note.</p></section>'
        '<section epub:type="colophon"><p>Set in a typeface.</p></section>'), "book.html")
    assert doc.paragraphs == ["The garden."]
