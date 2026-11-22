"""The page this skill has in ovos-control-panel, described in
controlpanel.json: the file, its strings in every language, and the skill's
answers to the page over the bus."""
import json
import re
from pathlib import Path

import pytest
from ovos_bus_client.message import Message

from conftest import skill_module  # noqa: F401 - loads the package
from test_skill import CLASSICS, SE, make_skill, web  # noqa: F401 - web is a fixture

ROOT = Path(__file__).resolve().parents[1]
TEXT = (ROOT / "controlpanel.json").read_text(encoding="utf-8")
PAGE = json.loads(TEXT)


def test_the_page_names_files_that_exist_and_its_own_messages():
    assert PAGE["controlpanel"] == 1 and PAGE["id"] == "books" and PAGE["group"] == "library"
    assert (ROOT / PAGE["icon"]).is_file()
    sent = re.findall(r'"(?:query|send)": "([^"]+)"', TEXT)
    assert sent and all(m.startswith(PAGE["bus"]) for m in sent)


def test_the_page_speaks_every_language_the_skill_does():
    files = {p.parent.name: json.loads(p.read_text(encoding="utf-8"))
             for p in (ROOT / "locale").glob("*/controlpanel.json")}
    assert set(files) == {p.name for p in (ROOT / "locale").iterdir() if p.is_dir()}
    keys = set(files["en-us"])
    for lang, table in files.items():
        assert set(table) == keys, lang
        assert all(text.strip() for text in table.values()), lang
        assert "{books}" in table["books.state.read"] and "{error}" in table["books.state.error"], lang
    used = set(re.findall(r'"((?:books|nav)\.[\w.]+)"', TEXT))
    states = {f"books.state.{s}" for s in ("read", "error", "new")}
    errors = {f"books.err.{e}" for e in ("url", "bar", "hours")}
    assert used | states | errors == keys, "every string is used, and every one used is there"


def test_the_panel_reads_it():
    described = pytest.importorskip("ovos_webui.described")
    page, refs = described.check(PAGE, "ovos-skill-opds-books")
    assert [b["type"] for b in page["blocks"]] == ["text", "list", "actions", "form", "form", "text"]
    assert refs["b1.a0"]["confirm"], "a remove asks first"
    assert not refs["b2.a0"]["privileged"], "reading them again changes nothing"


@pytest.fixture
def bus_skill(tmp_path, monkeypatch, web):  # noqa: F811 - the fixture
    return make_skill(tmp_path, monkeypatch, f"{CLASSICS} | Classics | me | secret | da", web)


def ask(bus, msg_type, **data):
    return bus.wait_for_response(Message(msg_type, data), timeout=3).data


def test_the_page_lists_the_catalogs_without_their_passwords(bus_skill):
    _, bus = bus_skill
    data = ask(bus, "ovos.opds.catalogs.list")
    [cat] = data["catalogs"]
    assert cat["shown"] == "Classics" and cat["login"] and cat["books"] > 0 and cat["state"] == "read"
    assert "secret" not in json.dumps(data)


def test_a_catalog_is_added_and_changed_and_the_password_kept(bus_skill):
    skill, bus = bus_skill
    ask(bus, "ovos.opds.catalogs.add", url=f" {SE} ", name="Standard Ebooks")
    assert skill.settings["catalogs"] == f"{CLASSICS} | Classics | me | secret | da\n{SE} | Standard Ebooks"
    got = ask(bus, "ovos.opds.catalogs.add", url=CLASSICS, name="Klassikere", username="me", language="da")
    assert skill.settings["catalogs"] == f"{SE} | Standard Ebooks\n{CLASSICS} | Klassikere | me | secret | da"
    assert [c["shown"] for c in got["catalogs"]] == ["Standard Ebooks", "Klassikere"]


def test_a_login_taken_away_takes_its_password_with_it(bus_skill):
    skill, bus = bus_skill
    ask(bus, "ovos.opds.catalogs.add", url=CLASSICS, name="Classics")
    assert "secret" not in skill.settings["catalogs"]


def test_a_catalog_is_removed(bus_skill):
    skill, bus = bus_skill
    assert ask(bus, "ovos.opds.catalogs.remove", url=CLASSICS)["catalogs"] == []
    assert skill.settings["catalogs"] == ""


@pytest.mark.parametrize("catalog, error", [({"url": "file:///etc/passwd"}, "books.err.url"),
                                            ({"url": CLASSICS, "name": "a | b"}, "books.err.bar")])
def test_a_catalog_it_cannot_keep_is_refused(bus_skill, catalog, error):
    skill, bus = bus_skill
    before = skill.settings["catalogs"]
    assert ask(bus, "ovos.opds.catalogs.add", **catalog) == {"error": error}
    assert skill.settings["catalogs"] == before


def test_how_often_they_are_read(bus_skill):
    skill, bus = bus_skill
    assert ask(bus, "ovos.opds.catalogs.every", refresh_hours=12)["refresh_hours"] == 12
    assert skill.settings["refresh_hours"] == 12 and "secret" in skill.settings["catalogs"]
    assert ask(bus, "ovos.opds.catalogs.every", refresh_hours="often") == {"error": "books.err.hours"}


def test_the_catalogs_are_read_again_on_request(bus_skill):
    _, bus = bus_skill
    assert ask(bus, "ovos.opds.catalogs.refresh")["catalogs"][0]["books"] > 0
