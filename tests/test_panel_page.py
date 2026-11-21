"""The page this skill adds to ovos-control-panel: its description, its
strings, and its routes talking to the skill over a bus."""
import json
import re
from pathlib import Path

import pytest

from conftest import skill_module  # noqa: F401 - loads the package
from test_skill import CLASSICS, SE, make_skill, web  # noqa: F401 - web is a fixture

from ovos_skill_opds_books import panel

ROOT = Path(__file__).resolve().parents[1]
PANEL = ROOT / "panel"
LANGS = {p.name.split("-")[0] for p in (ROOT / "locale").iterdir() if p.is_dir()}


def test_the_page_description_names_files_that_exist():
    page = panel.PAGE
    assert page["api_version"] == 1 and page["id"] == "books"
    for key in ("html", "icon"):
        assert (PANEL / page[key]).is_file(), key
    assert callable(page["routes"])
    assert page["group"] == panel.LIBRARY["id"] and panel.LIBRARY in page["groups"]


def test_the_page_speaks_every_language_the_skill_does():
    files = {p.stem: json.loads(p.read_text(encoding="utf-8")) for p in (PANEL / "i18n").glob("*.json")}
    assert LANGS <= set(files)
    keys = set(files["en"])
    for lang, table in files.items():
        assert set(table) == keys, lang
        assert all(text.strip() for text in table.values()), lang
    html = (PANEL / "page.html").read_text(encoding="utf-8")
    used = (set(re.findall(r'data-i18n="([^"]+)"', html)) | set(re.findall(r'\bt\("([^"]+)"', html))
            | set(re.findall(r'field\("[^"]*", "([^"]+)"', html)))
    assert used <= keys, "a string the page uses has no translation"
    assert keys - used <= {"nav.group.library", "books.title"}, "a translation nothing uses"


# ── the routes, against the skill itself on a bus ────────────────────────────
pytest.importorskip("fastapi")
pytest.importorskip("httpx")


@pytest.fixture
def client(tmp_path, monkeypatch, web):  # noqa: F811 - the fixture
    from fastapi import APIRouter, FastAPI
    from fastapi.testclient import TestClient

    skill, bus = make_skill(tmp_path, monkeypatch, f"{CLASSICS} | Classics | me | secret | da", web)

    class R:
        api = APIRouter(prefix="/api")
        privileged = APIRouter(prefix="/api")
        config = None

        @staticmethod
        def need_bus():
            return bus

    panel.routes(R)
    app = FastAPI()
    app.include_router(R.api)
    app.include_router(R.privileged)
    with TestClient(app) as c:
        yield c, skill


def test_the_page_lists_the_catalogs_without_their_passwords(client):
    c, _ = client
    r = c.get("/api/books/catalogs")
    [cat] = r.json()["catalogs"]
    assert cat["name"] == "Classics" and cat["login"] and cat["books"] > 0
    assert "secret" not in r.text


def test_a_catalog_is_added_and_the_password_kept(client):
    c, skill = client
    r = c.post("/api/books/catalogs", json={"catalogs": [
        {"url": CLASSICS, "name": "Classics", "username": "me", "language": "da"},
        {"url": f" {SE} ", "name": "Standard Ebooks"}], "refresh_hours": 12})
    assert r.status_code == 200, r.text
    assert skill.settings["catalogs"] == f"{CLASSICS} | Classics | me | secret | da\n{SE} | Standard Ebooks"
    assert skill.settings["refresh_hours"] == 12
    assert [x["name"] for x in r.json()["catalogs"]] == ["Classics", "Standard Ebooks"]


def test_a_login_taken_away_takes_its_password_with_it(client):
    c, skill = client
    c.post("/api/books/catalogs", json={"catalogs": [{"url": CLASSICS, "name": "Classics"}]})
    assert "secret" not in skill.settings["catalogs"]


def test_a_catalog_is_removed(client):
    c, skill = client
    assert c.post("/api/books/catalogs", json={"catalogs": []}).json()["catalogs"] == []
    assert skill.settings["catalogs"] == ""


@pytest.mark.parametrize("catalog", [{"url": "file:///etc/passwd"}, {"url": CLASSICS, "name": "a | b"}])
def test_a_catalog_it_cannot_keep_is_refused(client, catalog):
    c, skill = client
    before = skill.settings["catalogs"]
    assert c.post("/api/books/catalogs", json={"catalogs": [catalog]}).status_code == 400
    assert skill.settings["catalogs"] == before


def test_the_catalogs_are_read_again_on_request(client):
    c, _ = client
    assert c.post("/api/books/catalogs/refresh").json()["catalogs"][0]["books"] > 0
