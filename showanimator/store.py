"""DB access for stages and animations. Functions take a ShowDatabase (``app.db``)."""

from __future__ import annotations

import json
import re
import secrets

from sqlmodel import select

from showrunner.models import Cue, CueList

from .engines import BLENDS
from .models import AnimatorAnimation, AnimatorStage

_SLUG = re.compile(r"^[a-z0-9][a-z0-9-]{0,47}$")


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")[:48].strip("-")
    return slug or "stage"


# -- stages -----------------------------------------------------------------


def list_stages(db, show_id: int) -> list[AnimatorStage]:
    with db.session() as s:
        return list(s.exec(select(AnimatorStage).where(AnimatorStage.show_id == show_id)
                           .order_by(AnimatorStage.name)).all())


def get_stage(db, stage_id: int) -> AnimatorStage | None:
    with db.session() as s:
        return s.get(AnimatorStage, stage_id)


def get_stage_by_slug(db, slug: str) -> AnimatorStage | None:
    with db.session() as s:
        return s.exec(select(AnimatorStage).where(AnimatorStage.slug == slug)).first()


def create_stage(db, show_id: int, name: str, slug: str | None = None,
                 engine: str = "canvas2d", private: bool = False) -> AnimatorStage:
    """Create a stage. Slugs are unique across all shows; a missing slug is derived from the name."""
    with db.session() as s:
        taken = set(s.exec(select(AnimatorStage.slug)).all())
        if slug is not None:
            if not _SLUG.match(slug):
                raise ValueError(f"invalid slug {slug!r}: use a-z, 0-9 and '-'")
            if slug in taken:
                raise ValueError(f"slug {slug!r} is already used by another stage")
        else:
            base, n = slugify(name), 1
            slug = base
            while slug in taken:
                n += 1
                slug = f"{base}-{n}"
        stage = AnimatorStage(show_id=show_id, name=name.strip() or slug, slug=slug,
                              engine=engine, private=private,
                              token=secrets.token_urlsafe(16) if private else None)
        s.add(stage)
        s.commit()
        s.refresh(stage)
        return stage


def update_stage(db, stage_id: int, name: str | None = None,
                 private: bool | None = None) -> AnimatorStage:
    with db.session() as s:
        stage = s.get(AnimatorStage, stage_id)
        if stage is None:
            raise KeyError(stage_id)
        if name is not None:
            stage.name = name.strip() or stage.name
        if private is not None and private != stage.private:
            stage.private = private
            # A new token each time privacy is turned on, so an old link stops working.
            stage.token = secrets.token_urlsafe(16) if private else None
        s.add(stage)
        s.commit()
        s.refresh(stage)
        return stage


def delete_stage(db, stage_id: int) -> None:
    with db.session() as s:
        for row in s.exec(select(AnimatorAnimation).where(
                AnimatorAnimation.stage_id == stage_id)).all():
            s.delete(row)
        stage = s.get(AnimatorStage, stage_id)
        if stage is not None:
            s.delete(stage)
        s.commit()


# -- animations -------------------------------------------------------------


def list_animations(db, cue_id: int) -> list[AnimatorAnimation]:
    with db.session() as s:
        return list(s.exec(select(AnimatorAnimation).where(
            AnimatorAnimation.cue_id == cue_id).order_by(AnimatorAnimation.sequence,
                                                         AnimatorAnimation.id)).all())


def animations_on_layer(db, show_id: int, layer: str) -> list[AnimatorAnimation]:
    with db.session() as s:
        return list(s.exec(select(AnimatorAnimation).join(Cue, AnimatorAnimation.cue_id == Cue.id)
                           .join(CueList, Cue.cue_list_id == CueList.id)
                           .where(CueList.show_id == show_id, Cue.layer == layer)).all())


def layers_with_animations(db, show_id: int) -> list[str]:
    with db.session() as s:
        names = s.exec(select(Cue.layer).join(CueList, Cue.cue_list_id == CueList.id)
                       .join(AnimatorAnimation, AnimatorAnimation.cue_id == Cue.id)
                       .where(CueList.show_id == show_id).distinct()).all()
    return sorted(n for n in names if n)


def add_animation(db, cue_id: int, *, action: str = "show", scene: str | None = None,
                  stage_id: int | None = None, slot: str = "main",
                  params: dict | None = None, blend: str = "normal",
                  opacity: float = 1.0, fade: float = 0.0,
                  animation_id: int | None = None) -> AnimatorAnimation:
    """Add one step to a cue, or replace step ``animation_id`` in place (keeps its order).

    Validates action, blend and the scene against the stage's engine before writing.
    """
    from .engines import collect  # local: avoid import cycle at module load

    if action not in ("show", "hide"):
        raise ValueError(f"action must be 'show' or 'hide', not {action!r}")
    if blend not in BLENDS:
        raise ValueError(f"blend must be one of {BLENDS}, not {blend!r}")
    if action == "show" and not scene:
        raise ValueError("a 'show' step needs a scene")
    if not slot or len(slot) > 32:
        raise ValueError("slot must be 1-32 characters")
    with db.session() as s:
        cue = s.get(Cue, cue_id)
        if cue is None:
            raise KeyError(f"cue {cue_id} not found")
        stage = s.get(AnimatorStage, stage_id) if stage_id is not None else None
        if stage_id is not None and stage is None:
            raise KeyError(f"stage {stage_id} not found")
        if action == "show":
            engines = collect()
            engine_ids = [stage.engine] if stage else list(engines)
            if not any(scene in engines[e].scenes for e in engine_ids if e in engines):
                raise ValueError(f"unknown scene {scene!r}")
        values = dict(
            show_id=cue.cue_list.show_id if cue.cue_list else None,
            stage_id=stage_id, slot=slot, action=action, scene=scene,
            params_json=json.dumps(params or {}), blend=blend,
            opacity=min(1.0, max(0.0, opacity)), fade=max(0.0, fade),
        )
        if animation_id is None:
            row = AnimatorAnimation(cue_id=cue_id, sequence=len(list_animations_in(s, cue_id)), **values)
        else:
            row = s.get(AnimatorAnimation, animation_id)
            if row is None or row.cue_id != cue_id:
                raise KeyError(f"step {animation_id} not found on cue {cue_id}")
            for key, value in values.items():
                setattr(row, key, value)
        s.add(row)
        s.commit()
        s.refresh(row)
        return row


def list_animations_in(s, cue_id: int) -> list[AnimatorAnimation]:
    return list(s.exec(select(AnimatorAnimation).where(AnimatorAnimation.cue_id == cue_id)).all())


def delete_animation(db, animation_id: int) -> None:
    with db.session() as s:
        row = s.get(AnimatorAnimation, animation_id)
        if row is not None:
            s.delete(row)
            s.commit()


def delete_cue_animations(db, cue_id: int) -> int:
    with db.session() as s:
        rows = list_animations_in(s, cue_id)
        for row in rows:
            s.delete(row)
        s.commit()
        return len(rows)
