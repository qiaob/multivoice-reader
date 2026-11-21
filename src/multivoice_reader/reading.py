"""A script being read aloud, on disk: the script, who has which voice, and the audio so far.

Two processes share the folder. The page server writes only cast.json and target.json; the
speech worker writes the rest. Every write is whole-file and atomic.
"""

import hashlib
import shutil
import time
from collections import Counter
from pathlib import Path

from .book import read_json, slug, write_json
from .casting import assign
from .script import NARRATOR, NEUTRAL, normalize
from .voices import Voice, home


def audio_key(engine: str, voice_id: str, emotion: str, text: str) -> str:
    """Same line, same voice, same emotion: same file. Change any of them and it is made anew."""
    return hashlib.sha1(f"{engine}|{voice_id}|{emotion}|{text}".encode()).hexdigest()[:20]


class Reading:
    def __init__(self, folder: Path):
        self.dir = folder
        self.id = folder.name
        self.script = read_json(
            folder / "script.json", {"title": folder.name, "characters": {}, "chapters": []}
        )
        self._characters: dict[str, dict] | None = None

    @classmethod
    def create(cls, script: dict, folder: Path | None = None) -> "Reading":
        """Store a script to be read. One with the same title replaces the earlier one and keeps
        its voices and its audio: a line that did not change is not spoken again."""
        script = normalize(script)
        digest = hashlib.sha1(script["title"].encode()).hexdigest()[:8]
        folder = folder or home() / "readings" / f"{slug(script['title'])}-{digest}"
        (folder / "audio").mkdir(parents=True, exist_ok=True)
        write_json(folder / "script.json", script)
        lines = sum(len(chapter["lines"]) + 1 for chapter in script["chapters"])  # and each title
        write_json(
            folder / "meta.json",
            {"title": script["title"], "chapters": len(script["chapters"]), "lines": lines},
        )
        return cls(folder)

    @staticmethod
    def shelf() -> list[dict]:
        """Every stored reading as {id, title, chapters}, without loading the scripts themselves."""
        root = home() / "readings"
        found = sorted(root.glob("*/meta.json")) if root.is_dir() else []
        return [{"id": p.parent.name, **read_json(p, {})} for p in found]

    @staticmethod
    def open(reading_id: str) -> "Reading | None":
        folder = folder_of(reading_id)
        return Reading(folder) if folder else None

    def remove(self) -> None:
        shutil.rmtree(self.dir)

    # ---- speaking all of it ahead of time ----
    def wanted_whole(self) -> float:
        """When the whole script was asked to be spoken, or 0 if it was not."""
        return read_json(self.dir / "whole.json", {}).get("at", 0.0)

    def want_whole(self, wanted: bool) -> None:
        if wanted:
            write_json(self.dir / "whole.json", {"at": time.time()})
        else:
            (self.dir / "whole.json").unlink(missing_ok=True)

    @property
    def title(self) -> str:
        return self.script["title"]

    @property
    def chapters(self) -> list[str]:
        return [chapter["title"] for chapter in self.script["chapters"]]

    def segments(self, chapter: int) -> list[dict]:
        """What is spoken for a chapter, in order: its title, then its lines."""
        found = self.script["chapters"][chapter]
        title = {"text": found["title"], "speaker": NARRATOR, "emotion": NEUTRAL, "para": -1}
        return [title, *found["lines"]]

    def characters(self) -> dict[str, dict]:
        """name -> {gender, age, lines}, the ones who speak most first."""
        if self._characters is None:
            counts = Counter(line["speaker"] for c in self.script["chapters"] for line in c["lines"])
            names = sorted(self.script["characters"], key=lambda name: -counts[name])
            self._characters = {
                name: {**self.script["characters"][name], "lines": counts[name]} for name in names
            }
        return self._characters

    # ---- who has which voice ----
    def cast(self) -> dict[str, str]:
        """The listener's own choices, name -> voice id; they override the automatic casting."""
        return read_json(self.dir / "cast.json", {})

    def save_cast(self, cast: dict[str, str]) -> None:
        write_json(self.dir / "cast.json", cast)

    def genre(self) -> str:
        """The kind of story the listener said this is (see casting.GENRES); "" if they did not."""
        return read_json(self.dir / "genre.json", {}).get("genre", "")

    def save_genre(self, genre: str) -> None:
        """Read it as another kind of story. The automatic casting is done over, so that the
        new kind's voices are used; what the listener chose themselves stays."""
        write_json(self.dir / "genre.json", {"genre": genre})
        (self.dir / "assigned.json").unlink(missing_ok=True)

    def assigned(self, voices: dict[str, Voice]) -> dict[str, str]:
        """The automatic casting. A character keeps the voice it was first given; only
        characters that are new, or whose voice is gone, are given one now."""
        before = read_json(self.dir / "assigned.json", {})
        now = assign(self.characters(), voices, before, self.cast().get(NARRATOR), self.genre())
        if now != before:
            write_json(self.dir / "assigned.json", now)
        return now

    # ---- where the listener is, and what the worker is doing ----
    def target(self) -> dict:
        return read_json(self.dir / "target.json", {"chapter": 0, "segment": 0})

    def save_target(self, chapter: int, segment: int) -> None:
        write_json(self.dir / "target.json", {"chapter": chapter, "segment": segment})

    def status(self) -> dict:
        return read_json(self.dir / "status.json", {"state": "idle"})

    def save_status(self, **status) -> None:
        write_json(self.dir / "status.json", status)

    def audio_path(self, key: str) -> Path:
        return self.dir / "audio" / f"{key}.mp3"


def folder_of(reading_id: str) -> Path | None:
    """Where the reading with this id is stored. The id may come from a URL, so it has to be
    the name of a folder that is there, not a path to somewhere else."""
    root = home() / "readings"
    known = root.is_dir() and any(p.name == reading_id for p in root.iterdir())
    return root / reading_id if known and (root / reading_id / "script.json").is_file() else None


def whole_queue() -> list[str]:
    """Ids of the readings asked to be spoken whole, in the order they were asked."""
    root = home() / "readings"
    asked = [(read_json(p, {}).get("at", 0.0), p.parent.name) for p in root.glob("*/whole.json")]
    return [reading_id for _, reading_id in sorted(asked)]
