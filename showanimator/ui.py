"""Control page at ``/animator``: stages, cues (fire and steps) and live sliders.

Runs in the ShowRunner process, so slider changes call the hub directly.
"""

from __future__ import annotations

import json

from nicegui import ui
from sqlmodel import select

from showrunner.models import Cue, CueList
from showrunner.ui import _current_show_id, header

from . import cues, store
from .media import list_media
from .engines import BLENDS
from .runtime import runtime


def _cues(show_id: int) -> list[Cue]:
    with runtime.db.session() as s:
        return list(s.exec(select(Cue).join(CueList).where(CueList.show_id == show_id)
                           .order_by(Cue.sequence, Cue.id)).all())


def _scenes() -> dict:
    """Scene id -> Scene across every installed engine (first engine wins)."""
    found: dict = {}
    for eng in runtime.engines().values():
        for sc in eng.scenes.values():
            found.setdefault(sc.id, sc)
    return found


def _param_control(spec, value, on_change):
    if spec.kind == "color":
        return ui.color_input(spec.label, value=value, on_change=lambda e: on_change(e.value))
    if spec.kind == "image":
        names = list_media(runtime.media_dir)
        if not names:
            ui.label(f"No images in {runtime.media_dir}. Add .png/.jpg/.webp/.gif files and reload.")
        return ui.select(names, label=spec.label, value=value if value in names else None,
                         on_change=lambda e: on_change(e.value))
    with ui.column().classes("w-full gap-0"):
        ui.label(spec.label).classes("text-caption")
        return ui.slider(min=spec.min, max=spec.max, step=spec.step, value=value,
                         on_change=lambda e: on_change(e.value)).props("label-always")


def _set_opacity(stage_id: int, slot: str, value: float) -> None:
    """Change only the slot's opacity, keeping its current scene, params and blend."""
    for s in runtime.hub.snapshot(stage_id)["slots"]:
        if s["name"] == slot and abs(s["opacity"] - value) > 1e-9:
            cues.apply_scene(stage_id, slot, s["scene"], s["params"], blend=s["blend"],
                             opacity=value)


def _set_param(stage_id: int, slot: str, key: str, value) -> None:
    """Apply one param, skipping no-op echoes so synced sliders do not loop."""
    snap = runtime.hub.snapshot(stage_id)
    for s in snap["slots"]:
        if s["name"] == slot and s["params"].get(key) == value:
            return
    try:
        cues.set_param(stage_id, slot, key, value)
    except (KeyError, ValueError) as exc:
        ui.notify(str(exc), type="negative")


def _stages_panel(show_id: int) -> None:
    @ui.refreshable
    def stage_rows() -> None:
        for st in store.list_stages(runtime.db, show_id):
            path = f"/animator/stage/{st.slug}"
            if st.private and st.token:
                path += f"?k={st.token}"
            with ui.row().classes("items-center w-full no-wrap"):
                ui.label(st.name).classes("text-bold")
                ui.label(f"{st.engine} · {st.slug}").classes("text-grey")
                ui.switch("private", value=st.private,
                          on_change=lambda e, s=st: (store.update_stage(runtime.db, s.id, private=e.value),
                                                     stage_rows.refresh()))
                ui.link("open", path, new_tab=True)
                ui.button(icon="content_copy", on_click=lambda p=path: ui.run_javascript(
                    f"navigator.clipboard.writeText(location.origin + {json.dumps(p)})")
                ).props("flat dense").tooltip("copy link")
                ui.button(icon="delete", on_click=lambda s=st: (store.delete_stage(runtime.db, s.id),
                                                                stage_rows.refresh())
                          ).props("flat dense color=negative")

    with ui.card().classes("w-full"):
        ui.label("Stages").classes("text-h6")
        stage_rows()
        engines = list(runtime.engines())
        with ui.row().classes("items-center"):
            name = ui.input("Name")
            engine = ui.select(engines, value=engines[0], label="Engine")
            private = ui.switch("private link")

            def add() -> None:
                if not name.value.strip():
                    ui.notify("Name the stage", type="warning")
                    return
                store.create_stage(runtime.db, show_id, name.value, engine=engine.value,
                                   private=bool(private.value))
                name.value = ""
                stage_rows.refresh()

            ui.button("Add stage", on_click=add)


def _step_form(cue: Cue, show_id: int, refresh, existing=None, on_done=None) -> None:
    """Add a step to ``cue``, or edit ``existing`` (pre-filled, saved in place)."""
    scenes = _scenes()
    stages = store.list_stages(runtime.db, show_id)
    stage_opts = {0: "All stages", **{s.id: s.name for s in stages}}
    scene_opts = {sid: sc.label for sid, sc in scenes.items()}
    old = existing
    initial = json.loads(old.params_json or "{}") if old else {}
    vals: dict = {}
    box = ui.column().classes("w-full")

    with ui.row().classes("items-center"):
        stage = ui.select(stage_opts, value=(old.stage_id or 0) if old else 0, label="Stage")
        action = ui.select(["show", "hide"], value=old.action if old else "show", label="Action")
        slot = ui.input("Slot", value=old.slot if old else "main")
        scene = ui.select(scene_opts, label="Scene",
                          value=old.scene if old else next(iter(scene_opts), None))
        blend = ui.select(list(BLENDS), value=old.blend if old else "normal", label="Blend")
        with ui.column().classes("w-40 gap-0"):
            ui.label("Opacity").classes("text-caption")
            opacity = ui.slider(min=0, max=1, step=0.01,
                                value=old.opacity if old else 1).props("label-always")
        fade = ui.number("Fade (s)", value=old.fade if old else 0, min=0, step=0.5)

    def show_params() -> None:
        box.clear()
        sc = scenes.get(scene.value)
        vals.clear()
        if sc is None:
            return
        # Saved values apply only while the scene is still the saved one.
        shown = initial if old and scene.value == old.scene else {}
        vals.update({p.key: shown.get(p.key, p.default) for p in sc.params})
        with box:
            for spec in sc.params:
                _param_control(spec, vals[spec.key],
                               lambda v, k=spec.key: vals.__setitem__(k, v))

    scene.on_value_change(lambda _: show_params())
    show_params()

    def save() -> None:
        try:
            store.add_animation(runtime.db, cue.id, action=action.value,
                                scene=scene.value if action.value == "show" else None,
                                stage_id=stage.value or None, slot=slot.value or "main",
                                params=vals, blend=blend.value,
                                opacity=float(opacity.value), fade=float(fade.value or 0),
                                animation_id=old.id if old else None)
        except (KeyError, ValueError) as exc:
            ui.notify(str(exc), type="negative")
            return
        refresh()
        if on_done:
            on_done()

    ui.button("Save step" if old else "Add step", icon="save" if old else "add", on_click=save)


def _cues_panel(show_id: int) -> None:
    @ui.refreshable
    def cue_rows() -> None:
        names = {s.id: s.name for s in store.list_stages(runtime.db, show_id)}
        for cue in _cues(show_id):
            title = f"{cue.number or ''}{'.' + str(cue.point) if cue.point else ''} {cue.name or ''}".strip()
            with ui.expansion(title or f"cue {cue.id}").classes("w-full"):
                def fire(c=cue) -> None:
                    n = cues.fire_cue(c.id)
                    ui.notify(f"Fired: {n} slot change(s)")

                ui.button("Fire", icon="play_arrow", on_click=fire)
                for row in store.list_animations(runtime.db, cue.id):
                    what = (f"{row.action} {row.slot}" + (f" · {row.scene}" if row.scene else "")
                            + f" · {names.get(row.stage_id, 'all stages')} · {row.blend}"
                            + f" · op {row.opacity:g} · fade {row.fade:g}s")
                    with ui.row().classes("items-center"):
                        ui.label(what)
                        ui.button(icon="delete", on_click=lambda r=row: (
                            store.delete_animation(runtime.db, r.id), cue_rows.refresh())
                        ).props("flat dense color=negative")
                        with ui.dialog() as dlg, ui.card().classes("w-full"):
                            ui.label("Edit step").classes("text-h6")
                            _step_form(cue, show_id, cue_rows.refresh, existing=row, on_done=dlg.close)
                        ui.button(icon="edit", on_click=dlg.open).props("flat dense")
                _step_form(cue, show_id, cue_rows.refresh)

    with ui.card().classes("w-full"):
        ui.label("Cues").classes("text-h6")
        cue_rows()


def _live_panel(show_id: int) -> None:
    stages = store.list_stages(runtime.db, show_id)
    with ui.card().classes("w-full"):
        ui.label("Live").classes("text-h6")
        if not stages:
            ui.label("No stages yet.")
            return
        layers = store.layers_with_animations(runtime.db, show_id)
        if layers:
            with ui.row().classes("items-center"):
                ui.label("Stop layer:")
                for name in layers:
                    ui.button(name, icon="stop", on_click=lambda n=name: ui.notify(
                        f"Stopped {cues.stop_layer(show_id, n)} slot(s) on {n}")).props("outline color=negative")
        picker = ui.select({s.id: s.name for s in stages}, value=stages[0].id, label="Stage")
        box = ui.column().classes("w-full")
        shape: dict = {"key": None}
        controls: dict = {}  # (slot, key) -> element, for syncing values from elsewhere

        def build(snap: dict) -> None:
            box.clear()
            controls.clear()
            engine = runtime.engines()[store.get_stage(runtime.db, picker.value).engine]
            with box:
                if not snap["slots"]:
                    ui.label("Nothing on this stage.")
                for s in snap["slots"]:
                    sc = engine.scenes.get(s["scene"])
                    with ui.row().classes("items-center"):
                        ui.label(f"{s['name']} · {sc.label if sc else s['scene']}").classes("text-bold")
                        ui.button("Hide", on_click=lambda n=s["name"]: cues.hide_slot(picker.value, n))
                    with ui.column().classes("w-full gap-0"):
                        ui.label("Opacity").classes("text-caption")
                        op = ui.slider(min=0, max=1, step=0.01, value=s["opacity"]).props("label-always")
                    op.on_value_change(lambda e, n=s["name"]: _set_opacity(picker.value, n, float(e.value)))
                    controls[(s["name"], "__opacity")] = op
                    for spec in (sc.params if sc else ()):
                        el = _param_control(spec, s["params"][spec.key],
                                            lambda v, n=s["name"], k=spec.key: _set_param(picker.value, n, k, v))
                        controls[(s["name"], spec.key)] = el

        def tick() -> None:
            snap = runtime.hub.snapshot(picker.value)
            key = (picker.value, tuple((s["name"], s["scene"]) for s in snap["slots"]))
            if key != shape["key"]:
                shape["key"] = key
                build(snap)
                return
            for s in snap["slots"]:
                for k, v in list(s["params"].items()) + [("__opacity", s["opacity"])]:
                    el = controls.get((s["name"], k))
                    if el is not None and el.value != v:
                        el.value = v

        def picked(_) -> None:
            shape["key"] = None  # force a rebuild for the new stage
            tick()

        picker.on_value_change(picked)
        ui.timer(0.5, tick)


def register() -> None:
    @ui.page("/animator")
    def page() -> None:
        ui.dark_mode(True)
        header()
        show_id = _current_show_id()
        if show_id is None:
            ui.label("No show selected").classes("text-h5 q-pa-md")
            return
        with ui.column().classes("w-full q-pa-md gap-4"):
            _stages_panel(show_id)
            _live_panel(show_id)
            _cues_panel(show_id)
