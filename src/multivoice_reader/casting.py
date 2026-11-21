"""Choose a voice for each character from what is known about them."""

from collections import Counter

from .voices import UNKNOWN, Voice

DEFAULT_NARRATOR = "n_m_passion"
AGE_ORDER = ["儿童", "少年", "青年", "中年", "老年"]


def narrator_voice(voices: dict[str, Voice]) -> str:
    if DEFAULT_NARRATOR in voices:
        return DEFAULT_NARRATOR
    narrators = [v.id for v in voices.values() if v.kind == "narrator"]
    return (narrators or list(voices))[0]


def _fit(voice: Voice, gender: str, age: str, times_used: int) -> tuple:
    """Higher is better: right gender, then unused, then a character voice, then the closest age."""
    gender_ok = gender == UNKNOWN or voice.gender == gender
    if age in AGE_ORDER and voice.age in AGE_ORDER:
        age_gap = abs(AGE_ORDER.index(age) - AGE_ORDER.index(voice.age))
    else:
        age_gap = 2
    return (gender_ok, -times_used, voice.kind == "character", -age_gap)


def pick_voice(profile: dict, voices: dict[str, Voice], in_use: Counter) -> str:
    """The best free voice for a character. Voices the user cloned are theirs to assign."""
    pool = [v for v in voices.values() if v.kind != "clone"] or list(voices.values())
    gender, age = profile.get("gender", UNKNOWN), profile.get("age", UNKNOWN)
    return max(pool, key=lambda v: _fit(v, gender, age, in_use[v.id])).id


def assign(
    characters: dict[str, dict], voices: dict[str, Voice], before: dict[str, str], narrator: str | None = None
) -> dict[str, str]:
    """A voice for every character, in the order given, so the first get the pick of the voices.

    Whoever already has a voice that still exists keeps it. A character of whom neither gender
    nor age is known is left out: they speak with the narrator's voice until the listener says
    otherwise.
    """
    narrator = narrator if narrator in voices else narrator_voice(voices)
    kept = {name: before[name] for name in characters if before.get(name) in voices}
    in_use = Counter(kept.values())
    in_use[narrator] += 1
    out = {}
    for name, about in characters.items():
        if name in kept:
            out[name] = kept[name]
        elif about.get("gender", UNKNOWN) == UNKNOWN and about.get("age", UNKNOWN) == UNKNOWN:
            continue
        else:
            out[name] = pick_voice(about, voices, in_use)
            in_use[out[name]] += 1
    return out
