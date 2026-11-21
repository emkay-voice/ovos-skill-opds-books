"""The books page in ovos-control-panel.

The control panel finds this page through the ``opm.control_panel.page``
entry point (see pyproject.toml and the panel's docs/pages.md). It shows the
e-book catalogs the skill reads from, how many books each has and whether it
could be read, and lets you add, change and remove catalogs. Nothing here is
loaded by the skill itself, so the skill needs no web packages; the panel
brings those.
"""


def routes(r):
    # Imported here, so reading PAGE (the panel's registry, this skill's
    # tests) needs no web framework; only the panel calls this.
    from ovos_skill_opds_books.panel.api import routes as add
    add(r)


#: the group the reading skills share; any of them may bring it, the first wins
READING = {"id": "reading", "title": {"key": "reading.group", "label": "Reading"},
           "order": 5, "level": "everyday"}

PAGE = {
    "api_version": 1,
    "id": "books",
    "path": "/books",
    "title": {"key": "books.title", "label": "Books"},
    "group": "reading",
    "groups": [READING],
    "order": 20,
    "needs": ["ovos-skill-opds-books"],
    "html": "page.html",
    "icon": "icon.svg",
    "i18n": "i18n",
    "routes": routes,
}
