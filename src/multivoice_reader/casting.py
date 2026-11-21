"""Choose a voice for each character from what is known about them."""

from collections import Counter

from .script import SYSTEM
from .voices import UNKNOWN, Voice

DEFAULT_NARRATOR = "n_m_passion"
AGE_ORDER = ["儿童", "少年", "青年", "中年", "老年"]
# Kinds of story a script can be read as. Each has a narrator of its own and a few voices made
# for it, which its characters are given first: slow and low for a ghost story, quick and
# bright for a "system" novel.
GENRES = {
    "suspense": {"name": "悬疑灵异", "narrator": "sus_n_m"},
    "system": {"name": "系统爽文", "narrator": "sys_n_m"},
    "romance": {"name": "言情", "narrator": "rom_n_f"},
}


def narrator_voice(voices: dict[str, Voice], genre: str = "") -> str:
    for voice_id in (GENRES.get(genre, {}).get("narrator"), DEFAULT_NARRATOR):
        if voice_id in voices:
            return voice_id
    narrators = [v.id for v in voices.values() if v.kind == "narrator"]
    return (narrators or list(voices))[0]


def _fit(voice: Voice, gender: str, age: str, times_used: int, genre: str) -> tuple:
    """Higher is better: right gender, then unused, then made for this kind of story (unless
    it is the wrong generation: a grandmother does not get the heroine's voice), then a
    character voice, then the closest age."""
    gender_ok = gender == UNKNOWN or voice.gender == gender
    if age in AGE_ORDER and voice.age in AGE_ORDER:
        age_gap = abs(AGE_ORDER.index(age) - AGE_ORDER.index(voice.age))
    else:
        age_gap = 2
    of_genre = bool(genre) and voice.genre == genre and (age not in AGE_ORDER or age_gap <= 1)
    return (gender_ok, -times_used, of_genre, voice.kind == "character", -age_gap)


def pick_voice(profile: dict, voices: dict[str, Voice], in_use: Counter, genre: str = "") -> str:
    """The best free voice for a character. Voices the user cloned are theirs to assign, the
    system's voice is the system's, and a voice made for another kind of story stays there."""
    pool = [v for v in voices.values() if v.kind in ("narrator", "character") and v.genre in ("", genre)]
    gender, age = profile.get("gender", UNKNOWN), profile.get("age", UNKNOWN)
    return max(pool or list(voices.values()), key=lambda v: _fit(v, gender, age, in_use[v.id], genre)).id


def assign(
    characters: dict[str, dict],
    voices: dict[str, Voice],
    before: dict[str, str],
    narrator: str | None = None,
    genre: str = "",
) -> dict[str, str]:
    """A voice for every character, in the order given, so the first get the pick of the voices.

    Whoever already has a voice that still exists keeps it. A character of whom neither gender
    nor age is known is left out: they speak with the narrator's voice until the listener says
    otherwise. The system, if the story has one, gets the system's voice.
    """
    narrator = narrator if narrator in voices else narrator_voice(voices, genre)
    system = next((v.id for v in voices.values() if v.kind == "system"), None)
    kept = {name: before[name] for name in characters if before.get(name) in voices}
    in_use = Counter(kept.values())
    in_use[narrator] += 1
    out = {}
    for name, about in characters.items():
        if name in kept:
            out[name] = kept[name]
        elif name == SYSTEM and system:
            out[name] = system
        elif about.get("gender", UNKNOWN) == UNKNOWN and about.get("age", UNKNOWN) == UNKNOWN:
            continue
        else:
            out[name] = pick_voice(about, voices, in_use, genre)
            in_use[out[name]] += 1
    return out
