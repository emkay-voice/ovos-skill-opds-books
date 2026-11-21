"""Text out of a book, the way it reads aloud.

This is ovos-skill-documents' extract.py, unchanged: the same formats
(EPUB first of all here, and PDF, HTML, text, Markdown, Word, OpenDocument)
read the same way. Change both together; if a third skill needs it, it
becomes a small package of its own.

Formats: plain text, Markdown, PDF, Word (.docx), OpenDocument (.odt), EPUB
and HTML. Everything works from the document's bytes and its file name, so a
file on disk and one fetched from a url go the same way.

What is left out, because it does not read well aloud: code blocks, tables,
page numbers, scripts and styles, navigation. A paragraph stays a paragraph
(the reading pipeline pauses between them); a line break inside one is just a
space, and a word hyphenated at the end of a line is joined again.
"""
import io
import re
import zipfile
from dataclasses import dataclass, field
from pathlib import PurePosixPath
from typing import List, Optional
from xml.etree import ElementTree as ET

SUPPORTED = {".txt", ".text", ".md", ".markdown", ".pdf", ".docx", ".odt", ".epub", ".html", ".htm"}


class DocumentError(Exception):
    """The document could not be read."""


@dataclass
class Document:
    title: Optional[str] = None
    author: Optional[str] = None
    paragraphs: List[str] = field(default_factory=list)


def suffix(name: str) -> str:
    return PurePosixPath(name.split("?")[0].split("#")[0]).suffix.lower()


def is_supported(name: str) -> bool:
    return suffix(name) in SUPPORTED


def title_from_name(name: str) -> str:
    """'min_rapport-2024.pdf' -> 'min rapport 2024'."""
    stem = PurePosixPath(name.split("?")[0].split("#")[0]).stem
    return " ".join(re.sub(r"[_\-.+]+", " ", stem).split()) or stem


def read_document(data: bytes, name: str) -> Document:
    """The title, author and paragraphs of a document named `name`."""
    kind = suffix(name)
    try:
        if kind in (".txt", ".text"):
            doc = Document(paragraphs=paragraphs_from_text(_decode(data)))
        elif kind in (".md", ".markdown"):
            doc = _markdown(_decode(data))
        elif kind == ".pdf":
            doc = _pdf(data)
        elif kind == ".docx":
            doc = _docx(data)
        elif kind == ".odt":
            doc = _odt(data)
        elif kind == ".epub":
            doc = _epub(data)
        elif kind in (".html", ".htm"):
            doc = _html(_decode(data))
        else:
            raise DocumentError(f"not a format this skill reads: {name}")
    except DocumentError:
        raise
    except Exception as e:  # a broken file, whatever the library raises
        raise DocumentError(f"could not read {name}: {e}") from e
    doc.title = _clean(doc.title) or None
    doc.author = _clean(doc.author) or None
    doc.paragraphs = [p for p in (_clean(p) for p in doc.paragraphs) if p]
    return doc


# --- plain text ------------------------------------------------------------------------

def _decode(data: bytes) -> str:
    """UTF-8 (with or without a BOM), UTF-16 with a BOM, else Windows-1252,
    which is what a text file that is not UTF-8 usually is."""
    if data[:2] in (b"\xff\xfe", b"\xfe\xff"):
        return data.decode("utf-16")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        return data.decode("cp1252", errors="replace")


def _clean(text: Optional[str]) -> str:
    return " ".join((text or "").replace("­", "").split())


_PAGE_NUMBER = re.compile(r"^\s*(-\s*)?(page\s+|side\s+|seite\s+|página\s+|pagina\s+)?\d{1,4}(\s*-)?\s*$",
                          re.IGNORECASE)


def paragraphs_from_text(text: str) -> List[str]:
    """Paragraphs are separated by blank lines; the lines inside one are
    joined, a word hyphenated at a line end ('compli-\\ncated') is joined
    again, and lines that are only a page number are dropped."""
    text = text.replace("\r\n", "\n").replace("\r", "\n").replace("\f", "\n\n")
    paragraphs = []
    for block in re.split(r"\n\s*\n", text):
        lines = [line.strip() for line in block.split("\n")]
        lines = [line for line in lines if line and not _PAGE_NUMBER.match(line)]
        if not lines:
            continue
        joined = lines[0]
        for line in lines[1:]:
            if re.search(r"\w-$", joined) and line[:1].islower():
                joined = joined[:-1] + line
            else:
                joined += " " + line
        paragraphs.append(joined)
    return paragraphs


# --- Markdown ----------------------------------------------------------------------------

def _markdown(text: str) -> Document:
    title = None
    kept = []
    in_code = False
    for line in text.replace("\r\n", "\n").split("\n"):
        stripped = line.strip()
        if stripped.startswith(("```", "~~~")):
            in_code = not in_code
            continue
        if in_code or stripped.startswith("|") or re.match(r"^(-{3,}|\*{3,}|_{3,})$", stripped):
            if not in_code and kept and kept[-1] != "":
                kept.append("")  # a table or a rule ends the paragraph
            continue
        heading = re.match(r"^(#{1,6})\s+(.*?)\s*#*\s*$", stripped)
        if heading:
            if title is None and len(heading.group(1)) == 1:
                title = _inline_markdown(heading.group(2))
            kept += ["", _inline_markdown(heading.group(2)), ""]  # a heading is its own paragraph
            continue
        stripped = re.sub(r"^(>\s*)+", "", stripped)            # quotes
        stripped = re.sub(r"^([-*+]|\d+[.)])\s+", "", stripped)  # list items
        if re.match(r"^([-*+]|\d+[.)])\s+", line.strip()) and kept and kept[-1] != "":
            kept.append("")  # every list item is a paragraph of its own
        kept.append(_inline_markdown(stripped))
    return Document(title=title, paragraphs=paragraphs_from_text("\n".join(kept)))


def _inline_markdown(text: str) -> str:
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)            # images
    text = re.sub(r"\[([^\]]*)\]\([^)]*\)", r"\1", text)        # links: the text
    text = re.sub(r"<[^>]+>", "", text)                         # inline html
    text = re.sub(r"(\*\*|__|\*|_|~~|`)(\S(?:.*?\S)?)\1", r"\2", text)  # emphasis, code
    return text


# --- PDF -----------------------------------------------------------------------------------

def _pdf(data: bytes) -> Document:
    from pypdf import PdfReader
    reader = PdfReader(io.BytesIO(data))
    if reader.is_encrypted:
        try:
            reader.decrypt("")
        except Exception as e:
            raise DocumentError(f"the PDF is protected with a password: {e}") from e
    meta = reader.metadata or {}
    pages = [page.extract_text() or "" for page in reader.pages]
    return Document(title=meta.get("/Title"), author=meta.get("/Author"),
                    paragraphs=paragraphs_from_text("\n\n".join(pages)))


# --- Word ----------------------------------------------------------------------------------

def _docx(data: bytes) -> Document:
    import docx
    document = docx.Document(io.BytesIO(data))
    props = document.core_properties
    paragraphs = [p.text for p in document.paragraphs]
    return Document(title=props.title, author=props.author, paragraphs=paragraphs)


# --- OpenDocument ----------------------------------------------------------------------------

_ODF_TEXT = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
_ODF_OFFICE = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
_ODF_META = "urn:oasis:names:tc:opendocument:xmlns:meta:1.0"
_DC = "http://purl.org/dc/elements/1.1/"


def _odf_text(element) -> str:
    """The text of a paragraph or heading, with <text:s/> as spaces and
    <text:tab/>/<text:line-break/> as a space; notes are left out."""
    parts = [element.text or ""]
    for child in element:
        tag = child.tag.split("}")[-1]
        if tag in ("note", "annotation"):
            pass
        elif tag == "s":
            parts.append(" " * int(child.get(f"{{{_ODF_TEXT}}}c", "1")))
        elif tag in ("tab", "line-break"):
            parts.append(" ")
        else:
            parts.append(_odf_text(child))
        parts.append(child.tail or "")
    return "".join(parts)


def _odt(data: bytes) -> Document:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        content = ET.fromstring(z.read("content.xml"))
        meta = ET.fromstring(z.read("meta.xml")) if "meta.xml" in z.namelist() else None
    title = author = None
    if meta is not None:
        title = meta.findtext(f".//{{{_DC}}}title")
        author = meta.findtext(f".//{{{_DC}}}creator") or meta.findtext(f".//{{{_ODF_META}}}initial-creator")
    body = content.find(f".//{{{_ODF_OFFICE}}}text")
    paragraphs = []
    if body is not None:
        _odf_blocks(body, paragraphs)
    return Document(title=title, author=author, paragraphs=paragraphs)


def _odf_blocks(element, paragraphs):
    """Paragraphs and headings in document order; tables are left out."""
    for child in element:
        tag = child.tag.split("}")[-1]
        if tag in ("p", "h") and child.tag.startswith(f"{{{_ODF_TEXT}}}"):
            paragraphs.append(_odf_text(child))
        elif tag != "table":
            _odf_blocks(child, paragraphs)


# --- HTML and EPUB -----------------------------------------------------------------------

_BLOCKS = ["h1", "h2", "h3", "h4", "h5", "h6", "p", "li", "blockquote", "dd", "dt"]

# parts of a book (EPUB 3 structural semantics, epub:type) that are not the
# work itself: the edition's own pages, tables of contents, notes. Read from
# the start of a book they would come first ("This ebook is the product of
# many hours of hard work by volunteers...").
SKIP_EPUB_TYPES = {"titlepage", "halftitlepage", "imprint", "colophon", "copyright-page", "toc",
                   "landmarks", "loi", "lot", "page-list", "index", "endnotes", "footnotes",
                   "rearnotes", "noteref"}


def _skipped(tag) -> bool:
    return bool(SKIP_EPUB_TYPES & set((tag.get("epub:type") or "").split()))


def html_paragraphs(html: str) -> List[str]:
    """The readable blocks of an HTML page: headings, paragraphs, list
    items, quotes, and table rows. Text is taken with no separator and its
    whitespace collapsed (a space at every tag boundary would put one before
    every comma after a <b>, and stripping would glue words together); a
    <br> is a space. A block inside another block is read once, with it.

    A table row is one paragraph, its cells joined by ": " - that is how a
    play's dialogue is set (Standard Ebooks: the speaker, then the line), so
    it reads "Ivanov: ...". The parts of an EPUB that are not the work
    (SKIP_EPUB_TYPES) are left out."""
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["script", "style", "nav", "header", "footer", "pre",
                              "figure", "aside", "form", "noscript", "sup"]):
        tag.decompose()
    for tag in soup.find_all(_skipped):
        tag.decompose()
    for br in soup.find_all("br"):
        br.replace_with(" ")
    for block in soup.find_all(_BLOCKS):  # blocks read together (in a cell, a quote) stay apart
        block.append(" ")
    paragraphs = []
    for tag in soup.find_all(_BLOCKS + ["tr"]):
        if tag.name == "tr":
            cells = [" ".join(cell.get_text().split()) for cell in tag.find_all(["td", "th"], recursive=False)]
            paragraphs.append(": ".join(cell for cell in cells if cell))
            continue
        if tag.find_parent(_BLOCKS) or tag.find_parent("tr"):
            continue
        paragraphs.append(" ".join(tag.get_text().split()))
    if not paragraphs and soup.body:  # a page with no blocks at all: its text
        paragraphs = paragraphs_from_text(soup.body.get_text("\n"))
    return paragraphs


def _html(html: str) -> Document:
    from bs4 import BeautifulSoup
    soup = BeautifulSoup(html, "html.parser")
    title = soup.title.get_text() if soup.title else None
    author = None
    meta = soup.find("meta", attrs={"name": "author"})
    if meta:
        author = meta.get("content")
    return Document(title=title, author=author, paragraphs=html_paragraphs(html))


def _epub(data: bytes) -> Document:
    with zipfile.ZipFile(io.BytesIO(data)) as z:
        container = ET.fromstring(z.read("META-INF/container.xml"))
        rootfile = next(e.get("full-path") for e in container.iter() if e.tag.endswith("rootfile"))
        opf = ET.fromstring(z.read(rootfile))
        base = str(PurePosixPath(rootfile).parent)
        title = next((e.text for e in opf.iter() if e.tag == f"{{{_DC}}}title"), None)
        author = next((e.text for e in opf.iter() if e.tag == f"{{{_DC}}}creator"), None)
        manifest = {e.get("id"): e.get("href") for e in opf.iter() if e.tag.endswith("}item")}
        spine = [e.get("idref") for e in opf.iter() if e.tag.endswith("}itemref")]
        paragraphs = []
        for idref in spine:
            href = manifest.get(idref)
            if not href:
                continue
            path = str(PurePosixPath(base) / href) if base not in ("", ".") else href
            try:
                paragraphs += html_paragraphs(z.read(path).decode("utf-8", errors="replace"))
            except KeyError:
                continue
    return Document(title=title, author=author, paragraphs=paragraphs)
