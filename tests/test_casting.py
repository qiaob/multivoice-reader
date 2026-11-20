from collections import Counter
from pathlib import Path

from multivoice_reader.casting import narrator_voice, pick_voice
from multivoice_reader.voices import Voice


def voice(id, gender, age, kind="character"):
    return Voice(id, id, gender, age, kind, "", Path("ref.wav"), "x")


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
