"""ShowAnimator: live browser animations on stages, controlled from ShowRunner."""

import showrunner
from fastapi.staticfiles import StaticFiles
from loguru import logger

from showrunner.plugin import ShowRunnerPlugin

from . import cues
from .engines import AnimatorSpec
from .models import ensure_tables
from .routes import STATIC_DIR, router
from .ui import register as register_ui
from .runtime import runtime


class ShowAnimatorPlugin(ShowRunnerPlugin):
    """Stage pages, the live state hub, and the cue/command bridge into ShowRunner."""

    @showrunner.hookimpl
    def showrunner_register(self):
        return {
            "name": "ShowAnimator",
            "description": "Live browser animations on stages, driven by cues",
            "version": "0.1.0",
        }

    @showrunner.hookimpl
    def showrunner_startup(self, app):
        super().showrunner_startup(app)
        db = getattr(app, "db", None)
        if db is None:
            logger.error("ShowAnimator disabled: ShowDB is not loaded (no app.db)")
            return
        runtime.db = db
        runtime.pm = app.pm
        app.pm.add_hookspecs(AnimatorSpec)
        ensure_tables(db.engine)
        app.api.mount("/animator/static", StaticFiles(directory=STATIC_DIR), name="animator-static")
        register_ui()

    @showrunner.hookimpl
    def showrunner_shutdown(self, app):
        super().showrunner_shutdown(app)

    @showrunner.hookimpl
    def showrunner_get_routes(self):
        return router

    @showrunner.hookimpl
    def showrunner_get_nav(self):
        return {"label": "Animator", "path": "/animator", "icon": "movie_filter", "order": 60}

    @showrunner.hookimpl
    def showrunner_command(self, command_name, data):
        cues.handle_command(command_name, data)

    @showrunner.hookimpl
    def showrunner_cue_changed(self, action, cue, before):
        cues.on_cue_changed(action, cue, before)


plugin = ShowAnimatorPlugin()
