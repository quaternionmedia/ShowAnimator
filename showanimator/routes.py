"""HTTP and WebSocket routes for stage pages.

``/animator/stage/<slug>`` serves the stage page. ``/animator/ws/<slug>`` streams
state to it and accepts stage-side debug commands. Private stages need ``?k=<token>``
on both. Other routes (the control page) live in ``ui.py``.
"""

from __future__ import annotations

import asyncio
import hmac
import json
from pathlib import Path

from fastapi import APIRouter, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.responses import HTMLResponse
from loguru import logger

from . import cues, store
from .runtime import runtime

STATIC_DIR = Path(__file__).parent / "static"
router = APIRouter(prefix="/animator", tags=["ShowAnimator"])


def _authorised(stage, token: str | None) -> bool:
    if not stage.private:
        return True
    return bool(token) and hmac.compare_digest(token, stage.token or "")


def _stage_or_none(slug: str, token: str | None):
    stage = store.get_stage_by_slug(runtime.db, slug)
    if stage is None or not _authorised(stage, token):
        return None
    return stage


@router.get("/stage/{slug}", response_class=HTMLResponse)
def stage_page(slug: str, k: str | None = None):
    stage = _stage_or_none(slug, k)
    if stage is None:
        raise HTTPException(404, "stage not found")
    engine = runtime.engines().get(stage.engine)
    if engine is None:
        raise HTTPException(500, f"engine {stage.engine!r} is not installed")
    config = {
        "slug": stage.slug,
        "name": stage.name,
        "token": k if stage.private else None,
        "engine": engine.manifest(),
    }
    # Escape '<' so a stage name can never close the script tag early.
    blob = json.dumps(config).replace("<", "\\u003c")
    html = (STATIC_DIR / "stage.html").read_text(encoding="utf-8")
    return HTMLResponse(html.replace("/*__CONFIG__*/null", blob))


@router.websocket("/ws/{slug}")
async def stage_ws(ws: WebSocket, slug: str, k: str | None = None):
    stage = _stage_or_none(slug, k)
    if stage is None:
        await ws.close(code=4404)  # same answer for missing and unauthorised
        return
    await ws.accept()
    loop = asyncio.get_running_loop()
    queue: asyncio.Queue = asyncio.Queue()

    def listener(msg: dict) -> None:
        # Called from any thread (OSC/MIDI, web handlers). Hop onto this loop.
        try:
            loop.call_soon_threadsafe(queue.put_nowait, msg)
        except RuntimeError:  # loop closed during shutdown
            pass

    # Subscribe before taking the snapshot so no change is missed; clients drop stale revisions.
    unsubscribe = runtime.hub.subscribe(stage.id, listener)
    # The snapshot goes through the queue so one task does all the sending.
    queue.put_nowait({"type": "state", "state": runtime.hub.snapshot(stage.id)})

    async def pump() -> None:
        while True:
            await ws.send_json(await queue.get())

    sender = asyncio.create_task(pump())
    try:
        while True:
            msg = await ws.receive_json()
            try:
                _stage_command(stage.id, msg)
            except (KeyError, ValueError, TypeError) as exc:
                await ws.send_json({"type": "error", "message": str(exc)})
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("ShowAnimator stage socket failed")
    finally:
        unsubscribe()
        sender.cancel()


def _stage_command(stage_id: int, msg: dict) -> None:
    """Debug panel commands from a stage page: {type: set|apply|hide, ...}."""
    kind = msg.get("type")
    slot = str(msg.get("slot", "main"))
    if kind == "set":
        cues.set_param(stage_id, slot, str(msg["key"]), msg["value"])
    elif kind == "apply":
        cues.apply_scene(stage_id, slot, str(msg["scene"]), msg.get("params") or {},
                         blend=str(msg.get("blend", "normal")),
                         opacity=float(msg.get("opacity", 1.0)),
                         fade=float(msg.get("fade", 0.0)))
    elif kind == "hide":
        cues.hide_slot(stage_id, slot, fade=float(msg.get("fade", 0.0)))
    else:
        raise ValueError(f"unknown command {kind!r}")
