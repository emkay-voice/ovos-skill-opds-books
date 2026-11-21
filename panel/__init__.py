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


#: the panel's Library group: what the device reads and plays for you. Newer
#: panels have it themselves; this brings it to older ones, and its name to
#: the languages the panel itself has no strings for
LIBRARY = {"id": "library", "title": {"key": "nav.group.library", "label": "Library"},
           "order": 5, "level": "everyday"}

PAGE = {
    "api_version": 1,
    "id": "books",
    "path": "/books",
    "title": {"key": "books.title", "label": "Books"},
    "group": "library",
    "groups": [LIBRARY],
    "order": 20,
    "needs": ["ovos-skill-opds-books"],
    "html": "page.html",
    "icon": "icon.svg",
    "i18n": "i18n",
    "routes": routes,
}
