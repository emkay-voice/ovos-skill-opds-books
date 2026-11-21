"""The skill on a bus, with a fake web of catalogs and books."""
import threading
import time
from unittest.mock import MagicMock

import pytest
from ovos_bus_client.message import Message
from ovos_utils.fakebus import FakeBus

from conftest import opds, skill_module
from catalogs import FakeWeb, opds1, standard_ebooks
import samples

Skill = skill_module.OPDSBooksSkill
CLASSICS = "https://books.example.com/opds.xml"
SE = "https://se.example.com/feeds/atom/new-releases"


class FakeFileSystem:
    def __init__(self, path):
        self.path = str(path)


class Recorder:
    def __init__(self, bus, *topics):
        self.messages = []
        for topic in topics:
            bus.on(topic, self.messages.append)

    def of(self, topic):
        return [m for m in self.messages if m.msg_type == topic]


def book_files(*slugs, base="https://books.example.com"):
    return {f"{base}/d/{slug}.epub": (samples.epub([[f"{slug} chapter one.", "The end."]], title=slug),
                                       "application/epub+zip") for slug in slugs}


def make_skill(tmp_path, monkeypatch, catalogs, web, langs=("en-us", "da-dk")):
    bus = FakeBus()
    s = Skill.__new__(Skill)
    s.log = MagicMock()
    s.skill_id = "ovos-skill-opds-books.test"
    s._bus = bus
    s._settings = {"catalogs": catalogs}
    s.file_system = FakeFileSystem(tmp_path / "skill")
    s.add_event = lambda topic, handler, *a, **k: bus.on(topic, handler)
    s.schedule_repeating_event = MagicMock()
    monkeypatch.setattr(Skill, "lang", "en-us", raising=False)
    monkeypatch.setattr(Skill, "native_langs", list(langs), raising=False)
    monkeypatch.setattr(Skill, "settings", property(lambda self: self._settings), raising=False)
    # the real refresh, on the test's own thread
    monkeypatch.setattr(Skill, "refresh", lambda self, force=False, background=False:
                        REFRESH(self, force=force, background=False))
    s._get = lambda url, limit=None: web(url)
    s.initialize()
    s.robots = opds.Robots(lambda url: "", "test")  # no robots.txt
    s.refresh(force=True)
    return s, bus


REFRESH = Skill.refresh


@pytest.fixture
def web():
    return FakeWeb(opds1(), standard_ebooks(), book_files("wuthering", "pride", "dracula", "aelling"),
                   {"https://se.example.com/ebooks/moonstone/downloads/moonstone.epub?source=feed":
                        (samples.epub([["The Moonstone begins."]]), "application/epub+zip")})


@pytest.fixture
def skill(tmp_path, monkeypatch, web):
    catalogs = f"{CLASSICS}\n{SE} | Standard Ebooks"
    return make_skill(tmp_path, monkeypatch, catalogs, web)


def search(bus, **data):
    seen = Recorder(bus, skill_module.COMMON_READING_SEARCH_RESPONSE)
    bus.emit(Message(skill_module.COMMON_READING_SEARCH, dict({"lang": "en-US"}, **data)))
    return [m.data for m in seen.of(skill_module.COMMON_READING_SEARCH_RESPONSE)]


def fetch(s, bus, content_id):
    seen = Recorder(bus, skill_module.COMMON_READING_FETCH_CONTENT_RESPONSE)
    bus.emit(Message(f"{skill_module.COMMON_READING_FETCH_CONTENT}.{s.skill_id}", {"content_id": content_id}))
    [reply] = seen.of(skill_module.COMMON_READING_FETCH_CONTENT_RESPONSE)
    return reply.data["paragraphs"]


def test_a_title_is_found_downloaded_and_read(skill, web):
    s, bus = skill
    [found] = search(bus, phrase="wuthering heights", content_type="book")
    assert (found["title"], found["author"], found["source"]) == \
        ("Wuthering Heights", "Emily Brontë", "Example Classics")
    assert found["image"] == "https://books.example.com/c/wuthering.jpg"
    assert fetch(s, bus, found["content_id"]) == ["Chapter 1", "wuthering chapter one.", "The end."]
    downloads = [u for u in web.fetched if u.endswith("wuthering.epub")]
    assert len(downloads) == 1
    fetch(s, bus, found["content_id"])  # kept: not downloaded again
    assert len([u for u in web.fetched if u.endswith("wuthering.epub")]) == 1


def test_nothing_is_downloaded_until_a_book_is_asked_for(skill, web):
    assert not [u for u in web.fetched if u.endswith(".epub") or "?source=feed" in u]


def test_a_book_in_another_language_is_not_offered(skill):
    _, bus = skill
    assert search(bus, phrase="pride and prejudice", lang="da-DK") == []
    [found] = search(bus, phrase="den grimme ælling", lang="da-DK")
    assert found["title"] == "Den grimme ælling"
    assert search(bus, phrase="den grimme ælling", lang="en-US") == [] or \
        search(bus, phrase="den grimme ælling", lang="en-US")[0]["title"] != "Den grimme ælling"


def test_a_catalog_without_languages_counts_as_english_unless_set(tmp_path, monkeypatch, web):
    s, bus = make_skill(tmp_path, monkeypatch, f"{SE} | Standard Ebooks", web)
    assert search(bus, phrase="confessions of zeno")[0]["title"] == "Confessions of Zeno"
    assert search(bus, phrase="confessions of zeno", lang="da-DK") == []
    s2, bus2 = make_skill(tmp_path / "b", monkeypatch, f"{SE} | Standard Ebooks | | | da", web)
    assert search(bus2, phrase="confessions of zeno", lang="da-DK")


def test_the_catalog_name_given_in_the_settings_is_the_source(skill):
    _, bus = skill
    [found] = search(bus, phrase="confessions of zeno")
    assert found["source"] == "Standard Ebooks"


def test_a_book_from_a_named_catalog(skill):
    _, bus = skill
    for _ in range(10):
        [found] = search(bus, collection_hint="standard ebooks")
        assert found["title"] == "Confessions of Zeno" and found["confidence"] == 1.0
    [any_book] = search(bus, content_type="book")
    assert any_book["confidence"] == skill_module.NO_TITLE_CONFIDENCE


def test_not_ours(skill):
    _, bus = skill
    assert search(bus, phrase="wuthering heights", content_type="story") == []
    assert search(bus, phrase="wuthering heights", collection_hint="brothers grimm") == []
    assert search(bus, phrase="xyzzy plugh quux") == []


def test_a_title_not_listed_is_searched_for_in_the_catalog(skill, web):
    s, bus = skill
    [found] = search(bus, phrase="the moonstone")
    assert (found["title"], found["source"]) == ("The Moonstone", "Standard Ebooks")
    assert fetch(s, bus, found["content_id"]) == ["Chapter 1", "The Moonstone begins."]


def test_a_slow_search_does_not_hold_up_the_answer(skill, monkeypatch):
    s, bus = skill
    real = s._get

    def slow(url, limit=None):
        if "query=" in url:
            time.sleep(5)
        return real(url)
    s._get = slow
    t = time.monotonic()
    search(bus, phrase="the moonstone")
    assert time.monotonic() - t < skill_module.LIVE_SEARCH_TIMEOUT + 0.5


def test_a_catalog_that_asks_to_wait_keeps_its_books(skill, web):
    s, bus = skill

    def busy(url, limit=None):
        raise opds.Unavailable("come back later", time.time() + 3600)
    s._get = busy
    s.refresh(force=True)
    assert search(bus, phrase="wuthering heights")
    assert s.state[CLASSICS]["retry_after"] > time.time()


def test_vocabulary(skill):
    s, bus = skill
    seen = Recorder(bus, skill_module.COMMON_READING_VOCABULARY)
    bus.emit(Message(skill_module.COMMON_READING_VOCABULARY_GET, {"langs": ["da", "en"]}))
    vocab = {m.data["lang"]: m.data for m in seen.of(skill_module.COMMON_READING_VOCABULARY)}
    assert "bogen" in vocab["da"]["content_types"]["book"]
    assert "Standard Ebooks" in vocab["en"]["collections"] and "my books" in vocab["en"]["collections"]
    assert "Wuthering Heights" in vocab["en"]["titles"] and "Dracula" not in vocab["en"]["titles"]
    assert vocab["da"]["titles"] == ["Den grimme ælling"]


def test_login_goes_only_to_its_own_site(tmp_path, monkeypatch, web):
    s, _ = make_skill(tmp_path, monkeypatch, [
        {"url": SE, "name": "Standard Ebooks", "username": "me@example.com", "password": ""},
        {"url": CLASSICS}], web)
    assert s._auth_for("https://se.example.com/feeds/opds") == ("me@example.com", "")
    assert s._auth_for("https://books.example.com/d/x.epub") is None


def test_the_default_catalog(tmp_path, monkeypatch, web):
    s, _ = make_skill(tmp_path, monkeypatch, None, web)
    assert [c["url"] for c in s.catalogs()] == ["https://standardebooks.org/feeds/atom/new-releases"]


def test_settings_text(skill):
    assert skill_module.parse_catalogs("https://a.example/opds | My Lib | me | pw | da\nnot a url\n") == \
        [{"url": "https://a.example/opds", "name": "My Lib", "username": "me", "password": "pw", "language": "da"}]


# --- the catalogs, for a control-panel page -------------------------------------------------

def ask(bus, topic, data=None):
    seen = Recorder(bus, f"{topic}.response")
    bus.emit(Message(topic, data or {}))
    [reply] = seen.of(f"{topic}.response")
    return reply.data


def test_the_catalogs_are_listed_without_passwords(tmp_path, monkeypatch, web):
    s, bus = make_skill(tmp_path, monkeypatch, f"{CLASSICS} | Classics | me | secret | da", web)
    data = ask(bus, skill_module.CATALOGS_LIST)
    [c] = data["catalogs"]
    assert c["url"] == CLASSICS and c["name"] == "Classics" and c["language"] == "da"
    assert c["login"] is True and c["username"] == "me" and c["books"] > 0
    assert "secret" not in str(data) and "password" not in c


def test_setting_catalogs_saves_them_and_keeps_a_password_not_sent(tmp_path, monkeypatch, web):
    s, bus = make_skill(tmp_path, monkeypatch, f"{CLASSICS} | Classics | me | secret", web)
    data = ask(bus, skill_module.CATALOGS_SET, {"catalogs": [
        {"url": CLASSICS, "name": "My classics", "username": "me", "password": None},
        {"url": SE, "name": "Standard Ebooks", "language": "en"},
        {"url": "not a url"},
        {"url": "https://x.example.com/opds", "name": "bad | name"}]})
    assert s.settings["catalogs"] == (f"{CLASSICS} | My classics | me | secret\n"
                                      f"{SE} | Standard Ebooks | | | en")
    assert [c["name"] for c in data["catalogs"]] == ["My classics", "Standard Ebooks"]
    assert {c["url"]: c["books"] > 0 for c in data["catalogs"]} == {CLASSICS: True, SE: True}


def test_a_catalog_that_cannot_be_read_says_why_and_keeps_its_books(skill, web):
    s, bus = skill
    before = ask(bus, skill_module.CATALOGS_LIST)["catalogs"][0]["books"]
    web.pages.pop(CLASSICS, None) if hasattr(web, "pages") else None
    s._get = lambda url, limit=None: (_ for _ in ()).throw(OSError("down for maintenance"))
    data = ask(bus, skill_module.CATALOGS_REFRESH)
    first = data["catalogs"][0]
    assert first["books"] == before and "down for maintenance" in first["error"]
