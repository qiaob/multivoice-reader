import json

import pytest

from multivoice_reader.design import design, discard, draft, drafts, keep
from multivoice_reader.voices import library


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MVR_HOME", str(tmp_path))
    return tmp_path


def make_draft(home, draft_id, desc="低沉的男声"):
    folder = home / "designs" / draft_id
    folder.mkdir(parents=True)
    (folder / "ref.wav").write_bytes(b"RIFF")
    config = {"name": draft_id, "kind": "design", "gender": "男", "age": "中年", "desc": desc}
    config |= {"ref_audio": "ref.wav", "ref_text": "夜色渐深。"}
    (folder / "voice.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")


def test_a_draft_is_not_a_voice_until_it_is_kept(home):
    make_draft(home, "a1")
    assert [v.id for v in drafts()] == ["a1"] and "a1" not in library()
    voice = keep("a1", "深夜 男声")
    assert drafts() == [] and voice.id == "深夜_男声"
    kept = library()["深夜_男声"]
    assert (kept.name, kept.kind, kept.own, kept.desc) == ("深夜 男声", "design", True, "低沉的男声")


def test_keeping_needs_a_name_that_is_free_and_a_draft_that_is_there(home):
    make_draft(home, "a1")
    make_draft(home, "a2")
    keep("a1", "男声")
    with pytest.raises(ValueError):
        keep("a2", "男声")
    with pytest.raises(ValueError):
        keep("a2", "！！")
    with pytest.raises(LookupError):
        keep("../voices/男声", "别的")
    assert [v.id for v in drafts()] == ["a2"]


def test_a_draft_can_be_thrown_away(home):
    make_draft(home, "a1")
    discard("a1")
    assert drafts() == []
    with pytest.raises(LookupError):
        draft("a1")


def test_what_is_wrong_with_a_request_is_said_before_any_model_is_loaded(home):
    with pytest.raises(ValueError):
        design("  ", home / "x")
    with pytest.raises(ValueError):
        design("低沉的男声", home / "x", text="太短")
    assert not (home / "x").exists()
