"""Default engine: plain Canvas 2D, no extra dependencies. Drawing lives in static/engines/canvas2d.js."""

from . import Engine, ParamSpec, Scene

_COLOR = ParamSpec("color", "Colour", kind="color", default="#ffffff")
_COLOR_B = ParamSpec("color2", "Colour 2", kind="color", default="#000000")

ENGINE = Engine(
    id="canvas2d",
    label="Canvas 2D",
    script="/animator/static/engines/canvas2d.js",
    scenes={
        s.id: s
        for s in (
            Scene("solid", "Solid", (_COLOR,)),
            Scene(
                "gradient",
                "Gradient",
                (
                    _COLOR,
                    _COLOR_B,
                    ParamSpec("angle", "Angle", min=0, max=360, step=1, default=0),
                ),
            ),
            Scene(
                "pulse",
                "Pulse",
                (
                    _COLOR,
                    ParamSpec("speed", "Speed (Hz)", min=0, max=4, step=0.05, default=1),
                    ParamSpec("size", "Size", min=0.05, max=1.0, step=0.01, default=0.3),
                ),
            ),
        )
    },
)
