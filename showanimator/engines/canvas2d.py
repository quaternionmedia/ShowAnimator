"""Default engine: plain Canvas 2D, no extra dependencies. Drawing lives in static/engines/canvas2d.js."""

from . import Engine, ParamSpec, Scene

_COLOR = ParamSpec("color", "Colour", kind="color", default="#ffffff")
_COLOR_B = ParamSpec("color2", "Colour 2", kind="color", default="#000000")
_IMAGE = ParamSpec("image", "Painting", kind="image", default="")
_RATE = ParamSpec("speed", "Speed (Hz)", min=0, max=0.2, step=0.005, default=0.03)

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
            # Zoom must stay above 1 so the slow pan and water sway never reveal an edge.
            Scene(
                "painting",
                "Painting",
                (
                    _IMAGE,
                    ParamSpec("zoom", "Zoom", min=1.1, max=1.6, step=0.01, default=1.15),
                    ParamSpec("drift", "Drift", min=0, max=0.8, step=0.01, default=0.5),
                    ParamSpec("period", "Drift period (s)", min=10, max=600, step=5, default=180),
                    ParamSpec("sway", "Water sway", min=0, max=0.01, step=0.0005, default=0.002),
                    ParamSpec("brightness", "Brightness", min=-1, max=1, step=0.01, default=0),
                    ParamSpec("tint", "Tint", kind="color", default="#ffffff"),
                    ParamSpec("tint_strength", "Tint strength", min=0, max=1, step=0.01, default=0),
                ),
            ),
            Scene(
                "fog",
                "Fog",
                (
                    _COLOR,
                    _RATE,
                    ParamSpec("density", "Density", min=0, max=1, step=0.01, default=0.5),
                    ParamSpec("size", "Blob size", min=0.1, max=1, step=0.01, default=0.5),
                ),
            ),
            Scene(
                "sparkle",
                "Sparkle",
                (
                    _COLOR,
                    ParamSpec("count", "Stars", min=10, max=400, step=10, default=120),
                    ParamSpec("rate", "Twinkle (Hz)", min=0, max=4, step=0.05, default=1),
                    ParamSpec("size", "Star size", min=0.5, max=6, step=0.1, default=2),
                ),
            ),
        )
    },
)
