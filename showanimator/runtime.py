"""Process-wide state shared by routes, hooks and the control page.

Routers are built at import time (ShowRunner collects them in ``__init__``,
before startup), so handlers read ``runtime`` lazily instead of closing over it.
"""

from __future__ import annotations

from .engines import collect
from .state import StageHub


class Runtime:
    def __init__(self) -> None:
        self.db = None  # ShowDatabase, set in showrunner_startup (app.db)
        self.pm = None  # pluggy manager, set in showrunner_startup
        self.hub = StageHub()

    def engines(self):
        return collect(self.pm)


runtime = Runtime()
