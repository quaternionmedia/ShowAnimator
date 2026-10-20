"""Live stage state: named slots, each with a scene, params, blend and opacity.

Thread-safe. Callers may be OSC/MIDI threads or the web server. Subscribers
receive a full snapshot after every change; they must be safe to call from any
thread (routes hop onto the event loop). Each snapshot carries a ``revision`` so
clients can drop stale messages.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from typing import Callable

from .engines import BLENDS, Scene

Listener = Callable[[dict], None]


@dataclass
class Slot:
    name: str
    scene_obj: Scene
    params: dict
    blend: str = "normal"
    opacity: float = 1.0
    fade: float = 0.0

    def view(self) -> dict:
        return {
            "name": self.name,
            "scene": self.scene_obj.id,
            "params": dict(self.params),
            "blend": self.blend,
            "opacity": self.opacity,
            "fade": self.fade,
        }


@dataclass
class _StageState:
    revision: int = 0
    slots: dict[str, Slot] = field(default_factory=dict)


class StageHub:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._stages: dict[int, _StageState] = {}
        self._listeners: dict[int, list[Listener]] = {}

    # -- reads ---------------------------------------------------------------

    def snapshot(self, stage_id: int) -> dict:
        with self._lock:
            st = self._stages.get(stage_id, _StageState())
            return {"revision": st.revision, "slots": [s.view() for s in st.slots.values()]}

    # -- writes --------------------------------------------------------------

    def apply(
        self,
        stage_id: int,
        slot: str,
        scene: Scene,
        params: dict | None = None,
        blend: str = "normal",
        opacity: float = 1.0,
        fade: float = 0.0,
    ) -> dict:
        """Replace a slot's scene and params. Params merge over the scene defaults."""
        if blend not in BLENDS:
            raise ValueError(f"unknown blend {blend!r}; expected one of {BLENDS}")
        with self._lock:
            st = self._stages.setdefault(stage_id, _StageState())
            st.slots[slot] = Slot(
                name=slot,
                scene_obj=scene,
                params=scene.normalize(params),
                blend=blend,
                opacity=min(1.0, max(0.0, float(opacity))),
                fade=max(0.0, float(fade)),
            )
            return self._changed(stage_id, st)

    def set_param(self, stage_id: int, slot: str, key: str, value) -> dict | None:
        """Override one param; it holds until the slot is applied again. None if no such slot."""
        with self._lock:
            st = self._stages.get(stage_id)
            if st is None or slot not in st.slots:
                return None
            s = st.slots[slot]
            spec = {p.key: p for p in s.scene_obj.params}.get(key)
            if spec is None:
                raise KeyError(f"scene {s.scene_obj.id!r} has no param {key!r}")
            s.params[key] = spec.clean(value)
            return self._changed(stage_id, st)

    def hide(self, stage_id: int, slot: str, fade: float = 0.0) -> dict | None:
        """Fade a slot out (opacity 0). The scene stays so it can be faded back in."""
        with self._lock:
            st = self._stages.get(stage_id)
            if st is None or slot not in st.slots:
                return None
            s = st.slots[slot]
            s.opacity = 0.0
            s.fade = max(0.0, float(fade))
            return self._changed(stage_id, st)

    # -- subscriptions -------------------------------------------------------

    def subscribe(self, stage_id: int, listener: Listener) -> Callable[[], None]:
        with self._lock:
            self._listeners.setdefault(stage_id, []).append(listener)

        def unsubscribe() -> None:
            with self._lock:
                if listener in self._listeners.get(stage_id, []):
                    self._listeners[stage_id].remove(listener)

        return unsubscribe

    def _changed(self, stage_id: int, st: _StageState) -> dict:
        # Caller holds the lock. Listeners run inside it, so they must not block.
        st.revision += 1
        snap = {"revision": st.revision, "slots": [s.view() for s in st.slots.values()]}
        for listener in list(self._listeners.get(stage_id, [])):
            listener({"type": "state", "state": snap})
        return snap
