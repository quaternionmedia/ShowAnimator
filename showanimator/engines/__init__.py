"""Rendering engine contract and registry.

An engine is a Python manifest (scenes and their parameters) plus a browser
module at ``script`` that draws them. The core owns state, transport, fades
and the debug UI; the engine owns drawing and blend modes.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field

import pluggy

from ..media import IMAGE_NAME

hookspec = pluggy.HookspecMarker("showrunner")
hookimpl = pluggy.HookimplMarker("showrunner")

BLENDS = ("normal", "add", "subtract", "mask")
_HEX = re.compile(r"^#[0-9a-fA-F]{6}$")
_POINT = r"[A-Za-z][A-Za-z .'-]{0,23},\d{1,6}(?:\.\d{1,4})?,\d{1,6}(?:\.\d{1,4})?"
# 'NAME,x,y;NAME,x,y;...' with 2 to 20 stops, x and y in image pixels.
_ROUTE = re.compile(rf"{_POINT}(?:;{_POINT}){{1,19}}")


@dataclass(frozen=True)
class ParamSpec:
    """One scene parameter. ``kind`` is 'range' (numeric, min/max/step), 'color' (#rrggbb),
    'image' (a file name in the media folder) or 'route' (travel-map stops, see _ROUTE)."""

    key: str
    label: str
    kind: str = "range"
    min: float = 0.0
    max: float = 1.0
    step: float = 0.01
    default: float | str = 0.0

    def clean(self, value):
        """Coerce ``value`` to this param's type and range; fall back to the default."""
        if self.kind == "color":
            return value if isinstance(value, str) and _HEX.match(value) else self.default
        if self.kind == "image":
            return value if isinstance(value, str) and IMAGE_NAME.fullmatch(value) else self.default
        if self.kind == "route":
            text = value.strip() if isinstance(value, str) else ""
            return text if _ROUTE.fullmatch(text) else self.default
        try:
            v = float(value)
        except (TypeError, ValueError):
            return self.default
        return min(self.max, max(self.min, v))


@dataclass(frozen=True)
class Scene:
    id: str
    label: str
    params: tuple[ParamSpec, ...] = ()

    def defaults(self) -> dict:
        return {p.key: p.default for p in self.params}

    def normalize(self, params: dict | None) -> dict:
        """Merge over defaults, drop unknown keys, coerce each value."""
        params = params or {}
        return {p.key: p.clean(params.get(p.key, p.default)) for p in self.params}


@dataclass(frozen=True)
class Engine:
    id: str
    label: str
    script: str  # URL of the browser ES module exporting create(canvas)
    scenes: dict[str, Scene] = field(default_factory=dict)

    def manifest(self) -> dict:
        """JSON-safe description sent to stage pages and the control UI."""
        return {
            "id": self.id,
            "label": self.label,
            "script": self.script,
            "scenes": [
                {
                    "id": s.id,
                    "label": s.label,
                    "params": [vars(p) for p in s.params],
                }
                for s in self.scenes.values()
            ],
        }


class AnimatorSpec:
    """Hook spec for engines contributed by other plugins."""

    @hookspec
    def showanimator_get_engines(self):
        """Return an ``Engine`` or a list of them to make available on stages."""


def collect(pm=None) -> dict[str, Engine]:
    """Built-in engines plus any contributed through the hook. First id wins."""
    from .canvas2d import ENGINE

    engines: dict[str, Engine] = {ENGINE.id: ENGINE}
    if pm is None or not hasattr(pm.hook, "showanimator_get_engines"):
        return engines
    for result in pm.hook.showanimator_get_engines():
        for eng in result if isinstance(result, list) else [result]:
            if eng is not None and eng.id not in engines:
                engines[eng.id] = eng
    return engines
