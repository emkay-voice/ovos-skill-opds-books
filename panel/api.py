"""The books page's API: thin relays to the skill over the message bus."""
import re
from typing import Any, Optional

from fastapi import HTTPException
from pydantic import BaseModel, Field

LIST = "ovos.opds.catalogs.list"
SET = "ovos.opds.catalogs.set"
REFRESH = "ovos.opds.catalogs.refresh"
TIMEOUT = 5.0


class Catalog(BaseModel):
    url: str = Field(max_length=2000)
    name: str = Field("", max_length=200)
    username: str = Field("", max_length=200)
    #: None keeps the password the catalog has; the page never sees it
    password: Optional[str] = Field(None, max_length=500)
    language: str = Field("", max_length=20)


class CatalogsBody(BaseModel):
    catalogs: list[Catalog] = Field(max_length=50)
    refresh_hours: Optional[float] = Field(None, ge=1, le=24 * 30)


def ask(r, msg_type: str, data: dict | None = None, timeout: float = TIMEOUT) -> dict[str, Any]:
    """Send a message to the skill and give back its answer."""
    from ovos_bus_client.message import Message
    bus = r.need_bus()
    message = Message(msg_type, data or {})
    try:
        from ovos_webui import buswait
        reply = buswait.wait_for_response(bus, message, timeout=timeout)
    except ImportError:  # an older panel: the bus client's own wait
        reply = bus.wait_for_response(message, timeout=timeout)
    if reply is None:
        raise HTTPException(504, "the books skill did not answer; is it running?")
    return reply.data


def clean(body: CatalogsBody) -> dict[str, Any]:
    """The catalogs as the skill takes them, or 400 for one it cannot keep."""
    out, seen = [], set()
    for c in body.catalogs:
        c = c.model_copy(update={k: v.strip() for k, v in c.model_dump().items() if isinstance(v, str)})
        if not re.match(r"^https?://\S+$", c.url):
            raise HTTPException(400, f"a catalog's address starts with http:// or https://: {c.url}")
        if any("|" in v or "\n" in v for v in c.model_dump().values() if isinstance(v, str)):
            raise HTTPException(400, "a catalog's fields cannot contain | or a line break")
        if c.url in seen:
            continue
        seen.add(c.url)
        entry = c.model_dump(exclude_none=True)
        if not c.username:
            entry["password"] = ""  # no login: forget a password it had
        out.append(entry)
    data: dict[str, Any] = {"catalogs": out}
    if body.refresh_hours is not None:
        data["refresh_hours"] = body.refresh_hours
    return data


def routes(r) -> None:
    @r.api.get("/books/catalogs")
    def api_books_catalogs() -> dict[str, Any]:
        return ask(r, LIST)

    @r.api.post("/books/catalogs/refresh")
    def api_books_catalogs_refresh() -> dict[str, Any]:
        return ask(r, REFRESH)

    # A catalog makes the device fetch from the internet, and may carry a
    # login, so changing them needs the access token.
    @r.privileged.post("/books/catalogs")
    def api_books_catalogs_set(body: CatalogsBody) -> dict[str, Any]:
        return ask(r, SET, clean(body))
