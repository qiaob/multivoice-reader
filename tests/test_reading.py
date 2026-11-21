from pathlib import Path

import pytest

from multivoice_reader.reading import Reading, audio_key
from multivoice_reader.voices import Voice
from multivoice_reader.worker import caster, next_job, segment_audio_key

SCRIPT = {
    "title": "夜雨",
    "characters": {"张三": {"gender": "男", "age": "少年"}, "李四": {"gender": "女", "age": "少年"}},
    "chapters": [
        {
            "title": "第一章",
            "lines": [{"text": "夜色渐深。"}, {"speaker": "张三", "emotion": "愤怒", "text": "走！"}],
        },
        {
            "title": "第二章",
            "lines": [{"speaker": "李四", "text": "好。"}, {"speaker": "李四", "text": "再见。"}],
        },
    ],
}


def voice(id, gender, age, kind="character", genre=""):
    return Voice(id, id, gender, age, kind, "", Path("ref.wav"), "x", genre=genre)


VOICES = {
    v.id: v
    for v in [
        voice("n_m_passion", "男", "中年", "narrator"),
        voice("m_youth", "男", "少年"),
        voice("f_lively", "女", "少年"),
        voice("mine", "男", "青年", "clone"),
    ]
}


@pytest.fixture
def reading(tmp_path, monkeypatch):
    monkeypatch.setenv("MVR_HOME", str(tmp_path))
    return Reading.create(SCRIPT)


def test_a_chapter_is_spoken_title_first(reading):
    assert reading.chapters == ["第一章", "第二章"]
    assert [s["text"] for s in reading.segments(0)] == ["第一章", "夜色渐深。", "走！"]
    assert reading.segments(0)[0]["speaker"] == "旁白"


def test_characters_come_with_the_ones_who_speak_most_first(reading):
    assert list(reading.characters()) == ["李四", "张三"]
    assert reading.characters()["李四"] == {"gender": "女", "age": "少年", "lines": 2}


def test_voices_are_chosen_on_the_reading_side_and_the_listener_has_the_last_word(reading):
    voice_of = caster(reading, VOICES)
    assert (voice_of("旁白"), voice_of("张三"), voice_of("李四")) == ("n_m_passion", "m_youth", "f_lively")
    assert voice_of("没见过的人") == "n_m_passion"
    reading.save_cast({"张三": "mine", "旁白": "f_lively"})
    voice_of = caster(reading, VOICES)
    assert (voice_of("旁白"), voice_of("张三"), voice_of("李四")) == ("f_lively", "mine", "f_lively")


def test_the_same_title_replaces_the_script_and_keeps_the_voices_and_the_audio(reading):
    reading.save_cast({"张三": "mine"})
    _, key = segment_audio_key(reading.segments(0)[2], caster(reading, VOICES))
    reading.audio_path(key).write_bytes(b"mp3")
    longer = {**SCRIPT, "chapters": [*SCRIPT["chapters"], {"title": "第三章", "lines": [{"text": "完。"}]}]}
    again = Reading.create(longer)
    assert again.id == reading.id and len(again.chapters) == 3
    assert again.cast() == {"张三": "mine"} and again.audio_path(key).exists()
    assert Reading.shelf() == [{"id": reading.id, "title": "夜雨", "chapters": 3, "lines": 8}]
    assert Reading.open(reading.id).title == "夜雨" and Reading.open("../books") is None


def test_the_worker_speaks_from_where_the_listener_is_and_skips_what_is_made(reading):
    reading.save_target(0, 1)
    chapter, index, segment, voice_id, key = next_job(reading, VOICES, set())
    assert (chapter, index, segment["text"], voice_id) == (0, 1, "夜色渐深。", "n_m_passion")
    reading.audio_path(key).write_bytes(b"mp3")
    assert next_job(reading, VOICES, set())[2]["text"] == "走！"
    assert next_job(reading, VOICES, {next_job(reading, VOICES, set())[4]})[2]["text"] == "第一章"


def test_audio_key_changes_with_voice_and_emotion():
    base = audio_key("ming", "v1", "中性", "你好")
    assert base == audio_key("ming", "v1", "中性", "你好")
    assert len({base, audio_key("ming", "v2", "中性", "你好"), audio_key("ming", "v1", "愤怒", "你好")}) == 3


def test_a_genre_recasts_what_was_automatic_and_leaves_what_the_listener_chose(reading):
    voices = VOICES | {
        "sus_n_m": voice("sus_n_m", "男", "中年", "narrator", "suspense"),
        "sus_f": voice("sus_f", "女", "青年", "character", "suspense"),
    }
    reading.save_cast({"张三": "mine"})
    assert caster(reading, voices)("李四") == "f_lively" and reading.genre() == ""
    reading.save_genre("suspense")
    voice_of = caster(reading, voices)
    assert (voice_of("旁白"), voice_of("张三"), voice_of("李四")) == ("sus_n_m", "mine", "sus_f")
    reading.save_genre("")
    assert caster(reading, voices)("旁白") == "n_m_passion" and caster(reading, voices)("李四") == "f_lively"
