import json
import math
import shutil
import subprocess

import pytest

from showanimator.engines import ParamSpec
from showanimator.engines.canvas2d import ENGINE
from showanimator.routes import STATIC_DIR

SPEC = ParamSpec("route", "Route", kind="route", default="A,1,1;B,9,9")


def test_route_accepts_stops_and_falls_back_on_bad_text():
    assert SPEC.clean(" PORTLAND,6385,3745;QUEBEC,5750,960 ") == "PORTLAND,6385,3745;QUEBEC,5750,960"
    assert SPEC.clean("SAN FRANCISCO,8078.5,1096;ST. JOHN'S,1,2") == "SAN FRANCISCO,8078.5,1096;ST. JOHN'S,1,2"
    for bad in ("PORTLAND,6385,3745", "A,1,2;B,3", "A,1,2;B,x,3", "A,-1,2;B,3,4",
                "A,1,2,3;B,4,5", "1A,1,2;B,3,4", "A,1,2;B,3,4;", "", 12):
        assert SPEC.clean(bad) == "A,1,1;B,9,9", bad


def test_default_travel_route_is_valid():
    scene = ENGINE.scenes["travelmap"]
    default = scene.defaults()["route"]
    assert scene.normalize({"route": default})["route"] == default
    assert default.startswith("PORTLAND,")


@pytest.mark.skipif(shutil.which("node") is None, reason="node not installed")
def test_travel_route_geometry_matches_stops():
    # Stops at (0,0), (300,0), (300,400). The first leg bulges north, so the route is longer than 700.
    module = (STATIC_DIR / "engines" / "canvas2d.js").as_uri()
    script = f"""
globalThis.document = {{ createElement: () => ({{}}) }};
const m = await import({json.dumps(module)});
const route = m.buildRoute(m.parseRoute("A,0,0;B,300,0;C,300,400"));
console.log(JSON.stringify({{
  start: m.locate(route, 0), end: m.locate(route, 1), mid: m.locate(route, 0.5),
  total: route.total, stops: route.stopAt.length,
}}));
"""
    out = subprocess.run(["node", "--input-type=module", "-e", script],
                         capture_output=True, text=True, check=True, timeout=30)
    data = json.loads(out.stdout)
    assert data["stops"] == 3
    assert data["total"] > 700
    assert (data["start"]["x"], data["start"]["y"], data["start"]["passed"]) == (0, 0, 1)
    assert (round(data["end"]["x"], 6), round(data["end"]["y"], 6), data["end"]["passed"]) == (300, 400, 3)
    # Halfway is past the first stop and on the straight southbound leg.
    assert data["mid"]["passed"] == 2
    assert math.isclose(data["mid"]["x"], 300, abs_tol=1e-6)
    assert math.isclose(data["mid"]["ang"], math.pi / 2, abs_tol=1e-6)
