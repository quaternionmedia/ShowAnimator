import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from showanimator import routes, store


@pytest.fixture
def client(db):
    app = FastAPI()
    app.include_router(routes.router)
    return TestClient(app)


def test_private_stage_rejects_missing_and_bad_key(db, show, client):
    sid, _ = show
    st = store.create_stage(db, sid, "Back", private=True)
    assert client.get(f"/animator/stage/{st.slug}").status_code == 404
    assert client.get(f"/animator/stage/{st.slug}?k=nope").status_code == 404
    assert client.get(f"/animator/stage/{st.slug}?k={st.token}").status_code == 200


def test_private_stage_websocket_rejects_bad_key(db, show, client):
    sid, _ = show
    st = store.create_stage(db, sid, "Back", private=True)
    with pytest.raises(WebSocketDisconnect) as bad:
        with client.websocket_connect(f"/animator/ws/{st.slug}?k=nope") as ws:
            ws.receive_json()
    assert bad.value.code == 4404
    with client.websocket_connect(f"/animator/ws/{st.slug}?k={st.token}") as ws:
        assert ws.receive_json()["type"] == "state"


def test_unknown_stage_is_404(client):
    assert client.get("/animator/stage/nope").status_code == 404


def test_media_list_and_file_serving(client, tmp_path, monkeypatch):
    from showanimator.runtime import runtime

    monkeypatch.setattr(runtime, "media_dir", tmp_path)
    (tmp_path / "cole-ruins.png").write_bytes(b"\x89PNG fake")
    (tmp_path / "notes.txt").write_text("not an image")
    (tmp_path / "dusk-lake.jpg").write_bytes(b"\xff\xd8 fake")

    assert client.get("/animator/media").json() == ["cole-ruins.png", "dusk-lake.jpg"]
    assert client.get("/animator/media/cole-ruins.png").content == b"\x89PNG fake"
    assert client.get("/animator/media/notes.txt").status_code == 404
    assert client.get("/animator/media/..%2Fshow.db").status_code == 404
    assert client.get("/animator/media/missing.png").status_code == 404
