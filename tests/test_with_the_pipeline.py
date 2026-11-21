"""The real reading pipeline on the same bus: does it hand "read me the book
..." to this skill, and leave "book a table" and the like alone?"""
import pytest
from ovos_bus_client.message import Message

from test_skill import CLASSICS, SE, book_files, make_skill
from catalogs import FakeWeb, opds1, standard_ebooks

pipeline_module = pytest.importorskip("ovos_common_reading_pipeline_plugin")


@pytest.fixture
def pipeline(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path / "cfg"))
    web = FakeWeb(opds1(), standard_ebooks(), book_files("wuthering"))
    skill, bus = make_skill(tmp_path, monkeypatch, f"{CLASSICS}\n{SE} | Standard Ebooks", web)
    p = pipeline_module.CommonReadingPipeline(bus=bus)
    skill._announce_vocabulary()
    yield p
    p.stop()


def claimed(p, utterance, lang):
    message = Message("recognizer_loop:utterance", {"utterances": [utterance], "lang": lang},
                      {"session": {"session_id": "default", "lang": lang}})
    return p.match_high([utterance], lang, message) or p.match_low([utterance], lang, message)


@pytest.mark.parametrize("utterance, lang", [
    ("read me the book wuthering heights", "en-us"),
    ("read me a book", "en-us"),
    ("read me a book from standard ebooks", "en-us"),
    ("tell me wuthering heights", "en-us"),
    ("læs bogen den grimme ælling", "da-dk"),
    ("læs en bog", "da-dk"),
])
def test_claimed(pipeline, utterance, lang):
    assert claimed(pipeline, utterance, lang) is not None, utterance


@pytest.mark.parametrize("utterance, lang", [
    ("book a table for two", "en-us"),
    ("book me a flight to london", "en-us"),
    ("what is the weather", "en-us"),
    ("bestil et bord", "da-dk"),
])
def test_left_alone(pipeline, utterance, lang):
    assert claimed(pipeline, utterance, lang) is None, utterance
