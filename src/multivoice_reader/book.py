"""A book on disk: its chapters, what the analysis found, and the audio made so far.

Two processes share the folder. The page server writes only cast.json and target.json; the
worker writes everything else. Every write is whole-file and atomic, so a reader never sees
half a file.
"""

import hashlib
import json
import re
from pathlib import Path

from .text import read_text, split_chapters
from .voices import home


def _write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def _read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def audio_key(engine: str, voice_id: str, emotion: str, text: str) -> str:
    """Same line, same voice, same emotion: same file. Change any of them and it is made anew."""
    return hashlib.sha1(f"{engine}|{voice_id}|{emotion}|{text}".encode()).hexdigest()[:20]


class Book:
    def __init__(self, folder: Path):
        self.dir = folder
        self.id = folder.name
        self.meta = _read_json(folder / "book.json", {})

    @classmethod
    def create(cls, source: Path, title: str | None = None) -> "Book":
        title = title or re.sub(r"\s*作者[:：].*$", "", source.stem).strip() or source.stem
        chapters = split_chapters(read_text(source))
        if not chapters:
            raise ValueError(f"{source.name} 里没有可以朗读的正文")
        slug = re.sub(r"[^\w-]+", "_", title).strip("_")[:40]
        digest = hashlib.sha1(source.read_bytes()).hexdigest()[:8]
        folder = home() / "books" / f"{slug}-{digest}"
        for sub in ("text", "chapters", "audio"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        for index, chapter in enumerate(chapters):
            (folder / "text" / f"{index:05d}.txt").write_text("\n".join(chapter.paragraphs), encoding="utf-8")
        _write_json(folder / "book.json", {"title": title, "chapters": [c.title for c in chapters]})
        return cls(folder)

    @staticmethod
    def all() -> list["Book"]:
        root = home() / "books"
        return [Book(p.parent) for p in sorted(root.glob("*/book.json"))] if root.is_dir() else []

    @property
    def title(self) -> str:
        return self.meta.get("title", self.id)

    @property
    def chapters(self) -> list[str]:
        return self.meta.get("chapters", [])

    def paragraphs(self, chapter: int) -> list[str]:
        return (self.dir / "text" / f"{chapter:05d}.txt").read_text(encoding="utf-8").split("\n")

    # ---- written by the worker ----
    def script(self, chapter: int) -> list[dict] | None:
        """The analysed chapter: [{kind, text, speaker, emotion}], or None if not analysed yet."""
        return _read_json(self.dir / "chapters" / f"{chapter:05d}.json", None)

    def save_script(self, chapter: int, segments: list[dict]) -> None:
        _write_json(self.dir / "chapters" / f"{chapter:05d}.json", segments)

    def characters(self) -> dict[str, dict]:
        """name -> {gender, age, voice, lines}, in order of first appearance."""
        return _read_json(self.dir / "characters.json", {})

    def save_characters(self, characters: dict[str, dict]) -> None:
        _write_json(self.dir / "characters.json", characters)

    def status(self) -> dict:
        return _read_json(self.dir / "status.json", {"state": "idle"})

    def save_status(self, **status) -> None:
        _write_json(self.dir / "status.json", status)

    def audio_path(self, key: str) -> Path:
        return self.dir / "audio" / f"{key}.mp3"

    # ---- written by the page server ----
    def cast(self) -> dict[str, str]:
        """The reader's own choices, name -> voice id; they override the automatic casting."""
        return _read_json(self.dir / "cast.json", {})

    def save_cast(self, cast: dict[str, str]) -> None:
        _write_json(self.dir / "cast.json", cast)

    def target(self) -> dict:
        """Where the listener is, so the worker makes that audio first."""
        return _read_json(self.dir / "target.json", {"chapter": 0, "segment": 0})

    def save_target(self, chapter: int, segment: int) -> None:
        _write_json(self.dir / "target.json", {"chapter": chapter, "segment": segment})
