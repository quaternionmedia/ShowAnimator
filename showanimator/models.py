"""ShowAnimator tables. Owned by the plugin, created at startup (no core migration)."""

from __future__ import annotations

from sqlmodel import Field, SQLModel


class AnimatorStage(SQLModel, table=True):
    """A named output that renders animations in a browser."""

    __tablename__ = "animator_stages"

    id: int | None = Field(default=None, primary_key=True)
    show_id: int = Field(foreign_key="shows.id", index=True)
    name: str
    slug: str = Field(index=True, unique=True)  # global: links resolve without a show id
    engine: str = "canvas2d"
    private: bool = False
    token: str | None = None  # set when private; required in the link as ?k=


class AnimatorAnimation(SQLModel, table=True):
    """One step a cue applies to a stage slot (stage_id None = every stage).

    action 'show' sets the slot's scene/params/blend/opacity; 'hide' fades the slot out.
    fade is seconds (0 = instant). Fade-to-colour is a 'show' of the 'solid' scene on
    a second slot with fade > 0.
    """

    __tablename__ = "animator_animations"

    id: int | None = Field(default=None, primary_key=True)
    show_id: int = Field(foreign_key="shows.id", index=True)
    cue_id: int = Field(foreign_key="cues.id", index=True)
    stage_id: int | None = Field(default=None, foreign_key="animator_stages.id", index=True)
    slot: str = "main"
    action: str = "show"  # 'show' | 'hide'
    scene: str | None = None  # required for 'show'
    params_json: str = "{}"
    blend: str = "normal"  # normal | add | subtract | mask
    opacity: float = 1.0
    fade: float = 0.0
    sequence: int = 0


def ensure_tables(engine) -> None:
    """Create the plugin tables if missing. Safe to call on every startup."""
    tables = [AnimatorStage.__table__, AnimatorAnimation.__table__]
    SQLModel.metadata.create_all(engine, tables=tables, checkfirst=True)
