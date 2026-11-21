import json

import pytest

from multivoice_reader import voices
from multivoice_reader.voices import export_pack, import_pack, library, remove_voice, voice_id_of


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("MVR_HOME", str(tmp_path))
    return tmp_path


def make_voice(home, name="我的声音"):
    folder = home / "voices" / voice_id_of(name)
    folder.mkdir(parents=True)
    (folder / "ref.wav").write_bytes(b"RIFF....WAVE")
    config = {"name": name, "ref_audio": "ref.wav", "ref_text": "今天天气不错。"}
    (folder / "voice.json").write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
    return folder


def test_own_voices_are_clones_and_marked_as_the_users(home):
    make_voice(home)
    voice = library()["我的声音"]
    assert (voice.kind, voice.own) == ("clone", True)
    assert not any(v.own for v in library().values() if v.id != "我的声音")


def test_public_lists_only_the_samples_that_exist(home):
    folder = make_voice(home)
    (folder / "samples").mkdir()
    (folder / "samples" / "angry.mp3").write_bytes(b"mp3")
    public = library()["我的声音"].public()
    assert public["samples"] == [{"id": "angry", "label": "愤怒"}]
    assert "ref_audio" not in public and "ref_text" not in public


def test_a_pack_exported_from_one_library_can_be_added_to_another(home, tmp_path, monkeypatch):
    make_voice(home)
    pack = tmp_path / "我的声音.voice.zip"
    pack.write_bytes(export_pack(library()["我的声音"]))
    other = tmp_path / "elsewhere"
    monkeypatch.setenv("MVR_HOME", str(other))
    added = import_pack(pack)
    assert (added.name, added.ref_text, added.own) == ("我的声音", "今天天气不错。", True)
    assert added.ref_audio.read_bytes() == b"RIFF....WAVE"


def test_remove_deletes_only_the_users_own_voices(home):
    folder = make_voice(home)
    remove_voice("我的声音")
    assert not folder.exists()
    builtin = next(iter(library()))
    with pytest.raises(LookupError):
        remove_voice(builtin)
    assert builtin in library()


@pytest.mark.parametrize("voice_id", ["../books", "a/b", "", ".."])
def test_remove_cannot_leave_the_library(home, voice_id):
    (home / "books").mkdir()
    with pytest.raises(LookupError):
        remove_voice(voice_id)
    assert (home / "books").exists()


def test_voice_ids_keep_chinese_and_drop_what_a_folder_name_cannot_hold():
    assert voice_id_of("我的 声音/2") == "我的_声音_2"
    assert voice_id_of("！？") == ""
    assert voices.REF_MAX_SECONDS > 0
