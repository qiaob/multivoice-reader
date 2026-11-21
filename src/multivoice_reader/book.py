"""A novel being split, on disk: its chapters as text and what the analysis found in them.

Two processes share the folder. The page server writes only target.json; the split worker
writes everything else. Every write is whole-file and atomic, so a reader never sees half a
file.
"""

import hashlib
import json
import re
import shutil
import time
from pathlib import Path

from .script import NARRATOR, normalize
from .text import read_text, split_chapters
from .voices import home


def write_json(path: Path, data) -> None:
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(path)


def read_json(path: Path, default):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return default


def slug(title: str) -> str:
    return re.sub(r"[^\w-]+", "_", title).strip("_")[:40]


class Book:
    def __init__(self, folder: Path):
        self.dir = folder
        self.id = folder.name
        self.meta = read_json(folder / "book.json", {})

    @classmethod
    def create(cls, source: Path, title: str | None = None, folder: Path | None = None) -> "Book":
        """Cut the text into chapters and store them, in the library unless a folder is given."""
        title = title or re.sub(r"\s*作者[:：].*$", "", source.stem).strip() or source.stem
        chapters = split_chapters(read_text(source))
        if not chapters:
            raise ValueError(f"{source.name} 里没有可以朗读的正文")
        digest = hashlib.sha1(source.read_bytes()).hexdigest()[:8]
        folder = folder or home() / "books" / f"{slug(title)}-{digest}"
        for sub in ("text", "chapters"):
            (folder / sub).mkdir(parents=True, exist_ok=True)
        for index, chapter in enumerate(chapters):
            (folder / "text" / f"{index:05d}.txt").write_text("\n".join(chapter.paragraphs), encoding="utf-8")
        write_json(folder / "book.json", {"title": title, "chapters": [c.title for c in chapters]})
        return cls(folder)

    @staticmethod
    def all() -> list["Book"]:
        root = home() / "books"
        return [Book(p.parent) for p in sorted(root.glob("*/book.json"))] if root.is_dir() else []

    @staticmethod
    def open(book_id: str) -> "Book | None":
        """The stored book with this id. The id may come from a URL: it must name a folder there."""
        return next((book for book in Book.all() if book.id == book_id), None)

    def remove(self) -> None:
        shutil.rmtree(self.dir)

    @property
    def title(self) -> str:
        return self.meta.get("title", self.id)

    @property
    def chapters(self) -> list[str]:
        return self.meta.get("chapters", [])

    def paragraphs(self, chapter: int) -> list[str]:
        return (self.dir / "text" / f"{chapter:05d}.txt").read_text(encoding="utf-8").split("\n")

    # ---- written by the split worker ----
    def lines(self, chapter: int) -> list[dict] | None:
        """The split chapter: [{kind, text, para, speaker, emotion}], or None if not split yet."""
        return read_json(self.dir / "chapters" / f"{chapter:05d}.json", None)

    def save_lines(self, chapter: int, lines: list[dict]) -> None:
        write_json(self.dir / "chapters" / f"{chapter:05d}.json", lines)

    def done(self) -> list[bool]:
        """For each chapter, whether it has been split."""
        found = {p.stem for p in (self.dir / "chapters").glob("*.json")}
        return [f"{index:05d}" in found for index in range(len(self.chapters))]

    def characters(self) -> dict[str, dict]:
        """name -> {gender, age, lines}, in order of first appearance."""
        return read_json(self.dir / "characters.json", {})

    def save_characters(self, characters: dict[str, dict]) -> None:
        write_json(self.dir / "characters.json", characters)

    def status(self) -> dict:
        return read_json(self.dir / "status.json", {"state": "idle"})

    def save_status(self, **status) -> None:
        write_json(self.dir / "status.json", status)

    def script(self) -> dict:
        """The chapters split so far as a reading script; ValueError if there are none yet."""
        chapters = []
        for index, title in enumerate(self.chapters):
            lines = self.lines(index)
            if lines is not None:
                chapters.append({"title": title, "lines": [line for line in lines if line["para"] >= 0]})
        about = {name: {"gender": c["gender"], "age": c["age"]} for name, c in self.characters().items()}
        about.pop(NARRATOR, None)
        if not chapters:
            raise ValueError("还没有拆好的章节")
        return normalize({"title": self.title, "characters": about, "chapters": chapters})

    # ---- written by the page server ----
    def until(self) -> int:
        """How many chapters, counted from the first, have been asked for."""
        return read_json(self.dir / "target.json", {}).get("until", 0)

    def asked_at(self) -> float:
        """When that was asked: books are split in the order they were asked for."""
        return read_json(self.dir / "target.json", {}).get("at", 0.0)

    def model(self) -> str:
        """Which model was asked to do the splitting; "" if none was named."""
        return read_json(self.dir / "target.json", {}).get("model", "")

    def save_until(self, chapters: int, model: str | None = None) -> None:
        """Ask for the first `chapters` chapters; without `model`, with the one asked before."""
        asked = {"until": chapters, "at": time.time(), "model": self.model() if model is None else model}
        write_json(self.dir / "target.json", asked)

    def waiting(self) -> bool:
        """Whether a chapter that was asked for is still to be split."""
        return not all(self.done()[: self.until()])
