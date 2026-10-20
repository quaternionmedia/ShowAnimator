import pytest

from showanimator.engines import Engine, collect
from showanimator.engines.canvas2d import ENGINE
from showanimator.state import StageHub

PULSE = ENGINE.scenes["pulse"]
SOLID = ENGINE.scenes["solid"]


def test_apply_merges_params_over_defaults():
    hub = StageHub()
    snap = hub.apply(1, "main", PULSE, {"speed": 2})
    assert snap["slots"][0]["params"] == {"color": "#ffffff", "speed": 2.0, "size": 0.3}


def test_params_are_clamped_and_bad_colours_fall_back():
    hub = StageHub()
    hub.apply(1, "main", PULSE, {"speed": 99, "color": "red"})
    params = hub.snapshot(1)["slots"][0]["params"]
    assert params["speed"] == 4.0
    assert params["color"] == "#ffffff"


def test_set_holds_until_next_apply():
    hub = StageHub()
    hub.apply(1, "main", PULSE, {"speed": 2})
    hub.set_param(1, "main", "speed", 3)
    assert hub.snapshot(1)["slots"][0]["params"]["speed"] == 3
    hub.apply(1, "main", PULSE)  # a new apply replaces params with defaults
    assert hub.snapshot(1)["slots"][0]["params"]["speed"] == 1


def test_revision_and_listeners_see_every_change():
    hub = StageHub()
    seen = []
    unsubscribe = hub.subscribe(1, seen.append)
    hub.apply(1, "main", SOLID)
    hub.set_param(1, "main", "color", "#123456")
    assert [m["state"]["revision"] for m in seen] == [1, 2]
    unsubscribe()
    hub.apply(1, "main", SOLID)
    assert len(seen) == 2


def test_set_on_missing_slot_is_none_and_bad_param_raises():
    hub = StageHub()
    assert hub.set_param(1, "ghost", "color", "#000000") is None
    hub.apply(1, "main", SOLID)
    with pytest.raises(KeyError):
        hub.set_param(1, "main", "nope", 1)


def test_hide_keeps_scene_at_zero_opacity():
    hub = StageHub()
    hub.apply(1, "main", SOLID)
    slot = hub.hide(1, "main", fade=2)["slots"][0]
    assert (slot["scene"], slot["opacity"], slot["fade"]) == ("solid", 0.0, 2.0)


def test_unknown_blend_is_rejected():
    with pytest.raises(ValueError):
        StageHub().apply(1, "main", SOLID, blend="screen")


def test_registry_builtin_wins_and_plugins_add_engines():
    from types import SimpleNamespace

    extra = Engine("extra", "Extra", "/x.js")
    dup = Engine("canvas2d", "Impostor", "/evil.js")

    class Hook:
        def showanimator_get_engines(self):
            return [extra, dup]

    engines = collect(SimpleNamespace(hook=Hook()))
    assert engines["canvas2d"] is ENGINE
    assert engines["extra"] is extra
