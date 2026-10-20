import pytest

from showanimator import store


def test_slugs_are_unique_across_shows(db, show):
    sid, _ = show
    a = store.create_stage(db, sid, "Left Wall")
    b = store.create_stage(db, sid, "Left Wall")
    assert (a.slug, b.slug) == ("left-wall", "left-wall-2")
    with pytest.raises(ValueError):
        store.create_stage(db, sid, "Other", slug="left-wall")


def test_private_token_rotates_on_each_enable_and_clears_when_off(db, show):
    sid, _ = show
    st = store.create_stage(db, sid, "Back", private=True)
    first = st.token
    st = store.update_stage(db, st.id, private=False)
    assert st.token is None
    st = store.update_stage(db, st.id, private=True)
    assert st.token and st.token != first


def test_add_animation_validates_scene_and_action(db, show):
    _, (c1, _) = show
    with pytest.raises(ValueError):
        store.add_animation(db, c1, scene="nope")
    with pytest.raises(ValueError):
        store.add_animation(db, c1, action="show")  # a show step needs a scene
    with pytest.raises(ValueError):
        store.add_animation(db, c1, scene="solid", blend="screen")


def test_delete_stage_removes_its_steps_only(db, show):
    sid, (c1, _) = show
    a = store.create_stage(db, sid, "A")
    b = store.create_stage(db, sid, "B")
    store.add_animation(db, c1, stage_id=a.id, scene="solid")
    store.add_animation(db, c1, stage_id=b.id, scene="solid")
    store.delete_stage(db, a.id)
    assert [r.stage_id for r in store.list_animations(db, c1)] == [b.id]
