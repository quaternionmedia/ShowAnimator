from showanimator import cues, store
from showanimator.runtime import runtime


def test_cue_fires_to_all_stages_or_only_its_stage(db, show):
    sid, (c1, c2) = show
    a = store.create_stage(db, sid, "Left")
    b = store.create_stage(db, sid, "Right")
    store.add_animation(db, c1, scene="solid", params={"color": "#123456"})  # all stages
    store.add_animation(db, c2, stage_id=b.id, scene="pulse")

    assert cues.fire_cue(c1) == 2
    assert runtime.hub.snapshot(a.id)["slots"][0]["scene"] == "solid"
    assert runtime.hub.snapshot(b.id)["slots"][0]["scene"] == "solid"

    cues.fire_cue(c2)
    assert runtime.hub.snapshot(a.id)["slots"][0]["scene"] == "solid"  # untouched
    assert runtime.hub.snapshot(b.id)["slots"][0]["scene"] == "pulse"


def test_command_dispatch_cue_param_and_bad_input(db, show):
    sid, (c1, _) = show
    a = store.create_stage(db, sid, "Left")
    store.add_animation(db, c1, scene="solid", params={"color": "#123456"})

    cues.handle_command("animator.cue", {"number": "1", "show_id": sid})
    assert runtime.hub.snapshot(a.id)["slots"][0]["params"]["color"] == "#123456"

    cues.handle_command("animator.param", {"stage": a.slug, "key": "color", "value": "#abcdef"})
    assert runtime.hub.snapshot(a.id)["slots"][0]["params"]["color"] == "#abcdef"

    cues.handle_command("animator.bogus", {})  # ignored
    cues.handle_command("animator.cue", {"number": "99", "show_id": sid})  # logged, no raise
    assert runtime.hub.snapshot(a.id)["revision"] == 2


def test_cue_delete_removes_steps_and_update_keeps_them(db, show):
    sid, (c1, _) = show
    store.add_animation(db, c1, scene="solid")
    store.add_animation(db, c1, scene="pulse")
    cues.on_cue_changed("update", {"id": c1}, None)
    assert len(store.list_animations(db, c1)) == 2
    cues.on_cue_changed("delete", {"id": c1}, None)
    assert store.list_animations(db, c1) == []


def test_hide_defaults_to_configured_fade_and_stop_layer_hides_only_that_layer(db, show, monkeypatch):
    from showrunner.models import Cue
    sid, (c1, c2) = show
    a = store.create_stage(db, sid, "Left")
    with db.session() as s:
        for cid, layer in ((c1, "Ruins"), (c2, "Lights")):
            s.get(Cue, cid).layer = layer
        s.commit()
    store.add_animation(db, c1, scene="solid", slot="ruins")
    store.add_animation(db, c2, scene="solid", slot="lamp")
    cues.fire_cue(c1)
    cues.fire_cue(c2)

    monkeypatch.setattr(runtime, "hide_fade", 1.0)
    assert store.layers_with_animations(db, sid) == ["Lights", "Ruins"]
    assert cues.stop_layer(sid, "Ruins") == 1
    by_name = {s["name"]: s for s in runtime.hub.snapshot(a.id)["slots"]}
    assert by_name["ruins"]["opacity"] == 0.0 and by_name["ruins"]["fade"] == 1.0
    assert by_name["lamp"]["opacity"] == 1.0  # other layer untouched
    assert cues.hide_slot(a.id, "lamp", fade=0.25) is not None  # explicit fade still honoured
    assert {s["name"]: s for s in runtime.hub.snapshot(a.id)["slots"]}["lamp"]["fade"] == 0.25
