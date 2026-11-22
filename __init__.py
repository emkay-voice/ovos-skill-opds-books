"""
skill OVOS OPDS Books

A provider for ovos-common-reading-pipeline-plugin that reads books from
e-book catalogs: "read me the book Wuthering Heights", "read me a book from
Standard Ebooks", "læs bogen ...". Any OPDS catalog (OPDS 1 or 2) works - the
format e-reader apps use to browse and download books - and so does a plain
Atom or RSS feed whose entries carry the book (Standard Ebooks' new releases
feed). See opds.py for how a catalog is read, and extract.py for the text.

Made for Emkay (https://github.com/emkay-voice/emkay), and meant for any
OpenVoiceOS device.

DECISIONS (see ovos-skill-common-reading-example):

- Catalogs are the user's choice. The default is the one catalog that says
  plainly it may be used this way: Standard Ebooks' open new releases feed
  (their editions are CC0; their full OPDS catalog is a benefit for their
  Patrons Circle, and a member can add it with their own login).
- It behaves like an e-reader app: a catalog's pages are read politely (see
  opds.py), and a book is downloaded only when someone asks for it to be read.
- No translation. A book is offered only in its own language: a request in
  Danish is never answered with an English book read by a Danish voice. A
  catalog that does not say its books' language counts as English, unless
  its "language" setting says otherwise.
- The catalog's name is the source the pipeline names at the end ("It came
  from Standard Ebooks"), and the cover goes with the answer for the
  now-playing screen.
- Vocabulary: "book"/"e-book", "my books", the catalogs' names, and the
  titles of two words or more (at most MAX_ANNOUNCED_TITLES per language).
"""
import hashlib
import json
import random
import re
import threading
import time
from pathlib import Path
from urllib.parse import urlparse

from ovos_bus_client.message import Message
from ovos_bus_client.session import SessionManager
from ovos_utils import classproperty
from ovos_utils.parse import match_one
from ovos_utils.process_utils import RuntimeRequirements
from ovos_workshop.skills import OVOSSkill

from . import opds
from .extract import DocumentError, read_document

COMMON_READING_SEARCH = "ovos.common_reading.search"
COMMON_READING_SEARCH_RESPONSE = "ovos.common_reading.search.response"
COMMON_READING_FETCH_CONTENT = "ovos.common_reading.fetch_content"
COMMON_READING_FETCH_CONTENT_RESPONSE = "ovos.common_reading.fetch_content.response"
COMMON_READING_PING = "ovos.common_reading.ping"
COMMON_READING_PONG = "ovos.common_reading.pong"
COMMON_READING_VOCABULARY = "ovos.common_reading.vocabulary"
COMMON_READING_VOCABULARY_GET = "ovos.common_reading.vocabulary.get"

# for a control-panel page (or anything else): the catalogs, as data.
# Passwords are taken in, never sent out: a catalog only says it has a login.
CATALOGS_LIST = "ovos.opds.catalogs.list"        # -> .response {"catalogs": [...], "refresh_hours"}
CATALOGS_SET = "ovos.opds.catalogs.set"          # {"catalogs": [...]} -> .response, as list
CATALOGS_REFRESH = "ovos.opds.catalogs.refresh"  # -> .response, as list (reading goes on in the background)
CATALOGS_ADD = "ovos.opds.catalogs.add"          # one catalog, added or changed by its url -> as list
CATALOGS_REMOVE = "ovos.opds.catalogs.remove"    # {"url"} -> as list
CATALOGS_EVERY = "ovos.opds.catalogs.every"      # {"refresh_hours"} -> as list

CONTENT_TYPES = ["book"]
DEFAULT_CATALOGS = [{"url": "https://standardebooks.org/feeds/atom/new-releases", "name": "Standard Ebooks"}]
NO_TITLE_CONFIDENCE = 0.9
COLLECTION_HINT_THRESHOLD = 0.85
GOOD_TITLE_SCORE = 0.8     # below this, catalogs that can search are asked too
MIN_TITLE_SCORE = 0.5
LIVE_SEARCH_TIMEOUT = 1.5  # seconds; the pipeline waits 2 for all providers
REFRESH_HOURS = 24
MAX_ANNOUNCED_TITLES = 3000
MAX_BOOK_BYTES = 50 * 1024 * 1024
FALLBACK_COLLECTION_ALIASES = ["my books", "my e-books", "the book catalog"]
FALLBACK_CONTENT_WORDS = ["book", "books", "the book", "e-book", "ebook", "novel", "the novel"]


def _user_agent():
    try:
        from importlib.metadata import version
        ver = version("ovos-skill-opds-books")
    except Exception:
        ver = "unknown"
    return f"ovos-skill-opds-books/{ver} (+https://github.com/emkay-voice/ovos-skill-opds-books)"


USER_AGENT = _user_agent()


def primary_subtag(lang):
    return (lang or "").replace("_", "-").split("-")[0].lower()


def configured_languages(langs):
    return {primary_subtag(lang) for lang in langs or [] if lang}


def _read_voc(path):
    phrases = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        m = re.match(r"^(.*)\(([^)]*)\)(.*)$", line)
        if m:
            phrases += [" ".join(f"{m.group(1)}{alt}{m.group(3)}".split()) for alt in m.group(2).split("|")]
        else:
            phrases += [alt.strip() for alt in line.split("|") if alt.strip()]
    return phrases


def parse_catalogs(value):
    """The catalogs setting: a list of {"url", "name", "username", "password",
    "language"}, or text with one per line: url | name | username | password
    | language (all but the url optional)."""
    if not value:
        return []
    if isinstance(value, str):
        catalogs = []
        for line in value.splitlines():
            parts = [p.strip() for p in line.split("|")]
            if parts and parts[0].startswith(("http://", "https://")):
                parts += [""] * 5
                catalogs.append({"url": parts[0], "name": parts[1], "username": parts[2],
                                 "password": parts[3], "language": parts[4]})
        return catalogs
    return [dict(c) for c in value if isinstance(c, dict) and str(c.get("url", "")).startswith("http")]


class OPDSBooksSkill(OVOSSkill):

    @classproperty
    def runtime_requirements(self):
        return RuntimeRequirements(internet_before_load=False,
                                   network_before_load=False,
                                   requires_internet=True,
                                   requires_network=True,
                                   no_internet_fallback=True,
                                   no_network_fallback=True)

    def initialize(self):
        base = Path(self.file_system.path)
        self.state_file = base / "catalogs.json"
        self.text_cache = base / "text"
        self._lock = threading.RLock()
        self._refreshing = threading.Lock()
        self._preparing = {}   # book id -> threading.Event
        self._found_live = {}  # book id -> Book, from live searches
        self.state = self._load_state()
        self.robots = opds.Robots(self._get_text, USER_AGENT)
        self.add_event(COMMON_READING_SEARCH, self.handle_search)
        self.add_event(f"{COMMON_READING_FETCH_CONTENT}.{self.skill_id}", self.handle_fetch_content)
        self.add_event(COMMON_READING_PING, self.handle_ping)
        self.add_event(COMMON_READING_VOCABULARY_GET, self.handle_vocabulary_get)
        self.add_event(CATALOGS_LIST, self.handle_catalogs_list)
        self.add_event(CATALOGS_SET, self.handle_catalogs_set)
        self.add_event(CATALOGS_REFRESH, self.handle_catalogs_refresh)
        self.add_event(CATALOGS_ADD, self.handle_catalogs_add)
        self.add_event(CATALOGS_REMOVE, self.handle_catalogs_remove)
        self.add_event(CATALOGS_EVERY, self.handle_catalogs_every)
        self.settings_change_callback = lambda: self.refresh(force=True, background=True)
        self._announce_vocabulary()  # what was known at the last start, at once
        self.refresh(background=True)
        self.schedule_repeating_event(lambda: self.refresh(background=True), None, 3600, name="refresh")

    # --- catalogs ---------------------------------------------------------------------------

    def catalogs(self):
        configured = self.settings.get("catalogs")
        return parse_catalogs(configured) if configured is not None else [dict(c) for c in DEFAULT_CATALOGS]

    def _catalog(self, url):
        return next((c for c in self.catalogs() if c["url"] == url), {"url": url})

    def _auth_for(self, url):
        """The login of the catalog `url` belongs to (same site), if any."""
        host = urlparse(url).netloc
        for c in self.catalogs():
            if c.get("username") and urlparse(c["url"]).netloc == host:
                return c["username"], c.get("password") or ""
        return None

    def _get(self, url, limit=MAX_BOOK_BYTES):
        import requests
        r = requests.get(url, timeout=20, stream=True, auth=self._auth_for(url),
                         headers={"User-Agent": USER_AGENT})
        if r.status_code in (429, 503):
            wait = r.headers.get("Retry-After", "3600")
            until = time.time() + (int(wait) if wait.isdigit() else 3600)
            raise opds.Unavailable(f"{url} asks to come back later", until)
        r.raise_for_status()
        data = r.raw.read(limit + 1, decode_content=True)
        if len(data) > limit:
            raise DocumentError(f"{url} is larger than {limit // (1024 * 1024)} MB")
        return data, r.headers.get("content-type", "")

    def _get_text(self, url):
        data, _ = self._get(url, limit=512 * 1024)
        return data.decode("utf-8", errors="replace")

    def _load_state(self):
        try:
            return json.loads(self.state_file.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return {}

    def _save_state(self):
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.state_file.with_suffix(".part")
        tmp.write_text(json.dumps(self.state, ensure_ascii=False), encoding="utf-8")
        tmp.replace(self.state_file)

    def refresh(self, force=False, background=False):
        """Read every catalog that is due (or all, with force); on a thread
        of its own with background. A catalog that cannot be read keeps the
        books it had."""
        if background:
            threading.Thread(target=self.refresh, kwargs={"force": force}, daemon=True,
                             name="ovos-skill-opds-books-refresh").start()
            return
        if not self._refreshing.acquire(blocking=False):
            return  # one refresh at a time
        try:
            changed = False
            hours = float(self.settings.get("refresh_hours") or REFRESH_HOURS)
            urls = [c["url"] for c in self.catalogs()]
            for url in urls:
                known = self.state.get(url, {})
                if time.time() < known.get("retry_after", 0):
                    continue
                if not force and time.time() - known.get("fetched", 0) < hours * 3600:
                    continue
                changed |= self._refresh_catalog(url, known)
            with self._lock:
                for gone in [u for u in self.state if u not in urls]:
                    del self.state[gone]
                    changed = True
                self._save_state()
            if changed:
                self._announce_vocabulary()
        finally:
            self._refreshing.release()

    def _refresh_catalog(self, url, known):
        try:
            start, books = opds.crawl(url, self._get, self.robots)
        except opds.Unavailable as e:
            self.log.warning(f"{e}; trying again after {time.ctime(e.until)}")
            with self._lock:
                self.state.setdefault(url, {})["retry_after"] = e.until
            return False
        except Exception as e:
            self.log.error(f"could not read the catalog {url}: {e}")
            with self._lock:
                # the books it had stay; the error is for a page to show
                self.state.setdefault(url, {})["error"] = str(e)[:300]
            return False
        search, is_description = start.search, start.search_is_description
        if search and is_description:
            try:
                search = opds.opensearch_template(self._get(search, limit=256 * 1024)[0])
            except Exception as e:
                self.log.warning(f"no search for {url}: {e}")
                search = ""
        entry = {"name": start.title, "fetched": time.time(), "search": search,
                 "books": opds.as_dicts(books)}
        with self._lock:
            changed = known.get("books") != entry["books"] or known.get("name") != entry["name"]
            self.state[url] = entry
        return changed

    # --- the catalogs, as data (for a control-panel page) ----------------------------------

    def _catalogs_data(self):
        out = []
        with self._lock:
            for c in self.catalogs():
                known = self.state.get(c["url"], {})
                error = known.get("error") or ""
                out.append({"url": c["url"], "name": c.get("name") or "", "title": known.get("name") or "",
                            "username": c.get("username") or "", "login": bool(c.get("username")),
                            "language": c.get("language") or "", "books": len(known.get("books") or []),
                            "fetched": known.get("fetched"), "retry_after": known.get("retry_after"),
                            "error": error,
                            # as the control panel's page shows it
                            "shown": c.get("name") or known.get("name") or c["url"],
                            "state": "error" if error else ("read" if known.get("fetched") else "new")})
        return {"catalogs": out,
                "refresh_hours": float(self.settings.get("refresh_hours") or REFRESH_HOURS),
                "refreshing": self._refreshing.locked()}

    def handle_catalogs_list(self, message):
        self.bus.emit(message.response(self._catalogs_data()))

    def _save_catalogs(self, catalogs, refresh_hours=None):
        """Keep the catalogs in the skill's settings, read them again, and
        give back the list. A catalog without a password (None) keeps the
        one it had, so a page never needs to know it; one without a user
        name has none."""
        old = {c["url"]: c for c in self.catalogs()}
        lines = []
        for c in parse_catalogs(catalogs):
            password = c.get("password")
            if password is None:
                password = old.get(c["url"], {}).get("password") or ""
            if not c.get("username"):
                password = ""
            fields = [c["url"], c.get("name") or "", c.get("username") or "", password,
                      c.get("language") or ""]
            if any("|" in f or "\n" in f for f in fields):
                continue  # would not survive the one-per-line setting
            line = fields[0] + "".join(f" | {f}" if f else " |" for f in fields[1:])
            lines.append(line.rstrip(" |"))
        self.settings["catalogs"] = "\n".join(lines)
        if refresh_hours is not None:
            self.settings["refresh_hours"] = refresh_hours
        store = getattr(self.settings, "store", None)
        if callable(store):
            store()
        self.refresh(force=True, background=True)
        return self._catalogs_data()

    def _kept(self, but=None):
        """The catalogs there are (but one), each keeping its password."""
        return [dict(c, password=None) for c in self.catalogs() if c["url"] != but]

    def handle_catalogs_set(self, message):
        """Replace the catalogs (a list as _save_catalogs takes it)."""
        self.bus.emit(message.response(self._save_catalogs(message.data.get("catalogs") or [],
                                                           message.data.get("refresh_hours"))))

    def handle_catalogs_add(self, message):
        """Add a catalog, or change the one with the same address."""
        c = {k: str(message.data.get(k) or "").strip() for k in ("url", "name", "username", "language")}
        if not re.match(r"^https?://\S+$", c["url"]):
            self.bus.emit(message.response({"error": "books.err.url"}))
            return
        if any("|" in v or "\n" in v for v in c.values()):
            self.bus.emit(message.response({"error": "books.err.bar"}))
            return
        c["password"] = message.data.get("password") or None
        self.bus.emit(message.response(self._save_catalogs(self._kept(but=c["url"]) + [c])))

    def handle_catalogs_remove(self, message):
        url = str(message.data.get("url") or "")
        self.bus.emit(message.response(self._save_catalogs(self._kept(but=url))))

    def handle_catalogs_every(self, message):
        try:
            hours = min(max(float(message.data.get("refresh_hours")), 1.0), 24.0 * 30)
        except (TypeError, ValueError):
            self.bus.emit(message.response({"error": "books.err.hours"}))
            return
        self.bus.emit(message.response(self._save_catalogs(self._kept(), hours)))

    def handle_catalogs_refresh(self, message):
        self.refresh(force=True, background=True)
        self.bus.emit(message.response(self._catalogs_data()))

    # --- books, by language -----------------------------------------------------------------

    def catalog_name(self, url):
        return self._catalog(url).get("name") or self.state.get(url, {}).get("name") or urlparse(url).netloc

    def _book_language(self, book):
        return primary_subtag(book.language or self._catalog(book.catalog).get("language") or "en")

    def books(self, lang, catalog=None):
        """The books in `lang` (a primary subtag), from one catalog or all."""
        found = []
        with self._lock:
            for url, entry in self.state.items():
                if catalog and url != catalog:
                    continue
                for book in opds.from_dicts(entry.get("books")):
                    if self._book_language(book) == lang:
                        found.append(book)
        return found

    def book(self, book_id):
        if book_id in self._found_live:
            return self._found_live[book_id]
        with self._lock:
            for entry in self.state.values():
                for item in entry.get("books") or []:
                    if item.get("id") == book_id:
                        return opds.from_dicts([item])[0]
        return None

    # --- languages and words -------------------------------------------------------------

    @staticmethod
    def _request_lang(message):
        lang = message.data.get("lang") or message.context.get("lang")
        if not lang and message.context.get("session"):
            lang = SessionManager.get(message).lang
        return lang or None

    def _serves(self, lang):
        return primary_subtag(lang) in configured_languages(self.native_langs)

    def _locale_words(self, name, lang):
        base = Path(__file__).resolve().parent / "locale"
        for folder in sorted(base.iterdir()) if base.is_dir() else []:
            if primary_subtag(folder.name) == primary_subtag(lang) and (folder / f"{name}.voc").is_file():
                return _read_voc(folder / f"{name}.voc")
        return []

    def _aliases(self, lang):
        return self._locale_words("collection", lang) or FALLBACK_COLLECTION_ALIASES

    def _catalog_names(self):
        return {url: self.catalog_name(url) for url in self.state}

    def _vocabulary(self, lang):
        titles = sorted({b.title for b in self.books(lang) if len(b.title.split()) >= 2})
        return {"content_types": {CONTENT_TYPES[0]: self._locale_words("content_type", lang)
                                  or FALLBACK_CONTENT_WORDS},
                "collections": self._aliases(lang) + sorted(set(self._catalog_names().values())),
                "titles": titles[:MAX_ANNOUNCED_TITLES]}

    def _announce_vocabulary(self, langs=None, message=None):
        wanted = {primary_subtag(str(l)) for l in (langs or [])}
        for lang in sorted(configured_languages(self.native_langs)):
            if wanted and lang not in wanted:
                continue
            data = {"skill_id": self.skill_id, "lang": lang, **self._vocabulary(lang)}
            self.bus.emit(message.reply(COMMON_READING_VOCABULARY, data) if message
                          else Message(COMMON_READING_VOCABULARY, data))

    def handle_vocabulary_get(self, message):
        self._announce_vocabulary(message.data.get("langs"), message)

    # --- the reading protocol --------------------------------------------------------------

    def _hinted_catalog(self, hint, lang):
        """(matches, catalog url or None): whether a collection hint is ours,
        and which catalog it names when it names one."""
        if not hint:
            return True, None
        hint = hint.lower()
        names = self._catalog_names()
        if names:
            match, score = match_one(hint, [n.lower() for n in names.values()])
            if score >= COLLECTION_HINT_THRESHOLD:
                return True, next(u for u, n in names.items() if n.lower() == match)
        _, score = match_one(hint, [a.lower() for a in self._aliases(lang)])
        return score >= COLLECTION_HINT_THRESHOLD, None

    def handle_search(self, message):
        lang = primary_subtag(self._request_lang(message) or self.lang)
        if not self._serves(lang):
            return
        ours, catalog = self._hinted_catalog(message.data.get("collection_hint"), lang)
        if not ours:
            return
        content_type = message.data.get("content_type")
        if content_type and content_type.lower() not in CONTENT_TYPES:
            return
        phrase = (message.data.get("phrase") or "").strip()
        books = self.books(lang, catalog)
        if phrase:
            book, confidence = self._best_title(phrase, books)
            if confidence < GOOD_TITLE_SCORE:
                live, live_confidence = self._search_live(phrase, lang, catalog)
                if live is not None and live_confidence > confidence:
                    book, confidence = live, live_confidence
            if book is None or confidence < MIN_TITLE_SCORE:
                return
        else:
            if not books:
                return
            book = random.choice(books)
            confidence = 1.0 if message.data.get("collection_hint") else NO_TITLE_CONFIDENCE
        self.bus.emit(message.reply(COMMON_READING_SEARCH_RESPONSE, {
            "skill_id": self.skill_id,
            "content_id": book.id,
            "title": book.title,
            "author": book.author,
            "source": self.catalog_name(book.catalog),
            "image": book.image,
            "confidence": confidence,
            "machine_translated": False,
        }))
        self._prepare(book.id)

    @staticmethod
    def _best_title(phrase, books):
        if not books:
            return None, 0.0
        by_title = {}
        for book in books:
            by_title.setdefault(book.title.lower(), book)
        match, confidence = match_one(phrase.lower(), list(by_title))
        return by_title[match], confidence

    def _search_live(self, phrase, lang, catalog=None):
        """Ask the catalogs that can search (within LIVE_SEARCH_TIMEOUT)."""
        results = []

        def ask(url, template):
            try:
                query = opds.search_url(template, phrase)
                data, content_type = self._get(query)
                page = opds.parse(data, content_type, query, url)
                results.extend(b for b in page.books if self._book_language(b) == lang)
            except Exception as e:
                self.log.debug(f"search in {url} failed: {e}")

        with self._lock:
            searchable = [(u, e["search"]) for u, e in self.state.items()
                          if e.get("search") and (catalog is None or u == catalog)
                          and time.time() >= e.get("retry_after", 0)]
        threads = [threading.Thread(target=ask, args=s, daemon=True) for s in searchable]
        for t in threads:
            t.start()
        deadline = time.time() + LIVE_SEARCH_TIMEOUT
        for t in threads:
            t.join(max(0.0, deadline - time.time()))
        book, confidence = self._best_title(phrase, list(results))
        if book is not None:
            self._found_live[book.id] = book
        return book, confidence

    def handle_fetch_content(self, message):
        book_id = message.data.get("content_id")
        paragraphs = self._paragraphs(book_id) if book_id else []
        self.bus.emit(message.reply(COMMON_READING_FETCH_CONTENT_RESPONSE,
                                    {"paragraphs": paragraphs or []}))

    def handle_ping(self, message):
        lang = self._request_lang(message)
        if lang and not self._serves(lang):
            return
        self.bus.emit(message.reply(COMMON_READING_PONG, {"skill_id": self.skill_id}))

    # --- a book's text: downloaded when asked for, then kept ----------------------------------

    def _cache_file(self, book):
        key = hashlib.sha1(book.download.encode("utf-8")).hexdigest()[:8]
        return self.text_cache / f"{book.id}-{key}.json"

    def _prepare(self, book_id):
        book = self.book(book_id)
        if book is None or self._cache_file(book).exists():
            return
        with self._lock:
            if book_id in self._preparing:
                return
            self._preparing[book_id] = threading.Event()
        threading.Thread(target=self._download, args=(book,), daemon=True,
                         name=f"ovos-skill-opds-books-{book_id}").start()

    def _download(self, book):
        try:
            data, _ = self._get(book.download)
            name = urlparse(book.download).path.rsplit("/", 1)[-1] or "book"
            suffix = opds.FORMAT_SUFFIX.get(book.format, "")
            if suffix and not name.lower().endswith(suffix):
                name += suffix
            text = read_document(data, name)
            cache = self._cache_file(book)
            cache.parent.mkdir(parents=True, exist_ok=True)
            cache.write_text(json.dumps(text.paragraphs, ensure_ascii=False), encoding="utf-8")
        except Exception as e:
            self.log.error(f"could not get the book {book.title!r}: {e}")
        finally:
            with self._lock:
                event = self._preparing.pop(book.id, None)
            if event:
                event.set()

    def _paragraphs(self, book_id):
        book = self.book(book_id)
        if book is None:
            return []
        self._prepare(book_id)
        with self._lock:
            event = self._preparing.get(book_id)
        if event:
            event.wait(9)  # inside the pipeline's 10 s
        try:
            return json.loads(self._cache_file(book).read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return []

    def shutdown(self):
        try:
            self.bus.emit(Message(COMMON_READING_VOCABULARY, {"skill_id": self.skill_id, "remove": True}))
        except Exception:
            pass
        super().shutdown()
