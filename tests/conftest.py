"""Shared fixtures: a fresh SQLite show DB and a fresh hub per test."""

import pytest
from sqlmodel import SQLModel

from showanimator.models import ensure_tables
from showanimator.runtime import runtime
from showanimator.state import StageHub
from showrunner.database import ShowDatabase
from showrunner.models import Cue, CueList, Show


@pytest.fixture
def db(tmp_path, monkeypatch):
    database = ShowDatabase(str(tmp_path / "test.db"))
    SQLModel.metadata.create_all(database.engine)
    ensure_tables(database.engine)
    monkeypatch.setattr(runtime, "db", database)
    monkeypatch.setattr(runtime, "hub", StageHub())
    return database


@pytest.fixture
def show(db):
    """(show_id, [cue1_id, cue2_id]) for a show with two cues."""
    with db.session() as s:
        sh = Show(name="Demo")
        s.add(sh)
        s.commit()
        s.refresh(sh)
        cl = CueList(show_id=sh.id, name="Main")
        s.add(cl)
        s.commit()
        s.refresh(cl)
        cues = [Cue(cue_list_id=cl.id, number=str(i), name=f"c{i}") for i in (1, 2)]
        s.add_all(cues)
        s.commit()
        return sh.id, [c.id for c in cues]
