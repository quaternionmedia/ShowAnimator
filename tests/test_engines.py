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


def test_new_effect_params_are_clamped():
    scene = ENGINE.scenes["sparkle"]
    assert scene.normalize({"count": 9999})["count"] == 400
    assert ENGINE.scenes["painting"].normalize({"brightness": 5})["brightness"] == 1
    assert ENGINE.scenes["painting"].normalize({"tint": "red"})["tint"] == "#ffffff"


def test_image_param_accepts_plain_file_names_only():
    from showanimator.engines import ParamSpec

    spec = ParamSpec("image", "Painting", kind="image", default="")
    assert spec.clean("hudson-rainbow.png") == "hudson-rainbow.png"
    assert spec.clean("The Oxbow (1836), Lake’s edge.JPG") == "The Oxbow (1836), Lake’s edge.JPG"
    for bad in ("../secret.png", "sub/x.png", "x.exe", ".hidden.png", "x.png\n", 3, "x.tif"):
        assert spec.clean(bad) == "", bad


def test_kites_style_is_a_choice_with_a_safe_default():
    scene = ENGINE.scenes["kites"]
    assert scene.normalize({"style": "impressionistic"})["style"] == "impressionistic"
    assert scene.normalize({"style": "cubist"})["style"] == "simple"
    assert scene.normalize({"count": 9999})["count"] == 300
    kites = next(m for m in ENGINE.manifest()["scenes"] if m["id"] == "kites")
    style = next(p for p in kites["params"] if p["key"] == "style")
    assert tuple(style["options"]) == ("realistic", "simple", "impressionistic")

