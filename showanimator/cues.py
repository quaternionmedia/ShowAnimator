"""Stage control: apply scenes and params, fire cues, and handle ``animator.*`` commands.

Every path (cue fire, control page, stage debug panel, OSC/MIDI mapping) goes
through the functions here, so validation lives in one place.
"""

from __future__ import annotations

import json

from loguru import logger
from sqlmodel import select

from showrunner.models import Cue, CueList, Show

from . import store
from .runtime import runtime


def _scene(stage_id: int, scene_id: str):
    stage = store.get_stage(runtime.db, stage_id)
    if stage is None:
        raise KeyError(f"stage {stage_id} not found")
    engine = runtime.engines().get(stage.engine)
    scene = engine.scenes.get(scene_id) if engine else None
    if scene is None:
        raise KeyError(f"scene {scene_id!r} is not available on stage {stage.slug!r}")
    return scene


def apply_scene(stage_id: int, slot: str, scene_id: str, params: dict | None = None, *,
                blend: str = "normal", opacity: float = 1.0, fade: float = 0.0) -> dict:
    return runtime.hub.apply(stage_id, slot, _scene(stage_id, scene_id), params,
                             blend=blend, opacity=opacity, fade=fade)


def set_param(stage_id: int, slot: str, key: str, value) -> dict:
    snap = runtime.hub.set_param(stage_id, slot, key, value)
    if snap is None:
        raise KeyError(f"no active slot {slot!r} on stage {stage_id}")
    return snap


def hide_slot(stage_id: int, slot: str, fade: float = 0.0) -> dict | None:
    return runtime.hub.hide(stage_id, slot, fade=fade)


def fire_cue(cue_id: int) -> int:
    """Apply every animation step of a cue. Returns the number of stage slots changed.

    Steps for a missing stage or a scene that stage's engine lacks are logged and skipped,
    so one bad row does not stop the rest of the cue.
    """
    rows = store.list_animations(runtime.db, cue_id)
    changed = 0
    for row in rows:
        if row.stage_id is not None:
            targets = [row.stage_id]
        else:
            targets = [s.id for s in store.list_stages(runtime.db, row.show_id)]
        for stage_id in targets:
            try:
                if row.action == "hide":
                    hide_slot(stage_id, row.slot, fade=row.fade)
                else:
                    apply_scene(stage_id, row.slot, row.scene,
                                json.loads(row.params_json or "{}"),
                                blend=row.blend, opacity=row.opacity, fade=row.fade)
                changed += 1
            except (KeyError, ValueError) as exc:
                logger.warning("ShowAnimator cue {} step {}: {}", cue_id, row.id, exc)
    return changed


def find_cue(show_id: int, number: str, point: int = 0) -> Cue | None:
    with runtime.db.session() as s:
        return s.exec(
            select(Cue).join(CueList).where(
                CueList.show_id == show_id, Cue.number == number, Cue.point == point)
        ).first()


def first_show_id() -> int | None:
    with runtime.db.session() as s:
        return s.exec(select(Show.id).order_by(Show.name)).first()


def _stage_ids(stage_ref, show_id: int) -> list[int]:
    """A stage given as id or slug, or all stages of the show when omitted."""
    if stage_ref in (None, "", "all"):
        return [s.id for s in store.list_stages(runtime.db, show_id)]
    stage = (store.get_stage(runtime.db, int(stage_ref)) if str(stage_ref).isdigit()
             else store.get_stage_by_slug(runtime.db, str(stage_ref)))
    if stage is None:
        raise KeyError(f"stage {stage_ref!r} not found")
    return [stage.id]


def on_cue_changed(action: str, cue: dict | None, before) -> None:
    """showrunner_cue_changed: a deleted cue takes its animation steps with it."""
    if action == "delete" and cue and cue.get("id") is not None:
        store.delete_cue_animations(runtime.db, cue["id"])


def handle_command(command_name: str, data: dict | None) -> None:
    """showrunner_command: ``animator.cue``, ``animator.scene``, ``animator.param``, ``animator.hide``.

    Stage defaults to all stages of the show. Cues are found by ``cue_id`` or ``number``
    (+ optional ``point``) in ``show_id`` (default: the first show by name).
    """
    if not command_name.startswith("animator.") or runtime.db is None:
        return
    data = data or {}
    show_id = data.get("show_id") or first_show_id()
    if show_id is None:
        logger.warning("ShowAnimator command {} ignored: no show", command_name)
        return
    try:
        if command_name == "animator.cue":
            cue_id = data.get("cue_id")
            if cue_id is None:
                cue = find_cue(show_id, str(data["number"]), int(data.get("point", 0)))
                if cue is None:
                    raise KeyError(f"no cue {data['number']!r} in show {show_id}")
                cue_id = cue.id
            fire_cue(int(cue_id))
        elif command_name == "animator.scene":
            for sid in _stage_ids(data.get("stage"), show_id):
                apply_scene(sid, str(data.get("slot", "main")), str(data["scene"]),
                            data.get("params") or {}, blend=str(data.get("blend", "normal")),
                            opacity=float(data.get("opacity", 1.0)),
                            fade=float(data.get("fade", 0.0)))
        elif command_name == "animator.param":
            for sid in _stage_ids(data.get("stage"), show_id):
                set_param(sid, str(data.get("slot", "main")), str(data["key"]), data["value"])
        elif command_name == "animator.hide":
            for sid in _stage_ids(data.get("stage"), show_id):
                hide_slot(sid, str(data.get("slot", "main")), fade=float(data.get("fade", 0.0)))
        else:
            logger.warning("ShowAnimator: unknown command {}", command_name)
    except (KeyError, ValueError, TypeError) as exc:
        logger.warning("ShowAnimator command {} failed: {}", command_name, exc)
