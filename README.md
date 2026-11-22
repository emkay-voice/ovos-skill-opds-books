# <img src='icon.png' card_color='#2E8B6E' width='50' height='50' style='vertical-align:bottom'/> OPDS Books

Reads books aloud from e-book catalogs: any [OPDS](https://opds.io) catalog (OPDS 1 or 2), or a plain Atom/RSS feed
of books, such as [Standard Ebooks](https://standardebooks.org)' new releases.

It is a provider for the [common reading pipeline](https://github.com/andlo/ovos-common-reading-pipeline-plugin),
like the fairy-tale, article and [documents](https://github.com/emkay-voice/ovos-skill-documents) providers. A book
reads the way a story does: it is announced, read a sentence at a time, paused, and continued where it stopped. With
the pipeline's `"player": "ovos-media"`, it is read through the media player and has that player's controls.

Made for [Emkay](https://github.com/emkay-voice/emkay), and meant for any OpenVoiceOS device.

## Usage

- "Read me the book Ivanov"
- "Read the novel Confessions of Zeno"
- "Read a book from Standard Ebooks" (a catalog by its name)
- "Read me a book" / "Read my books" (a book picked at random)
- "Læs bogen Den grimme ælling"
- "Pause", "continue" and "stop", as for any reading

It understands "book", "e-book", "novel" and "my books" in English, Danish, German, Spanish, French, Italian, Dutch
and Portuguese. A book is read in its own language; nothing is translated. Books in the device's language are found
first. A book with no language of its own takes the catalog's (see below), or English.

## Catalogs

In the skill's settings, one catalog per line:

```
url | name | username | password | language
```

Every field except the url can be left out:

```
https://standardebooks.org/feeds/atom/new-releases | Standard Ebooks
https://example.org/opds | Min bogreol | | | da
```

- The **name** is what you call the catalog ("a book from Min bogreol").
- The **username and password** are sent only to the catalog's own site.
- The **language** is used for books whose catalog does not give one.

The skill reads the catalogs at start and then every `refresh_hours` (24 by default), in the background. It follows a
catalog's shelves and pages on its own site, at most 60 pages and 5000 books. It keeps the list, not the books.

### Standard Ebooks

The default catalog is Standard Ebooks' **new releases** feed. It is open to everyone, and the books are free (CC0).
Their full catalog, `https://standardebooks.org/feeds/opds`, and their search are for members of their
[Patrons Circle](https://standardebooks.org/donate#patrons-circle). If you are a member, add it with your email as
the username and an empty password:

```
https://standardebooks.org/feeds/opds | Standard Ebooks | you@example.com |
```

### Other catalogs

Any OPDS catalog works: a Calibre content server (`http://host:8080/opds`), Kavita, Komga, COPS, or an OPDS 2
catalog. Books are read from EPUB first, and from PDF, HTML or text when a book has no EPUB.

[Margin](https://marginpaper.com) has an open OPDS catalog, but its `robots.txt` disallows `/download/`, so it is not
among the defaults. Whether to add it is up to you. The skill downloads a book only when someone asks to hear it, as
an e-reader app does.

## In the control panel

With [ovos-control-panel](https://github.com/OpenVoiceOS/ovos-control-panel) on the device, the skill brings
its own page, **Books**, under **Library**. It shows each catalog with how many books it has, when it was read and,
if it could not be read, why. There you add, change (add one with the same address) and remove catalogs, set how often they are read,
and read them again at once. A password is never shown: leave the field empty to keep it. Changing the catalogs
needs the panel's access token. The page is described in `controlpanel.json`, with its words in
`locale/<lang>/controlpanel.json`: the panel draws it, and no code of the skill runs in the panel.

### The messages behind it

| Message | Data | Answer (`<message>.response`) |
|---|---|---|
| `ovos.opds.catalogs.list` | | `catalogs` (url, name, title, username, login, language, books, fetched, retry_after, error, shown, state; never a password), `refresh_hours`, `refreshing` |
| `ovos.opds.catalogs.set` | `catalogs` (url, name, username, password, language; a password of `null` keeps the one it had), optional `refresh_hours` | as `list`, after saving them and starting to read them |
| `ovos.opds.catalogs.refresh` | | as `list`; the catalogs are read in the background |
| `ovos.opds.catalogs.add` | url, name, username, password, language: one catalog, which changes the one with the same url | as `set`, or `error` |
| `ovos.opds.catalogs.remove` | `url` | as `set` |
| `ovos.opds.catalogs.every` | `refresh_hours` | as `set`, or `error` |

## Being polite to catalogs

- `robots.txt` is honoured when the skill reads a catalog on its own. A book someone asks to hear is fetched
  like an e-reader app fetches it.
- When a site answers "too many requests" or "unavailable", the skill waits as long as its `Retry-After` header asks.
- A book is downloaded only when it is asked for. Its text is kept, so it is not downloaded again for the next
  chapter.
- Requests carry a `User-Agent` that names the skill.

## Searching

A request is first matched against the titles the skill already knows. When nothing matches well, it asks every
catalog that can search (OpenSearch) and waits at most 1.5 seconds, inside the pipeline's 2. Standard Ebooks' search
needs Patrons Circle access, as above.

## What is read

The book itself, from its first chapter. The edition's own pages are left out: title page, imprint, colophon,
copyright page, tables of contents, notes and note markers (EPUB `epub:type`). Paragraphs, headings and list items
are read in order. A table row is read as one line with its cells joined by ": ", which is how a play is set, so it
sounds like "Ivanov: I am reading… presently."

## Install

```bash
pip install ovos-skill-opds-books
```

Like every reading provider, it needs
[ovos-common-reading-pipeline-plugin](https://github.com/andlo/ovos-common-reading-pipeline-plugin) in the intent
pipeline.

## Development

```bash
pip install -e ".[test]"
pytest -c tests/pytest.ini tests
```

The tests serve their own small catalogs: OPDS 1 with shelves and pages, a Standard Ebooks-style Atom feed, RSS, and
OPDS 2. They also build their own books, so nothing is fetched. `test_with_the_pipeline.py` uses the real reading
pipeline to check that the requests above are understood, and that "book a table" and the like are left to their own
skills.

`extract.py` is the same as in ovos-skill-documents; change both together.

## Category
**Entertainment**

## Tags
#books #ebooks #opds #reading #epub #standardebooks #commonreading #provider
