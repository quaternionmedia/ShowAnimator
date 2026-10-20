# Plan: ShowAnimator — live browser animations driven from ShowRunner

## Context

ShowAnimator is a ShowRunner plugin (`showanimator`) that renders live animations in a browser on named **stages**. A ShowRunner
instance controls them: a dedicated ShowAnimator control page fires cues and edits live parameters.

Decisions from the user:
- Default renderer: plain Canvas 2D, no new dependencies. The architecture must allow other rendering engines.
- Cue text (`Cue.notes`) is reserved for short human labels. Cue animation data goes in a separate `animations` table.
- ShowAnimator has its own control page that fires cues on stages.
- Stages and animations are stored **per show, in the database**. No show.toml config.
- Controlled networks: a simple labeled slug is the default link. An option makes a stage use an unguessable private link (token).
- Stage page: tap-to-start overlay (needed for fullscreen), fullscreen by default, `?debug=1` shows controls on the same page.
- Slider changes apply immediately and hold until a cue or another action overwrites them.

Repo state:
- `/home/harpo/ShowAnimator`: empty uv project (`main.py` placeholder, `requires-python >=3.14`, no deps, no commits).
- Host: `/home/harpo/ShowRunner` (v0.5.1, pluggy). External plugins load through the `showrunner` entry point group (`src/showrunner/utils.py` `get_plugin_manager`).

## Findings (ShowRunner)

- Hook contract: `src/showrunner/hookspecs.py`. Used here: `showrunner_register`, `_startup(app)`, `_shutdown(app)`, `_get_routes`, `_get_nav`, `_get_status`, `_command(command_name, data)` (called by OSC/MIDI mappings, `src/showrunner/connection.py:391`), `_cue_changed(action, cue, before)` (fires on cue delete in the script viewer).
- Base class: `src/showrunner/plugin.py` `ShowRunnerPlugin` (`_app`, `emit()`).
- Cue model: `src/showrunner/models.py:101` `Cue` (`id`, `cue_list_id`, `number`, `point`, `name`, `layer`, `notes`). `CueList` at `models.py:63`; `Show` at `models.py:19`.
- DB access: `app.db.session()` (`src/showrunner/database.py:81`), `app.db.engine`.
- Schema: `ShowDatabase.create_schema` (`database.py`) runs `create_all` only for a new DB and otherwise requires alembic head. Plugin tables must not need a core migration (see Approach).
- Per-show settings pattern: `src/showrunner/connection.py:429` `load_settings` / `:449` `save_settings` (DB `Config` row). Not used here (the animations need relational rows).
- NiceGUI: `plugins/dashboard.py` calls `ui.run_with(app.api, storage_secret=...)` in `showrunner_startup`. Our NiceGUI pages must be registered in the same startup.
- Nav entries: `showrunner_get_nav` (`label`, `path`, `icon`, `order`).

## Approach

### Package layout (`/home/harpo/ShowAnimator`)

```
pyproject.toml              entry point: showanimator = "showanimator:plugin"; dep: showrunner (editable), websockets? (check uvicorn)
showanimator/
  __init__.py               ShowAnimatorPlugin (hookimpls), module-level `plugin`
  models.py                 SQLModel tables: animator_stages, animator_animations
  engines/
    __init__.py             Engine dataclass + registry; own hookspec `showanimator_get_engines`
    canvas2d.py             default engine: Python manifest (scenes + ParamSpec)
  static/
    stage.html              stage page: tap-to-start, fullscreen, ?debug=1 controls
    stage.js                transport (WebSocket), engine loader, apply/set handling
    engines/canvas2d.js     Canvas 2D renderer: one draw function per scene id
  state.py                  StageHub: in-memory live state per stage, thread-safe, WS fan-out
  store.py                  DB CRUD (stages, animations), private-token generation
  cues.py                   fire(cue_id) -> applies animation rows to stages
  routes.py                 FastAPI: /animator/stage/{slug}, /animator/ws/{slug}, /animator/static
  ui.py                     NiceGUI control page /animator (stages, cue list, fire, sliders, animation editor)
tests/
  test_state.py  test_store.py  test_cues.py  test_routes.py
```

### Rendering engine architecture
- Python side: `Engine(id, label, scenes: dict[scene_id, Scene])`; `Scene(label, params: list[ParamSpec])`; `ParamSpec(key, label, min, max, step, default)`. Registry `engines.get_engines()` = built-in `canvas2d` + results of hook `showanimator_get_engines()`. Plugins can add engines by implementing that hookspec.
- JS side: each engine ships a module at `static/engines/<id>.js` exporting `create(container) -> { apply(scene, params), set(key, value), destroy() }`. `stage.js` loads `engines/<stage.engine>.js` and passes it the scene/param state. The engine owns its drawing; the core owns state, transport and UI.
- Stage row has `engine` (default `canvas2d`). The control page offers engines and scenes from the registry, so Python manifests and JS modules must agree on scene ids (the test checks each registered scene has a JS draw function name listed in the engine's manifest).

### Live state (`state.py`)
- `StageHub` holds per stage: `engine`, `scene`, `params` (dict), `revision` (int, bumped each change).
- `apply(stage, scene, params)`: replaces scene and params (params merged over the scene defaults).
- `set(stage, key, value)`: overrides one param. Holds until the next `apply`.
- Each change is pushed to every connected stage WebSocket. Pushes from non-async threads (OSC/MIDI dispatch) go through the server event loop captured at WS connect (`asyncio.run_coroutine_threadsafe`).
- A page connecting late receives the full current state. State is in memory; it is not saved across restarts (not asked).

### Stage links (`routes.py`, `store.py`)
- `animator_stages.slug` is unique per show. Labeled slug: `/animator/stage/<slug>`.
- `private = true` generates `token = secrets.token_urlsafe(16)`. The link becomes `/animator/stage/<slug>?k=<token>`. Both the page and the WebSocket check the token. The control page shows the link with a copy button.
- Stage pages are plain FastAPI routes. Static files go through `app.api.mount('/animator/static', StaticFiles(...))` in startup.

### Stage page (`static/stage.html`, `stage.js`)
- Full viewport canvas. A "Tap to start" overlay calls `requestFullscreen()` and starts the render loop (the tap is required for fullscreen).
- `?debug=1` shows a control panel on the same page: scene select, sliders for the current scene, status (connection, revision). Changes go to the server as `{type:'set'}` / `{type:'scene'}` and come back as state, so every stage and the control page stay in sync.

### Animations (DB)
- `animator_animations`: `id`, `show_id` (FK `shows.id`), `cue_id` (FK `cues.id`), `stage_id` (FK `animator_stages.id`, nullable = all stages), `engine`, `scene`, `params_json` (JSON text), `sequence`.
- A cue may have several rows (one per stage, or one for all stages).
- Cue `notes` is not used.
- Cue delete: `showrunner_cue_changed(action='delete')` removes the cue's animation rows.
- Stage delete removes rows that target that stage.

### Cue firing (`cues.py`)
- `fire(cue_id)`: for each animation row of that cue, call `StageHub.apply(stage, scene, params)` on the matching stage(s).
- Triggers:
  - ShowAnimator control page: "Fire" button per cue (also the source for the stage-specific fire).
  - `showrunner_command` with `animator.cue` `{cue_id}` or `{number, point}` (cue found by number in the show). Usable from OSC/MIDI mappings.
  - `animator.param` `{stage, key, value}` and `animator.scene` `{stage, scene, params}` for direct control from mappings.

### Control page (`ui.py`, NiceGUI at `/animator`, nav entry)
- Stages: add/rename/delete, engine, private toggle, link + copy, open-in-new-window.
- Cues: list the show's cues with their animation rows. Fire button per cue. Editor for a cue's rows: stage (all or one), scene, sliders for the scene's params.
- Live: scene selector and sliders per stage. Changes call the hub directly (same process) and are held until overwritten.
- Uses `app.db` (set by `ShowDB` at startup); the current show comes from the same selection the rest of the UI uses. First show by name if none is selected (matches `first_show_id()` in `connection.py:466`).

### Schema without a core migration
- `showanimator/models.py` tables are created by the plugin at startup: `SQLModel.metadata.create_all(engine, tables=[...], checkfirst=True)`. Cost: alembic in core does not know these tables. Trade-off accepted for a plugin-owned table; if core later gets a plugin-migration mechanism, move them there.
- Models import before `ShowDB.create_schema` on a fresh DB (plugin modules load at `get_plugin_manager`), so new databases get them too.

### Scenes shipped (Canvas 2D)
- Keep it small: `solid` (colour), `gradient` (two colours, angle), `pulse` (circle, speed, size). Enough to prove the param path. Each scene is a draw function in `static/engines/canvas2d.js`.

## Files to modify / create

- New: `ShowAnimator/pyproject.toml` (replace placeholder), `ShowAnimator/showanimator/**` (listed above), `ShowAnimator/tests/**`, `ShowAnimator/README.md`.
- Delete: `ShowAnimator/main.py` (placeholder).
- ShowRunner: no changes.

## Reuse

- `ShowRunnerPlugin` base: `ShowRunner/src/showrunner/plugin.py`.
- `app.db.session()`: `ShowRunner/src/showrunner/database.py:81`.
- Show selection default: `ShowRunner/src/showrunner/connection.py:466` `first_show_id`.
- NiceGUI `ui.run_with`: `ShowRunner/src/showrunner/plugins/dashboard.py`.
- Connection page pattern for the control page: `ShowRunner/src/showrunner/connection_ui.py` (`ConnectionPage`).
- Dispatch of mappings to `showrunner_command`: `ShowRunner/src/showrunner/connection.py:380-391`.

## Steps

- [x] Scaffold package, pyproject with entry point; `uv pip install -e` into the ShowRunner venv; confirm `sr plugin list` shows ShowAnimator
- [x] `models.py` tables + `create_all(checkfirst)` at startup
- [x] `engines/`: Engine/Scene/ParamSpec, registry, own hookspec, canvas2d manifest
- [x] `state.py` StageHub (apply/set, revision, WS fan-out with thread-safe push)
- [x] `store.py` CRUD for stages and animations; slug uniqueness; private token
- [x] `routes.py`: stage page, WS (token check), static mount
- [x] `static/stage.html`, `stage.js`, `engines/canvas2d.js`: tap-to-start, fullscreen, `?debug=1` controls, 3 scenes
- [x] `cues.py` fire + hook impls: `showrunner_command` (`animator.cue`, `animator.param`, `animator.scene`), `showrunner_cue_changed` (delete cleanup), `showrunner_get_nav`
- [x] `ui.py` control page: stages, cues + fire, animation editor, live sliders
- [x] Tests: hub apply/set hold, param merge over defaults, cue fire to all vs one stage, token rejects bad key, cue-delete cleanup, command dispatch, engine registry consistency
- [x] README: install, stage links, cue setup, writing an engine

## Verification

- `uv run pytest` in ShowAnimator (assert-based tests).
- `sr plugin list` shows ShowAnimator; `sr start` loads without error on the existing `show.db` (copy it first) and on a fresh DB.
- Create a stage, open `/animator/stage/<slug>` in a browser: tap to start goes fullscreen; the scene renders.
- `?debug=1`: change a slider on the control page, see it on the stage; change it on the stage debug panel, see it on the control page.
- Private stage: link without `?k=` is rejected (page and WebSocket).
- Fire a cue from the control page and from an OSC/MIDI mapping (`animator.cue`); confirm scene and params change on the right stage(s).
- Delete a cue in the script viewer; its animation rows are removed.
- Reload a stage page mid-show; it resumes the current scene and params.

## Open / noted

- Shortcut: plugin tables bypass alembic (see Approach). Upgrade path: plugin migrations in core.
- Shortcut: no `animation` layer type registered; animations attach to cues directly, so any layer works. Add the layer type later if layer-based filtering is wanted.
- Shortcut: state is in memory, not persisted across restarts.
- Not in scope: audio sync, timeline/keyframe fades (params change instantly; a cue may later carry a fade time), multi-user locking of the control page.
- Confirm before build: uvicorn's WebSocket support on this venv (`websockets` or `wsproto` installed?). Check during scaffold.
