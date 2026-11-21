from collections import Counter
from pathlib import Path

from multivoice_reader.casting import assign, narrator_voice, pick_voice
from multivoice_reader.voices import Voice


def voice(id, gender, age, kind="character", genre=""):
    return Voice(id, id, gender, age, kind, "", Path("ref.wav"), "x", genre=genre)


VOICES = {
    v.id: v
    for v in [
        voice("n_m_passion", "男", "中年", "narrator"),
        voice("m_youth", "男", "少年"),
        voice("m_elder", "男", "老年"),
        voice("f_lively", "女", "少年"),
        voice("mine", "男", "青年", "clone"),
    ]
}


def test_narrator_default():
    assert narrator_voice(VOICES) == "n_m_passion"


def test_gender_then_age():
    assert pick_voice({"gender": "女", "age": "青年"}, VOICES, Counter()) == "f_lively"
    assert pick_voice({"gender": "男", "age": "老年"}, VOICES, Counter()) == "m_elder"


def test_prefers_a_voice_nobody_has_yet():
    assert pick_voice({"gender": "男", "age": "老年"}, VOICES, Counter({"m_elder": 1})) == "m_youth"


def test_cloned_voices_are_never_assigned_automatically():
    in_use = Counter({"m_youth": 5, "m_elder": 5, "n_m_passion": 5})
    assert pick_voice({"gender": "男", "age": "青年"}, VOICES, in_use) != "mine"


def test_assign_gives_the_first_characters_the_pick_and_keeps_what_was_given():
    from multivoice_reader.casting import assign

    people = {
        "主角": {"gender": "男", "age": "少年"},
        "配角": {"gender": "男", "age": "少年"},
        "路人": {"gender": "未知", "age": "未知"},
    }
    first = assign(people, VOICES, {})
    assert first["主角"] == "m_youth" and first["配角"] == "m_elder"
    assert "路人" not in first  # nothing known: left to the narrator's voice
    again = assign({"新人": {"gender": "男", "age": "少年"}, **people}, VOICES, first)
    assert again["主角"] == "m_youth" and again["配角"] == "m_elder"
    gone = assign(people, {k: v for k, v in VOICES.items() if k != "m_youth"}, first)
    assert gone["主角"] != "m_youth" and gone["配角"] == "m_elder"


GENRE_VOICES = VOICES | {
    v.id: v
    for v in [
        voice("sus_n_m", "男", "中年", "narrator", "suspense"),
        voice("sus_m_lead", "男", "青年", "character", "suspense"),
        voice("rom_m_lead", "男", "青年", "character", "romance"),
        voice("sys_system", "女", "青年", "system"),
    ]
}


def test_a_genre_brings_its_own_narrator_and_its_voices_come_first():
    assert narrator_voice(GENRE_VOICES, "suspense") == "sus_n_m"
    assert narrator_voice(GENRE_VOICES, "nope") == "n_m_passion"
    people = {"甲": {"gender": "男", "age": "少年"}, "乙": {"gender": "男", "age": "少年"}}
    assert assign(people, GENRE_VOICES, {}, genre="suspense") == {"甲": "sus_m_lead", "乙": "m_youth"}


def test_a_genres_voice_is_not_given_to_someone_of_another_generation():
    people = {"奶奶": {"gender": "男", "age": "老年"}, "甲": {"gender": "男", "age": "青年"}}
    assert assign(people, GENRE_VOICES, {}, genre="suspense") == {"奶奶": "m_elder", "甲": "sus_m_lead"}


def test_without_a_genre_no_voice_made_for_one_is_given_out():
    people = {name: {"gender": "男", "age": "青年"} for name in "甲乙丙丁戊"}
    given = set(assign(people, GENRE_VOICES, {}).values())
    assert given <= {"n_m_passion", "m_youth", "m_elder", "f_lively"}


def test_the_system_speaks_with_the_systems_voice_and_nobody_else_does():
    people = {"系统": {"gender": "未知", "age": "未知"}, "甲": {"gender": "女", "age": "青年"}}
    assert assign(people, GENRE_VOICES, {}) == {"系统": "sys_system", "甲": "f_lively"}
    assert "系统" not in assign({"系统": {"gender": "未知", "age": "未知"}}, VOICES, {})
