import re

from showanimator.engines.canvas2d import ENGINE
from showanimator.routes import STATIC_DIR


def test_every_scene_has_a_js_draw_function_and_no_extra_ones():
    js = (STATIC_DIR / "engines" / "canvas2d.js").read_text(encoding="utf-8")
    drawn = set(re.findall(r"^  (\w+)\(c, w, h", js, re.M))
    assert drawn == set(ENGINE.scenes)


def test_manifest_lists_every_scene_and_param():
    manifest = ENGINE.manifest()
    assert [s["id"] for s in manifest["scenes"]] == list(ENGINE.scenes)
    keys = {p["key"] for s in manifest["scenes"] for p in s["params"]}
    assert {"color", "color2", "angle", "speed", "size"} <= keys
