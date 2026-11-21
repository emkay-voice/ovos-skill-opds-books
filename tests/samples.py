"""Small documents of every format, built here so no binaries are committed."""
import io
import zipfile


def pdf(lines, title=None, author=None) -> bytes:
    """A one-page PDF with `lines` of text (Helvetica), and an Info dict."""
    def esc(s):
        return s.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream = "BT /F1 12 Tf 14 TL 72 720 Td " + " ".join(f"({esc(l)}) Tj T*" for l in lines) + " ET"
    info = ""
    if title:
        info += f"/Title ({esc(title)}) "
    if author:
        info += f"/Author ({esc(author)}) "
    objects = [
        "<< /Type /Catalog /Pages 2 0 R >>",
        "<< /Type /Pages /Kids [3 0 R] /Count 1 >>",
        "<< /Type /Page /Parent 2 0 R /MediaBox [0 0 612 792] /Contents 4 0 R "
        "/Resources << /Font << /F1 5 0 R >> >> >>",
        f"<< /Length {len(stream)} >>\nstream\n{stream}\nendstream",
        "<< /Type /Font /Subtype /Type1 /BaseFont /Helvetica >>",
        f"<< {info}>>",
    ]
    out = io.BytesIO()
    out.write(b"%PDF-1.4\n")
    offsets = []
    for i, body in enumerate(objects, start=1):
        offsets.append(out.tell())
        out.write(f"{i} 0 obj\n{body}\nendobj\n".encode("latin-1"))
    xref = out.tell()
    out.write(f"xref\n0 {len(objects) + 1}\n0000000000 65535 f \n".encode())
    for off in offsets:
        out.write(f"{off:010d} 00000 n \n".encode())
    out.write(f"trailer\n<< /Size {len(objects) + 1} /Root 1 0 R /Info 6 0 R >>\n"
              f"startxref\n{xref}\n%%EOF\n".encode())
    return out.getvalue()


def docx(paragraphs, title=None, author=None) -> bytes:
    import docx as python_docx
    d = python_docx.Document()
    for p in paragraphs:
        d.add_paragraph(p)
    table = d.add_table(rows=1, cols=2)
    table.rows[0].cells[0].text = "TABLE CELL"
    if title:
        d.core_properties.title = title
    if author:
        d.core_properties.author = author
    out = io.BytesIO()
    d.save(out)
    return out.getvalue()


def odt(paragraphs, title=None, author=None) -> bytes:
    text_ns = "urn:oasis:names:tc:opendocument:xmlns:text:1.0"
    office_ns = "urn:oasis:names:tc:opendocument:xmlns:office:1.0"
    table_ns = "urn:oasis:names:tc:opendocument:xmlns:table:1.0"
    body = "".join(f"<text:p>{p}</text:p>" for p in paragraphs)
    content = (f'<?xml version="1.0" encoding="UTF-8"?>'
               f'<office:document-content xmlns:office="{office_ns}" xmlns:text="{text_ns}" '
               f'xmlns:table="{table_ns}"><office:body><office:text>'
               f'<text:h>Heading<text:s/>One</text:h>{body}'
               f'<table:table><table:table-row><table:table-cell><text:p>TABLE CELL</text:p>'
               f'</table:table-cell></table:table-row></table:table>'
               f'</office:text></office:body></office:document-content>')
    meta = (f'<?xml version="1.0" encoding="UTF-8"?>'
            f'<office:document-meta xmlns:office="{office_ns}" xmlns:dc="http://purl.org/dc/elements/1.1/">'
            f'<office:meta>' + (f"<dc:title>{title}</dc:title>" if title else "")
            + (f"<dc:creator>{author}</dc:creator>" if author else "") + '</office:meta></office:document-meta>')
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("mimetype", "application/vnd.oasis.opendocument.text")
        z.writestr("content.xml", content)
        z.writestr("meta.xml", meta)
    return out.getvalue()


def epub(chapters, title=None, author=None) -> bytes:
    out = io.BytesIO()
    with zipfile.ZipFile(out, "w") as z:
        z.writestr("mimetype", "application/epub+zip")
        z.writestr("META-INF/container.xml",
                   '<?xml version="1.0"?><container version="1.0" '
                   'xmlns="urn:oasis:names:tc:opendocument:xmlns:container"><rootfiles>'
                   '<rootfile full-path="OEBPS/content.opf" media-type="application/oebps-package+xml"/>'
                   '</rootfiles></container>')
        items = "".join(f'<item id="c{i}" href="c{i}.xhtml" media-type="application/xhtml+xml"/>'
                        for i in range(len(chapters)))
        # the spine, not the manifest, is the reading order: list it backwards
        spine = "".join(f'<itemref idref="c{i}"/>' for i in range(len(chapters)))
        z.writestr("OEBPS/content.opf",
                   '<?xml version="1.0"?><package xmlns="http://www.idpf.org/2007/opf" version="3.0">'
                   '<metadata xmlns:dc="http://purl.org/dc/elements/1.1/">'
                   + (f"<dc:title>{title}</dc:title>" if title else "")
                   + (f"<dc:creator>{author}</dc:creator>" if author else "")
                   + f'</metadata><manifest>{items[::-1] if False else items}</manifest>'
                   f'<spine>{spine}</spine></package>')
        for i, paragraphs in enumerate(chapters):
            body = "".join(f"<p>{p}</p>" for p in paragraphs)
            z.writestr(f"OEBPS/c{i}.xhtml",
                       f'<html xmlns="http://www.w3.org/1999/xhtml"><body><h1>Chapter {i + 1}</h1>'
                       f'{body}</body></html>')
    return out.getvalue()
