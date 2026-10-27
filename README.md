# ShowAnimator

A ShowRunner plugin that renders live animations in a browser on named **stages**.
ShowRunner cues and mappings drive the stages; the control page edits them live.

## Install

```sh
uv pip install -e /home/harpo/ShowAnimator --python /home/harpo/ShowRunner/.venv/bin/python
sr plugins            # ShowAnimator should be listed
sr start -c show.toml
```

Tables (`animator_stages`, `animator_animations`) are created at startup. No migration is needed.

## Control page and stages

- Open `/animator` (nav: **Animator**). Add stages here: name, engine, and optional private link.
- A stage's page is `/animator/stage/<slug>`. Open it full screen on the output device and tap **Tap to start** (browsers need the tap to enter fullscreen).
- `?debug=1` shows the controls on the same page: per-slot sliders, opacity, blend, hide, and apply.
- **Private** stages use `/animator/stage/<slug>?k=<token>`. Both the page and its WebSocket reject a missing or wrong key. Turning privacy off and on again issues a new token.
- Slugs are unique across all shows, so links never need a show id.

## Cues

Add steps to a cue on the control page: **Fire** plays them. A step targets one stage or all stages, and sets a slot's scene, params, blend, opacity and fade. A `hide` step fades the slot out.
Deleting a cue in the script viewer deletes its steps.

Commands for OSC/MIDI mappings (`showrunner_command`). Stage defaults to all stages of the show:

| Command | Data |
|---|---|
| `animator.cue` | `{number, point?}` or `{cue_id}` (optional `show_id`) |
| `animator.scene` | `{stage?, slot?, scene, params?, blend?, opacity?, fade?}` |
| `animator.param` | `{stage?, slot?, key, value}` |
| `animator.hide` | `{stage?, slot?, fade?}` |

`stage` is a stage slug or id. Unknown commands and bad values are logged and ignored.

Blend modes: `normal` (over), `add`, `subtract`, `mask` (knockout: the slot erases what is beneath it, scaled by opacity).

## Paintings (images)

The `painting` scene draws an image, covering the stage and moving very slowly.

- Put image files (`.png`, `.jpg`, `.webp`) in `animator_media/` next to `show.toml` (the folder is relative to where `sr start` runs, like `show.db`). Set `[plugins.showanimator] media_dir = "..."` to use another folder. Files are listed when the control page or a stage page loads; a new file needs a page reload.
- Params: **Painting** (file name), **Zoom** (1.1-1.6, keeps the edges covered), **Drift** (how far the picture pans, 0-0.8 of the spare room), **Drift period** (seconds for one pan cycle, default 180), **Water sway** (wave amplitude as a fraction of width, applied to the lower 40% of the picture), **Brightness** (-1 darker to 1 lighter), **Tint** and **Tint strength** (colour washed over the picture, 0 = none).
- Routes: `GET /animator/media` lists files; `GET /animator/media/<name>` serves one. Only plain file names are accepted.
- Limits: the picture is drawn at full size every frame, so very large files may stutter on a small box; pre-scale them. Images are not authenticated beyond the stage's own private token.

## Writing an engine

An engine has a Python manifest and a browser module.

1. Python: build an `Engine` with scenes and `ParamSpec`s, and return it from the `showanimator_get_engines` hook (`showrunner.hookimpl`) in your plugin:

   ```python
   from showanimator.engines import Engine, ParamSpec, Scene

   ENGINE = Engine(id="mine", label="Mine", script="/my/static/mine.js",
                   scenes={"wave": Scene("wave", "Wave", (ParamSpec("speed", "Speed", max=4, default=1),))})
   ```

2. Browser: `script` is an ES module exporting `create(canvas)` that returns `{ render(slots, t), resize(w, h), destroy() }`. Each slot is `{name, scene, params, blend, opacity}`; opacity is already faded. Draw with the scene and param keys from step 1.
3. Serve the module yourself (a plugin mounts its own static directory).
4. Test that every scene in the manifest has a draw function, as `tests/test_engines.py` does for `canvas2d`.

The built-in engine is `canvas2d` (`solid`, `gradient`, `pulse`, `painting`, `fog` with slowly drifting soft blobs, `sparkle` with twinkling stars): `showanimator/engines/canvas2d.py` and `showanimator/static/engines/canvas2d.js`.

## Development

```sh
uv run pytest
```

## Limits

- Live state is in memory. A restart clears the stages until the next cue fires.
- Fades are time-based on each slot. Other timing, audio sync, and a timeline are not included.
- Plugin tables bypass alembic. Move them to core migrations if core gains plugin migrations.
